import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, Uuid
from sqlalchemy import Enum as SaEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.schema import Index

from life_dashboard.core.database import Base
from life_dashboard.core.encryption import EncryptedText, EncryptedJSON


class AiMessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"
    tool = "tool"


class AiProvider(str, enum.Enum):
    anthropic = "anthropic"
    openai = "openai"
    ollama = "ollama"


# native_enum=False stores as VARCHAR — works on both Postgres and SQLite.
# (Existing Postgres DBs keep their native enum columns; runtime behaviour is identical.)
_ai_message_role_enum = SaEnum(AiMessageRole, native_enum=False)
_ai_provider_enum = SaEnum(AiProvider, native_enum=False)


class AiConversation(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE")
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE")
    )
    # Populated from the first user message; NULL until that message is saved.
    title: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # journal-001: "chat" (default) or "journal". Journal conversations
    # use a different system prompt and a restricted tool set when streamed
    # through /ai/chat. See ai/service.py build_chat_context.
    kind: Mapped[str] = mapped_column(String(20), default="chat")
    # For kind='journal' — the journal entry this session is filling in.
    # NULL for kind='chat'. One journal conversation per (user, note) so
    # re-opening Talk-it-out for the same day resumes the same session.
    note_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("notes.id", ondelete="SET NULL"), nullable=True
    )
    # journal-001 Phase C: which "check-in mode" the user chose when
    # starting this journal session, or NULL if they took the blank-slate
    # path. Drives (a) the canned opening message and (b) a mode-specific
    # instruction layered onto the journal system prompt — e.g. rant mode
    # tells the model to stay with the user, not reality-test. Valid
    # values: "blank", "mood", "body", "rant", "day_review". Stored as
    # the literal string the API received so it's easy to inspect in the
    # database; validation lives at the schema layer.
    mode: Mapped[str | None] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        Index("ix_ai_conversations_user_kind_note", "user_id", "kind", "note_id"),
    )


class AiMessage(Base):
    __tablename__ = "ai_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("ai_conversations.id", ondelete="CASCADE")
    )
    role: Mapped[AiMessageRole] = mapped_column(_ai_message_role_enum)
    content: Mapped[str] = mapped_column(Text)
    # NOTE: search_vector (TSVECTOR + GIN index) exists in Postgres DBs but is
    # not mapped here — it is Postgres-specific and incompatible with SQLite.
    # The ai/service.py search function uses a dialect-aware fallback (LIKE on
    # SQLite, tsvector @@ plainto_tsquery on Postgres via raw text()).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MemberAiMemory(Base):
    """Per-user curated profile read by both the chatbot and the coach.

    `memory_text` is the user's profile — a markdown document, sectioned by
    H2 headers, ~500-800 tokens. Originally written by the legacy lazy chat
    memory refresh; it is now also written directly by the bootstrap pass and
    the notes-driven incremental proposer, and read by coach_service when
    assembling digest prompts.

    Reusing this column rather than adding a user_profiles table is
    deliberate: the chatbot already read memory_text, so one blob keeps chat
    and coach speaking about the same person.

    Note that docs/ai-coach-redesign.md is stale on this point — it describes
    a user_profiles table that was never built.
    """

    __tablename__ = "member_ai_memory"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # The profile itself. Empty string until either the legacy refresh
    # fires or the bootstrap pass produces (and the user accepts) a draft.
    memory_text: Mapped[str] = mapped_column(EncryptedText, default="")
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Used by the legacy chat memory-refresh pass to decide whether enough
    # new conversation activity has accumulated to warrant a silent refresh.
    conversation_count_at_last_update: Mapped[int] = mapped_column(Integer, default=0)
    # NULL = the richer bootstrap pass (reads notes/documents + behavioural
    # data and writes memory_text directly) has never run for this user.
    # Distinct from last_updated_at, which advances on any change. Also the
    # gate the incremental proposer checks — it stays silent until bootstrap
    # has run at least once, so it never drafts a profile from scratch.
    last_bootstrapped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Total notes by this user (across all collections) the last time the
    # notes-driven profile proposer ran. profile_service.maybe_propose_from_notes
    # compares this against the current total to decide whether enough new
    # activity has accumulated to justify another proposer call. Advances on
    # every proposer run regardless of outcome — see Phase 1.5 in
    # docs/ai-coach-redesign.md.
    notes_at_last_proposal: Mapped[int] = mapped_column(Integer, default=0)


class UserProfileUpdate(Base):
    """Audit log of changes applied to a user's profile.

    Written by the bootstrap pass, the notes-driven incremental proposer, the
    update_profile chat tool, and the weekly scheduled refresh. Every row is
    inserted with status='accepted' — the profile is a silent background
    service, so the write has already happened by the time the row exists.

    This started life as a review queue (the user accepted or rejected each
    proposal). That surface was removed in coach-005: it put a chore in front
    of a feature whose entire value is that it maintains itself. The
    pending/rejected/superseded statuses and the accept/reject endpoints
    remain for debugging and for the historical rows, but nothing produces a
    pending row any more.

    `source` values: "bootstrap" | "incremental" | "manual" | "scheduled" |
                     "direct_edit"
    `status`  values: "accepted" (current) | "pending" | "rejected" |
                      "superseded" (legacy)
    """

    __tablename__ = "user_profile_updates"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE")
    )
    proposed_content_md: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    # One-line natural-language summary of what's changing.
    # Optional because manual proposals (future) may not have a summary.
    diff_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="incremental")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_user_profile_updates_user_status", "user_id", "status"),
    )


