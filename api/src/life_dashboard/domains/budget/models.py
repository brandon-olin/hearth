import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, JSON, Numeric, String, Text, Uuid
from sqlalchemy import Enum as SaEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from life_dashboard.core.database import Base
from life_dashboard.core.encryption import EncryptedText


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

# budget-010: renamed from personal/household → private/shared
TransactionScope = SaEnum(
    "private", "shared",
    name="budget_transaction_scope",
    native_enum=False,
)

# budget-010: renamed from personal/household → private/shared
CategoryDefaultScope = SaEnum(
    "private", "shared",
    name="budget_category_default_scope",
    native_enum=False,
)

ImportSource = SaEnum(
    "csv", "ofx", "manual", "teller", "plaid", "recurring",
    name="budget_import_source",
    native_enum=False,
)

BudgetingStyle = SaEnum(
    "zero_based", "profit_tracking",
    name="budget_budgeting_style",
    native_enum=False,
)

ProfileMemberRole = SaEnum(
    "owner", "member", "viewer",
    name="budget_profile_member_role",
    native_enum=False,
)


# ── Models ────────────────────────────────────────────────────────────────────

class BudgetProfile(Base):
    """
    A named financial context for a household.

    Two default profiles are seeded on household creation:
      Personal   — zero_based budgeting, personal accounts/categories only
      Household  — zero_based budgeting, shared household expenses

    Additional profiles can be created (e.g. a Business profile with
    budgeting_style='profit_tracking') as a paid-tier feature.

    budgeting_style:
      zero_based       — YNAB-style envelope budgeting; 'Ready to assign' banner
      profit_tracking  — P&L view; revenue vs expenses; net profit headline; no envelopes
    """
    __tablename__ = "budget_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    budgeting_style: Mapped[str] = mapped_column(BudgetingStyle, nullable=False, default="zero_based")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BudgetProfileMember(Base):
    """
    Explicit per-profile membership with role-based access control (budget-014).

    Profiles default to including all household members as 'member' on creation.
    Owners can restrict a profile to a subset of household members.

    Role semantics:
      owner  — can edit profile settings, manage members, delete profile
      member — can add/edit transactions, categories, targets
      viewer — read-only access to analytics and transactions
    """
    __tablename__ = "budget_profile_members"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("budget_profiles.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(ProfileMemberRole, nullable=False, default="member")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BudgetAccount(Base):
    """
    A financial account belonging to one household member.

    scope controls the default transaction scope for everything imported
    from this account:
      personal  — transactions visible only to the owner (default)
      shared    — transactions visible to all household members and eligible
                  for household expense splitting

    profile_id assigns this account to a budget profile (budget-009).
    All transactions imported from this account analytically belong to
    this profile unless overridden on the transaction (budget-011).
    """
    __tablename__ = "budget_accounts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # budget-009: profile assignment
    profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("budget_profiles.id", ondelete="SET NULL"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_type: Mapped[str] = mapped_column(AccountType, nullable=False, default="checking")
    # personal = only owner sees transactions; shared = visible to household
    scope: Mapped[str] = mapped_column(AccountScope, nullable=False, default="personal")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

    # budget-017: manually-maintained balance (user enters from bank statement)
    current_balance: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    balance_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Teller bank sync — all nullable; NULL means the account is not linked to Teller.
    # teller_enrollment_id: Teller enrollment ID from the Teller Connect callback.
    # teller_access_token:  per-enrollment access token; used as Basic-auth username.
    # teller_account_id:    Teller's internal account ID (distinct from our UUID PK).
    # teller_institution_name: human-readable bank name ("Chase", "Wells Fargo", …).
    # teller_last_synced_at: timestamp of the last successful polling sync.
    # teller_cursor:        most recent Teller transaction ID seen; passed as `from_id`
    #                       on the next sync to fetch only new transactions.
    teller_enrollment_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    teller_access_token: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    teller_account_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    teller_institution_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    teller_last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    teller_cursor: Mapped[str | None] = mapped_column(String(200), nullable=True)

    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BudgetCategoryGroup(Base):
    """
    A named group that organises categories into collapsible sections.

    Default groups (seeded via the API seed endpoint or the service helper):
      1 — Fixed Monthly
      2 — Everyday Spending
      3 — Irregular / True Expenses
      4 — Savings & Goals
      5 — Just for Fun
      6 — Income

    Categories whose group_id is NULL are rendered under an implicit "Other" bucket.

    profile_id: groups belong to a profile; the Household profile gets the default
    YNAB-inspired groups; a Business profile gets revenue/expense groups.
    """
    __tablename__ = "budget_category_groups"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    # budget-009: profile assignment
    profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("budget_profiles.id", ondelete="SET NULL"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)

    # When True, positive transactions in categories belonging to this group
    # are counted as income in analytics and summary queries.  This replaces
    # the previous hardcoded name == "income" check so users can name their
    # income group anything they like (Salary, Inflows, etc.).
    is_income: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BudgetCategory(Base):
    """
    A spending category defined at the household level.

    default_scope controls how transactions are scoped when auto-assigned
    to this category (budget-010 names):
      private  — expense is private to the importing member
      shared   — expense is shared and subject to split_config

    split_config is a JSONB map of { "<user_id>": <ratio> } for all
    household members. Ratios must sum to 1.0. NULL means equal split
    across all active members (resolved at query time).

    profile_id: the budget profile this category belongs to (budget-009).

    is_recurring_revenue: for profit_tracking profiles only — income in
    this category counts toward MRR / ARR reporting (budget-013).
    """
    __tablename__ = "budget_categories"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    # budget-009: profile assignment
    profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("budget_profiles.id", ondelete="SET NULL"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # budget-010: renamed from personal/household → private/shared
    default_scope: Mapped[str] = mapped_column(
        CategoryDefaultScope, nullable=False, default="private"
    )
    # Per-member split ratios for shared-scoped transactions.
    # NULL = equal split across all active household members.
    # Shape: { "<user_id_str>": float }  — ratios must sum to 1.0.
    split_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Group membership — NULL means the category falls into the implicit "Other" bucket
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("budget_category_groups.id", ondelete="SET NULL"), nullable=True
    )

    # Standing monthly budget target — applies to every month unless overridden
    # in budget_targets. NULL means no target is set for this category.
    default_monthly_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    # When True, any unspent (or overspent) balance at month-end carries forward
    # to the following month, adjusting that month's effective target.
    rollover_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    # Threshold (0–100) at which to fire a budget alert notification.
    # NULL = notifications disabled for this category.
    # When set, a notification fires when spending crosses this % of the monthly
    # target, and again when it crosses 100%.  Defaults to 80 for new categories.
    notify_threshold_pct: Mapped[int | None] = mapped_column(nullable=True, default=80)

    # budget-013: for profit_tracking profiles — income here counts toward MRR/ARR
    is_recurring_revenue: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

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

    scope (budget-010 names):
      private  — visible only to owner_user_id
      shared   — visible to all household members; subject to split_config

    profile_id (budget-011): optional override. When set, this transaction
    analytically belongs to the target profile instead of the account's profile.
    The account balance is unaffected — re-attribution is analytics-only.
    Resolution: COALESCE(txn.profile_id, account.profile_id)

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
    # budget-011: optional profile override for cross-profile re-attribution
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("budget_profiles.id", ondelete="SET NULL"), nullable=True
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

    # budget-010: private = only owner; shared = all members + split applies
    scope: Mapped[str] = mapped_column(TransactionScope, nullable=False, default="private")
    # Per-transaction split override. NULL = use category split_config.
    split_override: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # True when this transaction is one leg of an internal transfer between accounts.
    # Both legs should be marked is_transfer=True. Transfers are excluded from
    # income/expense aggregates so they don't inflate totals in multi-account views.
    is_transfer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    import_source: Mapped[str | None] = mapped_column(ImportSource, nullable=True)
    # Bank-provided transaction ID (OFX FITID, Teller/Plaid transaction_id)
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # SHA-256(account_id + date + amount + description) for CSV/OFX dedup
    dedup_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # budget-004: recurring rule (NULL = not recurring / this is a generated instance)
    # Shape: { "frequency": "monthly"|"weekly", "interval": int, "end_date": str|null }
    recurring: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # budget-004: points back to the recurring template that generated this instance
    recurring_template_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("budget_transactions.id", ondelete="SET NULL"), nullable=True
    )

    # Bank-reported account balance at the time of this transaction.
    # Populated from Teller's running_balance field; NULL for CSV/OFX/manual imports.
    # Used for balance-over-time charts and projected-balance features.
    running_balance: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BudgetTarget(Base):
    """
    Per-month budget target override for a single category.

    Keyed by (category_id, year, month).  When a row exists here, it takes
    precedence over budget_categories.default_monthly_amount for that
    specific month.  To revert a month to the default, delete the row.

    amount convention: always positive (it's a spending envelope, not a
    transaction amount).  The service layer treats income categories the
    same way — the target is how much income you expect for the month.

    profile_id mirrors the category's profile_id for efficient filtering.
    """
    __tablename__ = "budget_targets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    # budget-009: profile mirrors category's profile
    profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("budget_profiles.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("budget_categories.id", ondelete="CASCADE"), nullable=False
    )

    year: Mapped[int] = mapped_column(nullable=False)
    month: Mapped[int] = mapped_column(nullable=False)   # 1–12
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BudgetRolloverAmount(Base):
    """
    Stores the computed carry-forward balance for rollover-enabled categories.

    rollover_amount(M) = effective_target(M-1) - actual_spending(M-1)
    Positive = unspent balance carried forward (adds to next month's effective target).
    Negative = overspend carried forward (reduces next month's effective target).

    Rows are upserted by POST /budget/rollover — recomputing is idempotent.
    The analytics layer reads these rows and adds the carry-forward to the
    category's base target to produce the effective_target for display.
    """
    __tablename__ = "budget_rollover_amounts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("budget_categories.id", ondelete="CASCADE"), nullable=False
    )

    year: Mapped[int] = mapped_column(nullable=False)
    month: Mapped[int] = mapped_column(nullable=False)   # 1–12
    # Positive = unspent balance; negative = overspend.
    rollover_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0.0)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
