# 020 — Implement prompt caching

Status: READY TO BUILD 2026-07-22. Implementation companion to
`plans/019-ai-cost-control.md` (which is the why; this is the how).
Priority: **P1.** Effort: S/M — roughly a day including verification.
Bears a migration → parents on head **0053**, cannot run concurrently with
another migration-bearing branch.

Verified against Anthropic's prompt-caching documentation, 2026-07-22.

---

## What we're caching and why

`stream_chat` currently sends, on every one of up to six calls per user turn:

| Segment | Size | Stability |
|---|---|---|
| `TOOL_DEFINITIONS` (66 schemas) | **~15,582 tokens** | Module constant — identical for every user, every request |
| System prompt | ~2,000 tokens | Stable within a conversation |
| Message history (≤20) | 2,000–8,000 | Grows each turn |

The tool array is the prize: it is the largest segment *and* the most stable.
Cache reads cost 10% of base input, so caching it turns $0.047/call into
$0.005/call.

**Cache prefixes are built in the order `tools → system → messages`.** A
breakpoint caches everything up to and including that block, cumulatively.

## Breakpoint plan

Two explicit breakpoints, plus automatic caching for the growing history:

1. **Last tool definition** → caches the ~15.6k tool array.
   This prefix is *identical across every user and every conversation*, so it
   is shared cache-wide. Highest hit rate in the system.
2. **System block** → caches tools + system (~17.6k cumulative).
   Per-user (memory text) and per-mode (chat vs journal).
3. **Top-level `cache_control`** → automatic caching walks the breakpoint
   forward through message history as the conversation grows.

Four breakpoints are available; we use three. Note the automatic one consumes a
slot.

**Why two rather than one:** journal mode passes a different tools array
(`update_profile` only) and a different system prompt, so its prefix diverges
immediately. A tools-level breakpoint means ordinary chat still shares one
cache entry across the entire user base regardless of whose system prompt
follows.

## Minimum length — we clear it comfortably

Anthropic will silently skip caching below a per-model floor:

- **Sonnet 4.6 (`CHAT_MODEL`): 1,024 tokens** — tool array alone is 15× that. ✅
- **Haiku 4.5 (`FAST_MODEL`): 4,096 tokens** — background `complete()` calls
  (journal signal extraction, memory refresh) send a short system prompt and
  one message. **These will mostly fall below the floor and silently not
  cache.** Don't bother adding breakpoints to `complete()`; focus on
  `stream_chat`.

## The date-in-system-prompt question

`_build_system_prompt` includes `f"Today's date is {today}"`
(`service.py:617`). Anthropic's docs call out per-request volatile content
(timestamps) as the classic caching mistake.

**This one is fine.** It changes *daily*, not per-request, so within any 5-minute
TTL window it is constant. No restructuring needed. Worth a comment in the code
so nobody later "improves" it to include a time.

Do *not* add anything per-request (request id, current time, a random greeting)
to the system prompt — that would break caching entirely and the failure is
silent.

---

## The change: `api/src/life_dashboard/ai/provider.py`

Add a module-level helper:

```python
def _cacheable(tools: list[dict] | None, system: str) -> tuple[list[dict] | None, list[dict]]:
    """Attach cache breakpoints to the stable prefix (tools → system).

    Anthropic caches the prompt prefix cumulatively in the order
    tools → system → messages. Marking the final tool definition caches the
    whole tool array (~15.6k tokens, identical for every user); marking the
    system block caches tools+system.

    Both are copied rather than mutated — TOOL_DEFINITIONS is a module-level
    constant and must not gain request-specific keys.
    """
    cached_tools = None
    if tools:
        cached_tools = [dict(t) for t in tools]
        cached_tools[-1]["cache_control"] = {"type": "ephemeral"}

    system_blocks = [{
        "type": "text",
        "text": system,
        "cache_control": {"type": "ephemeral"},
    }]
    return cached_tools, system_blocks
```

Then in `AnthropicProvider.stream_chat`, replace the `kwargs` construction:

```python
        cached_tools, system_blocks = _cacheable(tools, system)

        kwargs: dict[str, Any] = dict(
            model=self.CHAT_MODEL,
            max_tokens=max_tokens,
            system=system_blocks,          # was: system=system
            messages=messages,
            cache_control={"type": "ephemeral"},   # automatic history caching
        )
        if cached_tools:
            kwargs["tools"] = cached_tools
```

That is the whole functional change. Nothing user-visible moves.