class AiSettings(Base):
    __tablename__ = "ai_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[AiProvider] = mapped_column(
        _ai_provider_enum, default=AiProvider.anthropic
    )
    # NULL → use the system-level ANTHROPIC_API_KEY env var.
    # Non-null → BYOK key stored encrypted by EncryptedText (Fernet, FIELD_ENCRYPTION_KEY).
    api_key_encrypted: Mapped[str | None] = mapped_column(EncryptedText)
    # NULL → keep conversations forever.
    # Allowed integers: 30, 60, 90, 180, 365 (enforced by DB CHECK constraint).
    retention_days: Mapped[int | None] = mapped_column(Integer, default=90)
    # Phase 2 of AI coach redesign: opt-out flag for per-entry journal
    # signal extraction. When False, save-time extraction is skipped and
    # the coach falls back to behavioural-only context. See
    # docs/ai-coach-redesign.md → Phase 2.
    ai_journal_extraction_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )


class AiUsage(Base):
    """Per-turn token consumption record.

    One row is written after each completed API call — both interactive chat
    turns and background calls (e.g. memory refresh).  turn_kind distinguishes
    these so they can be filtered separately in usage reports.

    conversation_id is nullable because background tasks (memory refresh) are
    not tied to a specific conversation.
    """
    __tablename__ = "ai_usage"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE")
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(),
        ForeignKey("ai_conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # Prompt-caching counters. input_tokens is only the *uncached* remainder,
    # so the true prompt size is
    #   input_tokens + cache_creation_input_tokens + cache_read_input_tokens.
    # Without these two columns a drop in input_tokens looks like a win even
    # when nothing was actually cached.
    cache_creation_input_tokens: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    cache_read_input_tokens: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    # Actual model string returned by the provider (e.g. "claude-sonnet-4-6").
    model: Mapped[str] = mapped_column(Text)
    # "chat" for interactive turns, "memory_refresh" for background calls.
    turn_kind: Mapped[str] = mapped_column(Text, default="chat")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # Index used by monthly rollup queries and the /ai/usage endpoint.
        Index("ix_ai_usage_user_created", "user_id", "created_at"),
    )


class CoachDigestKind(str, enum.Enum):
    morning = "morning"
    evening = "evening"
    weekly = "weekly"


class AiCoachDigest(Base):
    """One AI coach digest per user per day per session (morning or evening).

    Content is generated by the background scheduler or on-demand via the
    /ai/coach/digest/generate endpoint. Stored so users can re-read their
    digest without triggering another AI call.
    """
    __tablename__ = "ai_coach_digests"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE")
    )
    date: Mapped[date] = mapped_column(Date(), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # "morning" | "evening"
    content: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    tone: Mapped[str] = mapped_column(String(50), nullable=False, default="supportive")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_ai_coach_digests_user_date_kind", "user_id", "date", "kind", unique=True),
        Index("ix_ai_coach_digests_user_date", "user_id", "date"),
    )


class UserProfileVersion(Base):
    """Append-only snapshot of a user's profile content.

    A new row is written every time member_ai_memory.memory_text is about
    to be overwritten — bootstrap, incremental proposer, the
    update_profile chat tool, the scheduled weekly refresh, and direct
    admin PATCH all flow through the same `_apply_profile_update` helper
    in profile_service that snapshots the OLD content before saving.

    The application layer enforces a soft retention cap (~50 rows per
    user) by trimming the oldest rows whenever a new version is written.
    Caller commits.

    See docs/ai-coach-redesign.md → Phase 4 for the full design.
    """

    __tablename__ = "user_profile_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE")
    )
    content_md: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    # Matches profile_service.PROFILE_UPDATE_SOURCES.
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_user_profile_versions_user_created", "user_id", "created_at"),
    )


class JournalSignal(Base):
    """Per-entry structured features extracted from a journal note.

    One row per note (uniqueness enforced on note_id). Created or replaced by
    journal_signal_service when a note is saved into a collection with
    kind='journal' and the user's ai_journal_extraction_enabled flag is true.

    Trend math (sentiment_7d_vs_30d, harsh_self_talk_streak, etc.) runs on
    this table — never on raw note content — so the coach can reason about
    *patterns* without re-reading every entry each digest.

    Fields:
      entry_date         — the date the entry is *about*; from the collection's
                           auto_create_rule when available, else created_at.
      sentiment          — -1.00 (very negative) to +1.00 (very positive).
      self_talk_valence  — "positive" | "neutral" | "harsh" | "mixed".
      themes             — short string array; e.g. ["consistency", "work stress"].
      notable_phrases    — short string array; used sparingly for callbacks.
      energy_level       — "low" | "medium" | "high" | NULL when not inferable.
      extraction_version — bumped when the extraction prompt changes; lets us
                           re-run extraction across older rows.

    See docs/ai-coach-redesign.md → Phase 2 for the full design.
    """

    __tablename__ = "journal_signals"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), primary_key=True, default=uuid.uuid4
    )
    note_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("notes.id", ondelete="CASCADE"), unique=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE")
    )
    entry_date: Mapped[date] = mapped_column(Date(), nullable=False)
    sentiment: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    self_talk_valence: Mapped[str] = mapped_column(String(20), default="neutral")
    themes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    notable_phrases: Mapped[list[str] | None] = mapped_column(EncryptedJSON, nullable=True)
    energy_level: Mapped[str | None] = mapped_column(String(10), nullable=True)
    extraction_version: Mapped[int] = mapped_column(Integer, default=1)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_journal_signals_user_entry_date", "user_id", "entry_date"),
    )
