import uuid
from datetime import date as Date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ── Shared literals ───────────────────────────────────────────────────────────

AccountType = Literal["checking", "savings", "credit_card", "loan", "investment", "other"]
AccountScope = Literal["personal", "shared"]
# budget-010: renamed from personal/household → private/shared
TransactionScope = Literal["private", "shared"]
CategoryDefaultScope = Literal["private", "shared"]
ImportSource = Literal["csv", "ofx", "manual", "teller", "plaid"]
BudgetingStyle = Literal["zero_based", "profit_tracking"]
ProfileMemberRole = Literal["owner", "member", "viewer"]

# split_config / split_override shape: { "<user_id_str>": float }
# All ratios must sum to 1.0. NULL = equal split across active household members.
SplitConfig = dict[str, float] | None


# ── BudgetProfile ─────────────────────────────────────────────────────────────

class BudgetProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    budgeting_style: BudgetingStyle = "zero_based"
    currency: str = Field(default="USD", min_length=3, max_length=3)
    sort_order: int = 0


class BudgetProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    budgeting_style: BudgetingStyle | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    sort_order: int | None = None


class BudgetProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    name: str
    budgeting_style: str
    currency: str
    sort_order: int
    created_at: datetime
    updated_at: datetime


# ── BudgetProfileMember ───────────────────────────────────────────────────────

class BudgetProfileMemberAdd(BaseModel):
    user_id: uuid.UUID
    role: ProfileMemberRole = "member"


class BudgetProfileMemberUpdate(BaseModel):
    role: ProfileMemberRole


class BudgetProfileMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    profile_id: uuid.UUID | None
    user_id: uuid.UUID
    role: str
    created_at: datetime
    updated_at: datetime


# ── BudgetAccount ─────────────────────────────────────────────────────────────

class BudgetAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    account_type: AccountType = "checking"
    scope: AccountScope = "personal"
    currency: str = Field(default="USD", min_length=3, max_length=3)
    profile_id: uuid.UUID | None = None   # defaults to Personal profile at service layer


class BudgetAccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    account_type: AccountType | None = None
    scope: AccountScope | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    profile_id: uuid.UUID | None = None
    archived_at: datetime | None = None
    # budget-017: manually-maintained balance
    current_balance: float | None = None


class BudgetAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    owner_user_id: uuid.UUID
    profile_id: uuid.UUID | None  # NULL when the assigned profile was deleted (ondelete=SET NULL)
    name: str
    account_type: str
    scope: str
    currency: str
    # budget-017: manually-maintained balance
    current_balance: float | None = None
    balance_updated_at: datetime | None = None
    # Teller bank sync — all None when account is not linked
    teller_enrollment_id: str | None = None
    teller_account_id: str | None = None
    teller_institution_name: str | None = None
    teller_last_synced_at: datetime | None = None
    # teller_access_token intentionally excluded — never returned to the frontend
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


# ── Teller bank sync schemas ──────────────────────────────────────────────────

class TellerConnectRequest(BaseModel):
    """
    Payload sent by the frontend after a successful Teller Connect flow.
    The frontend receives this from the TellerConnect.setup() onSuccess callback.
    One enrollment may cover multiple bank accounts; the API calls GET /accounts
    to discover all of them and creates a BudgetAccount for each.
    """
    access_token: str
    enrollment_id: str
    institution_name: str
    # Optional: limit which Teller accounts to import (by Teller account ID).
    # When empty / omitted, all accounts in the enrollment are imported.
    account_ids: list[str] = []


class TellerSyncResult(BaseModel):
    """Result of a polling sync for one Teller-linked BudgetAccount."""
    account_id: uuid.UUID
    teller_account_id: str
    institution_name: str | None
    inserted: int
    skipped: int
    auto_categorized: int
    last_synced_at: datetime


class TellerSyncAllResult(BaseModel):
    """Aggregate result of syncing all Teller-linked accounts in a household."""
    accounts_synced: int
    total_inserted: int
    total_skipped: int
    total_auto_categorized: int
    results: list[TellerSyncResult]


class TellerConfigResponse(BaseModel):
    """
    Public Teller configuration returned to the frontend.
    Tells the frontend whether bank sync is available and how to initialise
    the Teller Connect widget.  The access token is never included here.
    """
    enabled: bool
    app_id: str | None
    environment: str  # sandbox | development | production


