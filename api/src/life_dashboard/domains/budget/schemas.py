import uuid
from datetime import date as Date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ── Shared literals ───────────────────────────────────────────────────────────

AccountType = Literal["checking", "savings", "credit_card", "loan", "investment", "other"]
AccountScope = Literal["personal", "shared"]
TransactionScope = Literal["personal", "household"]
CategoryDefaultScope = Literal["personal", "household"]
ImportSource = Literal["csv", "ofx", "manual", "teller", "plaid"]

# split_config / split_override shape: { "<user_id_str>": float }
# All ratios must sum to 1.0. NULL = equal split across active household members.
SplitConfig = dict[str, float] | None


# ── BudgetAccount ─────────────────────────────────────────────────────────────

class BudgetAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    account_type: AccountType = "checking"
    scope: AccountScope = "personal"
    currency: str = Field(default="USD", min_length=3, max_length=3)


class BudgetAccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    account_type: AccountType | None = None
    scope: AccountScope | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    archived_at: datetime | None = None


class BudgetAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    owner_user_id: uuid.UUID
    name: str
    account_type: str
    scope: str
    currency: str
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


# ── BudgetCategory ────────────────────────────────────────────────────────────

class BudgetCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    default_scope: CategoryDefaultScope = "personal"
    split_config: SplitConfig = None
    color: str | None = Field(default=None, max_length=20)
    icon: str | None = Field(default=None, max_length=10)
    sort_order: int = 0
    keywords: list[str] | None = None


class BudgetCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    default_scope: CategoryDefaultScope | None = None
    split_config: SplitConfig = None
    color: str | None = None
    icon: str | None = None
    sort_order: int | None = None
    keywords: list[str] | None = None
    archived_at: datetime | None = None


class BudgetCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    name: str
    default_scope: str
    split_config: dict[str, Any] | None
    color: str | None
    icon: str | None
    sort_order: int
    keywords: list[str] | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


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


class BudgetCategoryAnalyticsEntry(BaseModel):
    category_id: uuid.UUID | None
    category_name: str
    category_color: str | None
    category_icon: str | None
    total_expenses: float       # abs(sum of negative amounts)
    total_income: float         # sum of positive amounts
    transaction_count: int


class BudgetAnalyticsResponse(BaseModel):
    """Per-category spending breakdown for a calendar month."""
    year: int
    month: int
    date_from: Date
    date_to: Date
    total_expenses: float
    total_income: float
    transaction_count: int
    by_category: list[BudgetCategoryAnalyticsEntry]


# ── BudgetTransaction ─────────────────────────────────────────────────────────

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
    # If not provided, defaults to the account's scope at insert time (service layer)
    scope: TransactionScope | None = None
    split_override: SplitConfig = None
    import_source: ImportSource | None = None
    external_id: str | None = None
    is_transfer: bool = False


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


class BudgetTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    account_id: uuid.UUID
    owner_user_id: uuid.UUID
    category_id: uuid.UUID | None
    date: Date
    amount: float
    currency: str
    description: str
    merchant_name: str | None
    notes: str | None
    scope: str
    split_override: dict[str, Any] | None
    is_transfer: bool
    import_source: str | None
    external_id: str | None
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
