import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy import Enum as SaEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.schema import Index

from life_dashboard.core.database import Base


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
    __tablename__ = "member_ai_memory"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Curated natural-language user profile (~500-800 tokens).
    # Blank until the lazy refresh threshold is first reached.
    memory_text: Mapped[str] = mapped_column(Text, default="")
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Used to decide lazily whether a memory refresh is due.
    conversation_count_at_last_update: Mapped[int] = mapped_column(Integer, default=0)


class AiSettings(Base):
    __tablename__ = "ai_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[AiProvider] = mapped_column(
        _ai_provider_enum, default=AiProvider.anthropic
    )
    # NULL → use the system-level ANTHROPIC_API_KEY env var.
    # Non-null → BYOK key stored by the service layer.
    # TODO: encrypt at rest (e.g. Fernet with a key derived from JWT_SECRET_KEY).
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    # NULL → keep conversations forever.
    # Allowed integers: 30, 60, 90, 180, 365 (enforced by DB CHECK constraint).
    retention_days: Mapped[int | None] = mapped_column(Integer, default=90)


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
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tone: Mapped[str] = mapped_column(String(50), nullable=False, default="supportive")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_ai_coach_digests_user_date_kind", "user_id", "date", "kind", unique=True),
        Index("ix_ai_coach_digests_user_date", "user_id", "date"),
    )
