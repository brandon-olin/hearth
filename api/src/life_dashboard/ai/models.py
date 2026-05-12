import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Computed, DateTime, ForeignKey, Integer, Text
from sqlalchemy import Enum as SaEnum
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
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


# Reference PG enum types by name; create_type=False prevents SQLAlchemy from
# emitting CREATE TYPE — both were created by migration 0003.
_ai_message_role_pg = SaEnum(AiMessageRole, name="ai_message_role", create_type=False)
_ai_provider_pg = SaEnum(AiProvider, name="ai_provider", create_type=False)


class AiConversation(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id", ondelete="CASCADE")
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
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_conversations.id", ondelete="CASCADE")
    )
    role: Mapped[AiMessageRole] = mapped_column(_ai_message_role_pg)
    content: Mapped[str] = mapped_column(Text)
    # Server-generated column maintained by Postgres on every INSERT/UPDATE.
    # Deferred so it is not loaded on routine SELECT queries; only used in
    # WHERE clauses for full-text search via the GIN index.
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', content)", persisted=True),
        deferred=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MemberAiMemory(Base):
    __tablename__ = "member_ai_memory"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
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
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[AiProvider] = mapped_column(
        _ai_provider_pg, default=AiProvider.anthropic
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
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
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
