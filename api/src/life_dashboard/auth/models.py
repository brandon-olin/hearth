import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy import Enum as SaEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from typing import Optional

from life_dashboard.core.database import Base


class EmailVerificationCode(Base):
    """Short-lived OTP issued after registration; consumed once to verify an email address."""
    __tablename__ = "email_verification_codes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # SHA-256 of the raw 6-digit code — same pattern as refresh tokens
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MembershipRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"
    viewer = "viewer"
    agent = "agent"


# native_enum=False stores as VARCHAR — works on both Postgres and SQLite.
# Migration 0047 converted the native `membership_role` enum away and dropped
# the type, so both engines now agree (ADR-015). The CHECK constraint is what
# keeps an invalid role out of a permissions column.
_membership_role_pg = SaEnum(
    MembershipRole,
    native_enum=False,
    name="membership_role",
    create_constraint=True,
)


class Household(Base):
    __tablename__ = "households"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    # Per-domain access-control configuration. NULL = use defaults from
    # life_dashboard.core.permissions.DEFAULT_DOMAIN_PERMISSIONS.
    # Shape: { "<domain>": { "read": "<role>", "create": "<role>", "manage_others": "<role>" } }
    permissions_config: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # updated_at is maintained by the households_updated_at DB trigger.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # ── Subscription (cloud tier only) ────────────────────────────────────────
    # subscription_status: free | trialing | active | past_due | canceled
    # Updated by Stripe webhook handler when payment events arrive.
    # is_exempt: True bypasses subscription checks entirely (dev/test accounts).
    subscription_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="free", default="free"
    )
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_exempt: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )

    memberships: Mapped[list["HouseholdMembership"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_agent: Mapped[bool] = mapped_column(Boolean, default=False)
    # Verified via 6-digit OTP sent to the email address at registration.
    # Existing users (pre-feature) are backfilled to True in migration 0038.
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Set True when an admin creates an account on behalf of a new household member.
    # The frontend blocks app access and forces the user to set their own password.
    # Cleared to False once the user successfully sets a new password.
    force_password_change: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    preferences: Mapped[dict | None] = mapped_column(JSON)

    # ── Locale / display preferences ──────────────────────────────────────────
    # Auto-detected from the browser on first login; overridable in Account settings.
    # IANA timezone string, e.g. "America/Chicago". None = not yet detected.
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Date display format. One of: "MM/DD/YY", "DD/MM/YYYY", "YYYY-MM-DD".
    # None = not yet set (falls back to ISO 8601 in the API).
    date_format: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # First day of the week. "sunday" (US default) or "monday" (ISO/EU default).
    week_start: Mapped[str | None] = mapped_column(String(10), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # updated_at is maintained by the users_updated_at DB trigger.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    memberships: Mapped[list["HouseholdMembership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    personal_access_tokens: Mapped[list["PersonalAccessToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class HouseholdMembership(Base):
    __tablename__ = "household_memberships"
    __table_args__ = (
        UniqueConstraint("household_id", "user_id", name="household_memberships_household_user_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE")
    )
    role: Mapped[MembershipRole] = mapped_column(_membership_role_pg, default=MembershipRole.member)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # ai-access-001: admin-controlled gate for AI features (coach, chat,
    # journal, profile personalisation). Defaults True so existing members
    # are unaffected. Set to False to lock a member out of AI surfaces
    # without deleting them or revoking other access. Existing AI data
    # is preserved — flipping back to True restores the experience.
    ai_features_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    household: Mapped["Household"] = relationship(back_populates="memberships")
    user: Mapped["User"] = relationship(back_populates="memberships")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE")
    )
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    user_agent: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class PersonalAccessToken(Base):
    """Long-lived, scoped, revocable API token for agents (security-006).

    Session JWTs are too short-lived for MCP clients, Home Assistant, and
    iCal feeds. A PAT is issued per member, shown exactly once at creation,
    and stored only as a SHA-256 hash — the plaintext is unrecoverable, so a
    DB leak yields no usable credentials.

    SHA-256 rather than argon2 (which guards `users.password_hash`) because
    the secret is 256 bits of CSPRNG output, not a human-chosen password:
    there is no dictionary to attack, so a slow KDF buys nothing and would
    prevent the indexed hash lookup this table does on every agent request.
    Same reasoning as RefreshToken above.
    """
    __tablename__ = "personal_access_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # User-supplied label, e.g. "Kitchen speaker".
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # SHA-256 of the full raw token. There is deliberately no plaintext column.
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    # Non-secret display fragment, e.g. "hearth_pat_a1b2c3d4" — lets a user tell
    # two tokens apart in the management UI without exposing the secret.
    prefix: Mapped[str] = mapped_column(String(40), nullable=False)
    # { "<scope domain>": "read" | "write" } — see auth/pat_scopes.py.
    scopes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Throttled to one write per _LAST_USED_THROTTLE_SECONDS in pat_service.
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="personal_access_tokens")


class PasswordResetToken(Base):
    """Short-lived token for the forgot-password flow.

    Only used on the cloud tier where email is available. On local/self_hosted
    tiers the household admin can reset passwords directly via the invite flow.
    The table exists on all tiers so the schema stays portable.
    """
    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # SHA-256 of the raw URL-safe token — same pattern as refresh tokens
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
