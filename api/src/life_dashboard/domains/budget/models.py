import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, JSON, Numeric, String, Text, Uuid
from sqlalchemy import Enum as SaEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from life_dashboard.core.database import Base


# ── Enums ─────────────────────────────────────────────────────────────────────

AccountType = SaEnum(
    "checking", "savings", "credit_card", "loan", "investment", "other",
    name="budget_account_type",
    native_enum=False,
)

AccountScope = SaEnum(
    "personal", "shared",
    name="budget_account_scope",
    native_enum=False,
)

TransactionScope = SaEnum(
    "personal", "household",
    name="budget_transaction_scope",
    native_enum=False,
)

CategoryDefaultScope = SaEnum(
    "personal", "household",
    name="budget_category_default_scope",
    native_enum=False,
)

ImportSource = SaEnum(
    "csv", "ofx", "manual", "teller", "plaid",
    name="budget_import_source",
    native_enum=False,
)


# ── Models ────────────────────────────────────────────────────────────────────

class BudgetAccount(Base):
    """
    A financial account belonging to one household member.

    scope controls the default transaction scope for everything imported
    from this account:
      personal  — transactions visible only to the owner (default)
      shared    — transactions visible to all household members and eligible
                  for household expense splitting
    """
    __tablename__ = "budget_accounts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_type: Mapped[str] = mapped_column(AccountType, nullable=False, default="checking")
    # personal = only owner sees transactions; shared = visible to household
    scope: Mapped[str] = mapped_column(AccountScope, nullable=False, default="personal")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BudgetCategory(Base):
    """
    A spending category defined at the household level.

    default_scope controls how transactions are scoped when auto-assigned
    to this category:
      personal   — expense is private to the importing member
      household  — expense is shared and subject to split_config

    split_config is a JSONB map of { "<user_id>": <ratio> } for all
    household members. Ratios must sum to 1.0. NULL means equal split
    across all active members (resolved at query time).

    Example: { "uuid-jon": 0.6667, "uuid-amy": 0.3333 }
    """
    __tablename__ = "budget_categories"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Whether transactions in this category are personal or household by default
    default_scope: Mapped[str] = mapped_column(
        CategoryDefaultScope, nullable=False, default="personal"
    )
    # Per-member split ratios for household-scoped transactions.
    # NULL = equal split across all active household members.
    # Shape: { "<user_id_str>": float }  — ratios must sum to 1.0.
    split_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    color: Mapped[str | None] = mapped_column(String(20), nullable=True)   # CSS color or token
    icon: Mapped[str | None] = mapped_column(String(10), nullable=True)    # single emoji
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)
    # Keywords for auto-categorization: ["groceries", "whole foods", "trader joe"]
    keywords: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BudgetTransaction(Base):
    """
    A single financial transaction, normalised from any import source.

    amount convention:
      negative  — money out (expense, payment)
      positive  — money in  (income, refund, transfer received)

    scope mirrors the account scope at import time but can be overridden
    per-transaction:
      personal   — visible only to owner_user_id
      household  — visible to all household members; subject to split_config

    split_override is a per-transaction override of the category split_config.
    NULL = use the category's split_config (or equal split if that is also NULL).
    Shape: { "<user_id_str>": float }

    dedup_hash is a hex-encoded SHA-256 of (account_id, date, amount, description).
    Unique per account, used to prevent duplicate imports.

    external_id is the bank's own transaction identifier (from OFX/Teller/Plaid),
    used as a secondary dedup key when available.
    """
    __tablename__ = "budget_transactions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("budget_accounts.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalised from account for efficient personal-view queries without a join
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("budget_categories.id", ondelete="SET NULL"), nullable=True
    )

    date: Mapped[date] = mapped_column(Date, nullable=False)
    # Negative = expense, positive = income/refund
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

    # Raw description as it came from the bank
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # AI-cleaned or user-edited merchant name
    merchant_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # personal = only owner; household = shared + split applies
    scope: Mapped[str] = mapped_column(TransactionScope, nullable=False, default="personal")
    # Per-transaction split override. NULL = use category split_config.
    split_override: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    import_source: Mapped[str | None] = mapped_column(ImportSource, nullable=True)
    # Bank-provided transaction ID (OFX FITID, Teller/Plaid transaction_id)
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # SHA-256(account_id + date + amount + description) for CSV/OFX dedup
    dedup_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
