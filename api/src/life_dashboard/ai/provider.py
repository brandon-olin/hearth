"""AI provider abstraction.

AIProvider is a structural Protocol — any object with matching stream_chat and
complete methods satisfies it. This keeps the service layer decoupled from any
specific SDK.

Current implementations: AnthropicProvider.
Planned: OpenAIProvider, OllamaProvider (both will be drop-in replacements).
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class AIProvider(Protocol):
    """Minimal interface every AI backend must satisfy."""

    def stream_chat(
        self,
        messages: list[dict],
        system: str,
        *,
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[tuple[str, Any]]:
        """Yield structured streaming events.

        Each yielded value is a tuple of (event_type, payload):
          ("text", str)       — a text delta from the model
          ("done", message)   — the final complete message object; check
                                message.stop_reason == "tool_use" to know
                                whether tool calls are present in message.content

        Defined as a plain def returning AsyncIterator so both async generator
        functions and regular async methods that return an async iterator
        satisfy the Protocol.
        """
        ...

    async def complete(
        self,
        messages: list[dict],
        system: str,
        *,
        max_tokens: int = 1024,
    ) -> tuple[str, int, int, str]:
        """Non-streaming call; returns (text, input_tokens, output_tokens, model).

        Used for background tasks (e.g. memory refresh) where streaming
        is not needed.  The token counts and model string allow callers to
        record usage without coupling them to the provider SDK.
        """
        ...


class AnthropicProvider:
    """Anthropic Claude backend.

    CHAT_MODEL is used for interactive streaming responses.
    FAST_MODEL is used for background non-streaming tasks (memory refresh,
    auto-titling) where cost and latency matter more than capability.
    """

    CHAT_MODEL = "claude-sonnet-4-6"
    FAST_MODEL = "claude-haiku-4-5-20251001"

    def __init__(self, api_key: str) -> None:
        # Import lazily so the module can be imported even if anthropic is not
        # installed (e.g. in test environments that mock the provider).
        from anthropic import AsyncAnthropic
        self._client = AsyncAnthropic(api_key=api_key)

    async def stream_chat(
        self,
        messages: list[dict],
        system: str,
        *,
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[tuple[str, Any]]:  # type: ignore[override]
        """Async generator yielding ("text", chunk) deltas then ("done", message).

        Retries once on 429 rate-limit errors after the server-suggested delay
        (or 60 s if no Retry-After header is present).
        """
        import asyncio
        from anthropic import RateLimitError

        kwargs: dict[str, Any] = dict(
            model=self.CHAT_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        if tools:
            kwargs["tools"] = tools

        for attempt in range(2):
            try:
                async with self._client.messages.stream(**kwargs) as stream:
                    async for text in stream.text_stream:
                        yield ("text", text)
                    final = await stream.get_final_message()
                yield ("done", final)
                return
            except RateLimitError as exc:
                if attempt == 1:
                    raise  # second attempt also failed — propagate
                # Parse Retry-After if available, otherwise wait 60 s.
                retry_after = 60
                if hasattr(exc, "response") and exc.response is not None:
                    header = exc.response.headers.get("retry-after")
                    if header and header.isdigit():
                        retry_after = int(header)
                yield ("rate_limited", retry_after)
                await asyncio.sleep(retry_after)

    async def complete(
        self,
        messages: list[dict],
        system: str,
        *,
        max_tokens: int = 1024,
    ) -> tuple[str, int, int, str]:
        """Non-streaming call.

        Returns (response_text, input_tokens, output_tokens, model_string).
        Token counts come directly from the API response so callers can record
        usage without depending on the Anthropic SDK types.
        """
        response = await self._client.messages.create(
            model=self.FAST_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=messages,  # type: ignore[arg-type]
        )
        text = ""
        if response.content and hasattr(response.content[0], "text"):
            text = response.content[0].text
        input_tokens = getattr(response.usage, "input_tokens", 0) if response.usage else 0
        output_tokens = getattr(response.usage, "output_tokens", 0) if response.usage else 0
        return text, input_tokens, output_tokens, response.model or self.FAST_MODEL