**Verify the SDK accepts the top-level `cache_control` kwarg** — `pyproject.toml`
pins `anthropic>=0.40.0`, and automatic caching is a newer addition. If the
installed version rejects it, drop that one line: the two explicit breakpoints
deliver the large majority of the saving on their own, since the tool array
dominates. Ship without it rather than blocking on an SDK upgrade.

## Recording the result: `AiUsage` migration

Without this you cannot prove caching works. `input_tokens` alone will *appear*
to drop dramatically — because it now only counts tokens after the last
breakpoint — which looks like a win even if nothing is cached.

> `total_input = cache_read_input_tokens + cache_creation_input_tokens + input_tokens`

Add two nullable integer columns to `ai_usage`:

```python
    cache_creation_input_tokens: Mapped[int] = mapped_column(default=0, server_default="0")
    cache_read_input_tokens: Mapped[int] = mapped_column(default=0, server_default="0")
```

Migration parents on **0053**. Use `op.batch_alter_table` so it runs on SQLite
as well as Postgres, and verify with `make migrate-verify` — a green SQLite run
proves nothing (root `CLAUDE.md`).

Then extend `record_usage(...)` with the two new keyword arguments, and at the
usage-capture site in `generate_stream` (`service.py`, ~line 1373):

```python
                    usage = getattr(final_msg, "usage", None)
                    if usage is not None:
                        total_input_tokens  += getattr(usage, "input_tokens", 0)
                        total_output_tokens += getattr(usage, "output_tokens", 0)
                        total_cache_write   += getattr(usage, "cache_creation_input_tokens", 0) or 0
                        total_cache_read    += getattr(usage, "cache_read_input_tokens", 0) or 0
```

`getattr` with a default keeps this safe against older SDK response shapes.

---

## Verification

**Automated** — a test asserting a second turn reads from cache:

1. Send a chat turn, capture `cache_creation_input_tokens` > 0 (first write).
2. Send a second turn in the same conversation, within the TTL.
3. Assert `cache_read_input_tokens` >= 15,000 on the second call.

If **both** cache fields are 0, caching did not happen — per the docs that
usually means the minimum length wasn't met, or the prefix changed between
requests.

**Manual, against a real key** — the honest check, since this only pays off
against the live API:

```sql
SELECT turn_kind,
       count(*)                          AS calls,
       sum(input_tokens)                 AS uncached_in,
       sum(cache_read_input_tokens)      AS cache_reads,
       sum(cache_creation_input_tokens)  AS cache_writes
FROM ai_usage
WHERE created_at > now() - interval '1 day'
GROUP BY turn_kind;
```

Expect `cache_reads` to dominate within a few turns of use.

## Expected result

| Interaction | Before | After |
|---|---|---|
| Simple question, 1 call | $0.072 | $0.025 |
| Typical, 1 tool round | $0.146 | $0.051 |
| Busy, 3 tool rounds | $0.324 | $0.134 |

Roughly **2.2–2.9× on chat**. Journaling improves less (~1.3×) because it has
almost no tool prefix to cache.

## Pitfalls

- **Cache writes cost 1.25× base input.** A one-shot question that never gets a
  follow-up is slightly *more* expensive than before. Net positive overall
  because the tool loop alone means most turns make 2+ calls, but expect the
  first days of data to look noisier than the table above.
- **Any change to `TOOL_DEFINITIONS` invalidates the entire cache** — tools,
  system and messages. Expected and harmless, but it means a deploy that edits
  a tool schema causes a brief cost spike as caches rewrite.
- **Don't mutate `TOOL_DEFINITIONS` in place.** The helper copies deliberately;
  attaching `cache_control` to the shared module constant would leak a
  request-scoped key into a global.
- **Default TTL is 5 minutes**, refreshed free on every hit. A 1-hour TTL exists
  at 2× write cost. Journaling sessions with long pauses between turns are the
  case that might justify it — measure before switching.
- **Cache entries are workspace-isolated** and only become available once the
  first response *begins*, so parallel first-requests won't share a write.

## Done when

- `cache_read_input_tokens` is non-zero and dominant in `ai_usage` after normal use.
- A typical tool-using chat turn costs ~$0.05 rather than ~$0.15.
- `make migrate-verify` passes against Postgres.
- No user-visible behaviour has changed.

## Not in this plan

Tool subsetting (plan 019, finding 4) is the larger structural win and is
deliberately separate — it changes what the model can see, so it carries
product risk that this change does not. Do this one first; it is pure upside.