# ── BudgetCategoryGroup ───────────────────────────────────────────────────────

class BudgetCategoryGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    sort_order: int = 0
    is_income: bool = False
    profile_id: uuid.UUID | None = None   # defaults to Household profile at service layer


class BudgetCategoryGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    sort_order: int | None = None
    is_income: bool | None = None
    profile_id: uuid.UUID | None = None


class BudgetCategoryGroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    profile_id: uuid.UUID | None
    name: str
    sort_order: int
    is_income: bool
    created_at: datetime
    updated_at: datetime


# ── BudgetCategory ────────────────────────────────────────────────────────────

class BudgetCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    default_scope: CategoryDefaultScope = "private"
    split_config: SplitConfig = None
    color: str | None = Field(default=None, max_length=20)
    icon: str | None = Field(default=None, max_length=10)
    sort_order: int = 0
    keywords: list[str] | None = None
    group_id: uuid.UUID | None = None
    default_monthly_amount: float | None = None
    rollover_enabled: bool = False
    is_recurring_revenue: bool = False
    profile_id: uuid.UUID | None = None   # defaults to Personal profile at service layer
    notify_threshold_pct: int | None = 80


class BudgetCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    default_scope: CategoryDefaultScope | None = None
    split_config: SplitConfig = None
    color: str | None = None
    icon: str | None = None
    sort_order: int | None = None
    keywords: list[str] | None = None
    group_id: uuid.UUID | None = None
    archived_at: datetime | None = None
    default_monthly_amount: float | None = None
    rollover_enabled: bool | None = None
    is_recurring_revenue: bool | None = None
    profile_id: uuid.UUID | None = None
    notify_threshold_pct: int | None = None


class BudgetCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    profile_id: uuid.UUID | None
    name: str
    default_scope: str
    split_config: dict[str, Any] | None
    color: str | None
    icon: str | None
    sort_order: int
    keywords: list[str] | None
    group_id: uuid.UUID | None
    default_monthly_amount: float | None
    rollover_enabled: bool
    is_recurring_revenue: bool
    notify_threshold_pct: int | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BudgetCategoryGroupWithCategories(BaseModel):
    """A group with its member categories nested — used by GET /budget/categories/grouped."""
    id: uuid.UUID | None          # None for the implicit "Other" bucket
    name: str
    sort_order: int
    is_income: bool
    categories: list[BudgetCategoryResponse]


# ── BudgetTarget ──────────────────────────────────────────────────────────────

class BudgetTargetUpsert(BaseModel):
    """
    Upsert a per-month budget target for a category.
    Set amount=None to clear the override (reverts to default_monthly_amount).
    """
    category_id: uuid.UUID
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    amount: float | None = Field(default=None, ge=0)


class BudgetTargetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    profile_id: uuid.UUID | None
    category_id: uuid.UUID
    year: int
    month: int
    amount: float
    created_at: datetime
    updated_at: datetime


class RolloverComputeResponse(BaseModel):
    """Result of POST /budget/rollover — how many categories were updated."""
    year: int
    month: int
    categories_updated: int   # rollover-enabled categories whose carry-forward was stored
    total_carried_forward: float  # net sum of all rollover amounts (can be negative)


class BudgetTargetMonthResponse(BaseModel):
    """
    Effective targets for all categories for a given month.
    Maps category_id (str) → effective amount (float | None).
    Override rows take precedence over default_monthly_amount.
    Categories with no target at all are absent from the map (or None).
    """
    year: int
    month: int
    targets: dict[str, float | None]   # category_id → effective amount


class AutoCategorizeResponse(BaseModel):
    updated: int  # number of transactions that had a category assigned


class ApplyToSimilarResponse(BaseModel):
    updated: int          # transactions categorized (excluding the original)
    keyword_added: bool   # whether the merchant name was added as a new keyword


class BudgetSummaryResponse(BaseModel):
    """Aggregate totals for a date range — used by the summary bar on the budget page."""
    total_income: float        # sum of positive amounts (inflows)
    total_expenses: float      # sum of abs(negative amounts) — always positive
    transaction_count: int
    date_from: Date | None
    date_to: Date | None


class BudgetTrendMonth(BaseModel):
    """One month's totals for the spending-trends chart."""
    year: int
    month: int
    total_income: float
    total_expenses: float
    total_budgeted: float   # sum of effective targets for that month (0 if none set)
    net: float              # total_income - total_expenses


