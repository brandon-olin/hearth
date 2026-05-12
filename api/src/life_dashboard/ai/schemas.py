import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field


AiProviderLiteral = Literal["anthropic", "openai", "ollama"]


# ── Conversations ─────────────────────────────────────────────────────────────

class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    created_at: datetime
    last_message_at: datetime


class ConversationListResponse(BaseModel):
    items: list[ConversationResponse]
    total: int


# ── Messages ──────────────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    content: str
    created_at: datetime


class ConversationDetailResponse(BaseModel):
    """A conversation with its full message history."""
    id: uuid.UUID
    title: str | None
    created_at: datetime
    last_message_at: datetime
    messages: list[MessageResponse]


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=32_000)
    # Omit to start a new conversation; provide to continue an existing one.
    conversation_id: uuid.UUID | None = None


# ── Settings ──────────────────────────────────────────────────────────────────

class AiSettingsResponse(BaseModel):
    """AI settings for the current user.

    The raw API key is never included in responses; has_custom_key indicates
    whether a BYOK key has been saved without exposing it.
    """
    provider: AiProviderLiteral
    retention_days: int | None
    has_custom_key: bool


class AiSettingsUpdate(BaseModel):
    """All fields are optional; only sent fields are updated (model_fields_set).

    retention_days:
      - Not sent → current value unchanged
      - Sent as null → set to null (keep conversations forever)
      - Sent as integer → set to that retention window

    api_key:
      - None → don't change the stored key
      - Non-empty string → save as new BYOK key
      - Use clear_api_key=true to remove a BYOK key and fall back to system key
    """
    provider: AiProviderLiteral | None = None
    retention_days: int | None = None
    api_key: str | None = None
    clear_api_key: bool = False


# ── Search ────────────────────────────────────────────────────────────────────

class MessageSearchItem(BaseModel):
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    conversation_title: str | None
    role: str
    snippet: str
    created_at: datetime


class MessageSearchResponse(BaseModel):
    items: list[MessageSearchItem]
    total: int


# ── Usage ─────────────────────────────────────────────────────────────────────

class UsageModelBreakdown(BaseModel):
    """Token usage for a single model within a reporting period."""
    model: str
    input_tokens: int
    output_tokens: int

    @computed_field  # type: ignore[misc]
    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class UsageSummaryResponse(BaseModel):
    """Token usage summary for the current user.

    this_month_* covers the current calendar month (UTC).
    lifetime_* covers all recorded history.
    by_model gives the this-month breakdown per model string so the UI can
    show which model consumed what.
    """
    this_month_input_tokens: int
    this_month_output_tokens: int
    this_month_total_tokens: int
    lifetime_input_tokens: int
    lifetime_output_tokens: int
    lifetime_total_tokens: int
    by_model: list[UsageModelBreakdown]
