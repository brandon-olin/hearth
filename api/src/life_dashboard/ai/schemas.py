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

ChatContextType = Literal["note", "recipe", "document", "todo", "goal", "habit"]


class ChatContextRef(BaseModel):
    """Lightweight hint sent by the client identifying what resource the user
    is currently viewing in the app.

    The backend resolves this to a brief markdown block and prepends it to
    the chat system prompt so the AI knows what 'this' refers to without
    the user having to paste content. Visibility/ownership rules are
    enforced at resolution time — an unauthorised ref produces no block
    (silent) rather than an error, so a stale or bogus context never
    breaks the chat flow.
    """
    type: ChatContextType
    id: uuid.UUID


class ChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=32_000)
    # Omit to start a new conversation; provide to continue an existing one.
    conversation_id: uuid.UUID | None = None
    # Optional "what the user is currently looking at" hint — see ChatContextRef.
    context: ChatContextRef | None = None


# ── Settings ──────────────────────────────────────────────────────────────────

class AiSettingsResponse(BaseModel):
    """AI settings for the current user.

    The raw API key is never included in responses; has_custom_key indicates
    whether a BYOK key has been saved without exposing it.
    """
    provider: AiProviderLiteral
    retention_days: int | None
    has_custom_key: bool
    # Phase 2 of AI coach redesign — opt-out of per-entry journal signal
    # extraction. True by default for new users; True (server default) for
    # existing users after the 0033 migration.
    ai_journal_extraction_enabled: bool = True


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

    ai_journal_extraction_enabled:
      - Not sent → current value unchanged
      - Sent → new value applied (toggles per-entry signal extraction)
    """
    provider: AiProviderLiteral | None = None
    retention_days: int | None = None
    api_key: str | None = None
    clear_api_key: bool = False
    ai_journal_extraction_enabled: bool | None = None


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


# ── Journal session (journal-001) ─────────────────────────────────────────────

class JournalStartRequest(BaseModel):
    """Start (or resume) a guided journal session for today's entry."""
    note_id: uuid.UUID


class JournalStartResponse(BaseModel):
    """The active conversation for this user+note pair.

    `is_new` is true when this call created the conversation; false when
    we resumed an existing one (the user opened Talk-it-out earlier today).
    Frontend uses it to decide whether to wait for an AI-initiated opener
    or just render the existing transcript.

    `opening_message` (journal-001 Phase B) is the personalized first-turn
    message the AI generates when is_new=true. Already saved as the first
    assistant message in the conversation by /ai/journal/start. NULL for
    resumed sessions — their history (including the original opener) is
    fetched separately when the frontend wants to render it.
    """
    conversation_id: uuid.UUID
    is_new: bool
    opening_message: str | None = None


class JournalFinishResponse(BaseModel):
    """Synthesized first-person summary, NOT yet saved.

    The frontend renders this in an editable view; user accepts/edits
    then calls /ai/journal/save with the final content_md.
    """
    summary_md: str


class JournalSaveRequest(BaseModel):
    """Persist a journal session as appended content on the target note."""
    conversation_id: uuid.UUID
    content_md: str = Field(min_length=1, max_length=20_000)
    include_transcript: bool = False


class JournalSaveResponse(BaseModel):
    note_id: uuid.UUID


# ── Profile (Phase 1 of AI coach redesign) ────────────────────────────────────

ProfileUpdateSource = Literal[
    "bootstrap", "incremental", "manual", "scheduled", "direct_edit"
]
ProfileUpdateStatus = Literal["pending", "accepted", "rejected", "superseded"]


class ProfileResponse(BaseModel):
    """Current accepted user profile.

    content_md is the same data stored on member_ai_memory.memory_text — a
    markdown document, sectioned by H2 headers, that both the coach and the
    chatbot read on every interaction. Empty string until the bootstrap pass
    has run and the user has accepted the first proposed update.
    """
    content_md: str
    last_updated_at: datetime
    last_bootstrapped_at: datetime | None


class ProfilePatchRequest(BaseModel):
    """User-driven direct edit of the profile.

    The 8KB cap matches the hard cap documented in docs/ai-coach-redesign.md.
    """
    content_md: str = Field(min_length=0, max_length=8000)


class ProfileUpdateResponse(BaseModel):
    """One proposed change to the profile, surfaced to the user for review."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    proposed_content_md: str
    diff_summary: str | None
    source: ProfileUpdateSource
    status: ProfileUpdateStatus
    created_at: datetime
    resolved_at: datetime | None


class ProfileUpdateListResponse(BaseModel):
    items: list[ProfileUpdateResponse]


class BootstrapResponse(BaseModel):
    """Returned by POST /ai/profile/bootstrap.

    `update` is the newly-created pending proposal the user must review.
    `bootstrap_skipped` is true when the pass produced no usable signal
    (e.g. a brand-new user with no notes/journal/documents) — in that case
    no update is created and the user can populate the profile manually.
    """
    update: ProfileUpdateResponse | None
    bootstrap_skipped: bool = False
    reason: str | None = None


# ── Phase 4: profile versioning ───────────────────────────────────────────────

class ProfileVersionResponse(BaseModel):
    """One historical snapshot of a user's profile content."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    content_md: str
    source: ProfileUpdateSource
    created_at: datetime


class ProfileVersionListResponse(BaseModel):
    items: list[ProfileVersionResponse]