class BudgetTrendsResponse(BaseModel):
    """GET /budget/trends — last N months of income/expense/budget totals."""
    months: list[BudgetTrendMonth]


class BudgetCategoryAnalyticsEntry(BaseModel):
    category_id: uuid.UUID | None
    category_name: str
    category_color: str | None
    category_icon: str | None
    total_expenses: float       # abs(sum of negative amounts)
    total_income: float         # sum of positive amounts
    transaction_count: int
    # Budget target fields (None when no target is set for this category/month)
    budgeted: float | None      # effective target = base + rollover (None if no target)
    remaining: float | None     # budgeted - total_expenses (negative = over budget)
    is_over_budget: bool        # True when total_expenses > budgeted (and budgeted is set)
    rollover_amount: float      # carry-forward from previous month (0 if rollover disabled)


class BudgetAnalyticsResponse(BaseModel):
    """Per-category spending breakdown for a calendar month (zero_based profiles)."""
    year: int
    month: int
    date_from: Date
    date_to: Date
    total_expenses: float
    total_income: float
    transaction_count: int
    total_budgeted: float   # sum of targets for categories that have expenses this month
    total_targets: float    # sum of ALL effective targets for ALL categories this month
                            # (including categories with no spending yet)
                            # Used for: Ready to assign = total_income - total_targets
    by_category: list[BudgetCategoryAnalyticsEntry]


class BudgetProfitAnalyticsResponse(BaseModel):
    """P&L view for profit_tracking profiles (budget-012)."""
    year: int
    month: int
    date_from: Date
    date_to: Date
    total_revenue: float        # sum of positive amounts
    total_expenses: float       # abs(sum of negative amounts)
    net_profit: float           # total_revenue - total_expenses
    transaction_count: int
    by_category: list[BudgetCategoryAnalyticsEntry]
    # budget-013: MRR metrics (only populated when profile has MRR categories)
    mrr_actual: float           # sum of recurring revenue this month
    arr_projected: float        # mrr_actual × 12
    mrr_prev_month: float       # mrr from previous month (for growth calc)
    mrr_growth_pct: float | None  # (mrr_actual - mrr_prev_month) / mrr_prev_month × 100


# ── BudgetTransaction ─────────────────────────────────────────────────────────

class RecurringRule(BaseModel):
    """
    Recurrence rule for a budget transaction template.
    Matches the shape used in the todos domain.
    """
    frequency: Literal["weekly", "monthly", "bi_weekly", "semi_monthly"]
    interval: int = Field(default=1, ge=1, le=52)
    end_date: Date | None = None


class BudgetTransactionCreate(BaseModel):
    account_id: uuid.UUID
    category_id: uuid.UUID | None = None
    date: Date
    # Negative = expense, positive = income/refund
    amount: float
    currency: str = Field(default="USD", min_length=3, max_length=3)
    description: str = Field(min_length=1)
    merchant_name: str | None = None
    notes: str | None = None
    # budget-010: private / shared (inherits from account if not provided)
    scope: TransactionScope | None = None
    split_override: SplitConfig = None
    import_source: ImportSource | None = None
    external_id: str | None = None
    is_transfer: bool = False
    # Bank-reported balance at transaction time (Teller only; NULL otherwise)
    running_balance: float | None = None
    # budget-004: recurring rule; None = one-off transaction
    recurring: RecurringRule | None = None


class BudgetTransactionUpdate(BaseModel):
    category_id: uuid.UUID | None = None
    date: Date | None = None
    amount: float | None = None
    description: str | None = Field(default=None, min_length=1)
    merchant_name: str | None = None
    notes: str | None = None
    scope: TransactionScope | None = None
    split_override: SplitConfig = None
    is_transfer: bool | None = None
    archived_at: datetime | None = None
    # budget-004: set/clear the recurring rule
    recurring: RecurringRule | None = None


class BudgetTransactionReattribute(BaseModel):
    """budget-011: Re-attribute a transaction to a different profile for analytics."""
    target_profile_id: uuid.UUID | None   # None = revert to account's profile


class BudgetTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    account_id: uuid.UUID
    owner_user_id: uuid.UUID
    category_id: uuid.UUID | None
    profile_id: uuid.UUID | None   # budget-011: None = inherit from account
    date: Date
    amount: float
    currency: str
    description: str
    merchant_name: str | None
    notes: str | None
    scope: str
    split_override: dict[str, Any] | None
    is_transfer: bool
    running_balance: float | None
    import_source: str | None
    external_id: str | None
    # budget-004: recurring rule (non-null = this is a template)
    recurring: dict[str, Any] | None
    # budget-004: points to the template that generated this instance
    recurring_template_id: uuid.UUID | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BudgetTransactionListResponse(BaseModel):
    items: list[BudgetTransactionResponse]
    total: int
    limit: int
    offset: int


# ── Bulk import ───────────────────────────────────────────────────────────────

class BudgetTransactionBulkImport(BaseModel):
    """
    Payload for the bulk-upsert import endpoint.
    Transactions with a dedup_hash or external_id already in the DB are skipped.
    """
    account_id: uuid.UUID
    import_source: ImportSource
    transactions: list[BudgetTransactionCreate] = Field(min_length=1)


class BudgetTransactionBulkImportResponse(BaseModel):
    inserted: int
    skipped: int           # duplicates detected and skipped
    auto_categorized: int = 0  # transactions matched by keyword rules after import


# ── File import (OFX / CSV) ───────────────────────────────────────────────────

class CSVColumnMapping(BaseModel):
    """
    Maps CSV column header names to transaction fields.
    Exactly one of amount_col or (debit_col + credit_col) should be provided.
    """
    date_col: str
    description_col: str
    amount_col: str | None = None    # signed single column
    debit_col: str | None = None     # outflow (positive value = money out)
    credit_col: str | None = None    # inflow  (positive value = money in)
    merchant_col: str | None = None  # optional second description column


class BudgetImportDetectResponse(BaseModel):
    """
    Returned by POST /budget/import/detect.
    Provides enough information for the frontend to render the column-mapping
    step (CSV) or a simple confirmation step (OFX).
    """
    format: Literal["ofx", "csv", "unknown"]
    # CSV only
    columns: list[str] | None = None
    sample_rows: list[list[str]] | None = None   # up to 5 data rows, values as strings
    detected_mapping: CSVColumnMapping | None = None
    mapping_confidence: float | None = None       # 0.0–1.0
    # Both formats
    estimated_transaction_count: int | None = None
    date_range_start: Date | None = None
    date_range_end: Date | None = None
    errors: list[str] = Field(default_factory=list)


class BudgetFileImportResponse(BaseModel):
    """Returned by POST /budget/import after parsing + inserting."""
    inserted: int
    skipped: int
    auto_categorized: int = 0  # transactions matched by keyword rules after import
    parse_errors: list[str] = Field(default_factory=list)


# ── Profile seeding ───────────────────────────────────────────────────────────

class SeedProfilesResponse(BaseModel):
    """Result of POST /budget/profiles/seed-defaults."""
    profiles_created: int
    members_seeded: int


class ReattributeResponse(BaseModel):
    """Result of POST /budget/transactions/{id}/move-to-profile."""
    transaction_id: uuid.UUID
    target_profile_id: uuid.UUID | None
    split_prompt: bool   # True when the target category has a split_config and user should confirm


class RecurringGenerateResponse(BaseModel):
    """Result of POST /budget/recurring/generate."""
    year: int
    month: int
    generated: int   # number of new transaction instances created


# ── budget-020: Income forecasting ────────────────────────────────────────────

class IncomeForecastSource(BaseModel):
    """A single projected income occurrence derived from a recurring template."""
    template_id: uuid.UUID
    description: str
    amount: float
    category_id: uuid.UUID | None
    category_name: str | None
    expected_date: Date


class IncomeForecastResponse(BaseModel):
    """
    GET /budget/income-forecast — forward-looking income allocation view.

    projected_income: sum of all recurring-income template occurrences that
        fire in the target month (amount > 0, non-transfer).
    actual_income: income actually received this month (from analytics).
        Zero for future months.
    sources: per-occurrence breakdown of projected income.
    total_targets: sum of all active category budget targets for the month
        (same figure used by "Ready to assign").
    left_to_allocate: projected_income - total_targets.
    is_future_month: True when the requested month is strictly after today.
    """
    year: int
    month: int
    projected_income: float
    actual_income: float
    sources: list[IncomeForecastSource]
    total_targets: float
    left_to_allocate: float
    is_future_month: bool
