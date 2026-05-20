"""
Budget domain — service layer.

All business logic lives here. Routers call these functions; no DB access
happens in routes directly.

Household scoping is enforced on every query. Personal/shared visibility
for transactions is enforced via the scope + owner_user_id columns:
  - household scope  → all household members can see the transaction
  - personal scope   → only the owner_user_id can see the transaction
"""
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.domains.budget.models import (
    BudgetAccount,
    BudgetCategory,
    BudgetTransaction,
)
from life_dashboard.domains.budget.schemas import (
    BudgetAccountCreate,
    BudgetAccountUpdate,
    BudgetAccountResponse,
    BudgetCategoryCreate,
    BudgetCategoryUpdate,
    BudgetCategoryResponse,
    BudgetSummaryResponse,
    BudgetTransactionCreate,
    BudgetTransactionUpdate,
    BudgetTransactionResponse,
    BudgetTransactionListResponse,
    BudgetTransactionBulkImportResponse,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compute_dedup_hash(account_id: uuid.UUID, txn_date: Any, amount: float, description: str) -> str:
    """
    SHA-256 of (account_id, date, amount, description) as a hex string.
    Used to detect duplicate imports from CSV/OFX files.
    """
    raw = f"{account_id}|{txn_date}|{amount:.2f}|{description.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _transaction_visible_to(model: type[BudgetTransaction], user_id: uuid.UUID):
    """
    SQLAlchemy WHERE fragment: transactions the given user may see.
      household scope → any member of the household can see it
      personal scope  → only the owner
    Household scoping (household_id filter) must still be applied separately.
    """
    return or_(
        model.scope == "household",
        model.owner_user_id == user_id,
    )


# ── BudgetAccount ─────────────────────────────────────────────────────────────

async def list_accounts(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    include_archived: bool = False,
) -> list[BudgetAccountResponse]:
    """
    Return accounts the user is entitled to see:
      - Their own accounts (any scope)
      - Shared accounts belonging to any household member
    """
    stmt = select(BudgetAccount).where(
        BudgetAccount.household_id == household_id,
        or_(
            BudgetAccount.owner_user_id == user_id,
            BudgetAccount.scope == "shared",
        ),
    )
    if not include_archived:
        stmt = stmt.where(BudgetAccount.archived_at.is_(None))
    stmt = stmt.order_by(BudgetAccount.created_at)
    result = await db.execute(stmt)
    return [BudgetAccountResponse.model_validate(a) for a in result.scalars().all()]


async def get_account(
    db: AsyncSession,
    account_id: uuid.UUID,
    household_id: uuid.UUID,
) -> BudgetAccount | None:
    stmt = select(BudgetAccount).where(
        BudgetAccount.id == account_id,
        BudgetAccount.household_id == household_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_account(
    db: AsyncSession,
    household_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    data: BudgetAccountCreate,
) -> BudgetAccountResponse:
    account = BudgetAccount(
        household_id=household_id,
        owner_user_id=owner_user_id,
        **data.model_dump(),
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return BudgetAccountResponse.model_validate(account)


async def update_account(
    db: AsyncSession,
    account_id: uuid.UUID,
    household_id: uuid.UUID,
    data: BudgetAccountUpdate,
) -> BudgetAccountResponse | None:
    account = await get_account(db, account_id, household_id)
    if account is None:
        return None
    for field in data.model_fields_set:
        setattr(account, field, getattr(data, field))
    account.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(account)
    return BudgetAccountResponse.model_validate(account)


async def delete_account(
    db: AsyncSession,
    account_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    account = await get_account(db, account_id, household_id)
    if account is None:
        return False
    await db.delete(account)
    await db.commit()
    return True


# ── BudgetCategory ────────────────────────────────────────────────────────────

async def list_categories(
    db: AsyncSession,
    household_id: uuid.UUID,
    include_archived: bool = False,
) -> list[BudgetCategoryResponse]:
    stmt = select(BudgetCategory).where(BudgetCategory.household_id == household_id)
    if not include_archived:
        stmt = stmt.where(BudgetCategory.archived_at.is_(None))
    stmt = stmt.order_by(BudgetCategory.sort_order, BudgetCategory.name)
    result = await db.execute(stmt)
    return [BudgetCategoryResponse.model_validate(c) for c in result.scalars().all()]


async def get_category(
    db: AsyncSession,
    category_id: uuid.UUID,
    household_id: uuid.UUID,
) -> BudgetCategory | None:
    stmt = select(BudgetCategory).where(
        BudgetCategory.id == category_id,
        BudgetCategory.household_id == household_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_category(
    db: AsyncSession,
    household_id: uuid.UUID,
    data: BudgetCategoryCreate,
) -> BudgetCategoryResponse:
    category = BudgetCategory(
        household_id=household_id,
        **data.model_dump(),
    )
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return BudgetCategoryResponse.model_validate(category)


async def update_category(
    db: AsyncSession,
    category_id: uuid.UUID,
    household_id: uuid.UUID,
    data: BudgetCategoryUpdate,
) -> BudgetCategoryResponse | None:
    category = await get_category(db, category_id, household_id)
    if category is None:
        return None
    for field in data.model_fields_set:
        setattr(category, field, getattr(data, field))
    category.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(category)
    return BudgetCategoryResponse.model_validate(category)


async def delete_category(
    db: AsyncSession,
    category_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    category = await get_category(db, category_id, household_id)
    if category is None:
        return False
    await db.delete(category)
    await db.commit()
    return True


# ── BudgetTransaction ─────────────────────────────────────────────────────────

async def list_transactions(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    account_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    scope: str | None = None,
    date_from: Any | None = None,
    date_to: Any | None = None,
    include_archived: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> BudgetTransactionListResponse:
    base = (
        select(BudgetTransaction)
        .where(
            BudgetTransaction.household_id == household_id,
            _transaction_visible_to(BudgetTransaction, user_id),
        )
    )
    if not include_archived:
        base = base.where(BudgetTransaction.archived_at.is_(None))
    if account_id is not None:
        base = base.where(BudgetTransaction.account_id == account_id)
    if category_id is not None:
        base = base.where(BudgetTransaction.category_id == category_id)
    if scope is not None:
        base = base.where(BudgetTransaction.scope == scope)
    if date_from is not None:
        base = base.where(BudgetTransaction.date >= date_from)
    if date_to is not None:
        base = base.where(BudgetTransaction.date <= date_to)

    count_stmt = select(func.count()).select_from(base.subquery())
    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    stmt = base.order_by(BudgetTransaction.date.desc(), BudgetTransaction.created_at.desc())
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    items = [BudgetTransactionResponse.model_validate(t) for t in result.scalars().all()]

    return BudgetTransactionListResponse(items=items, total=total, limit=limit, offset=offset)


async def get_summary(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    account_id: uuid.UUID | None = None,
    date_from: Any | None = None,
    date_to: Any | None = None,
) -> BudgetSummaryResponse:
    """
    Return aggregate income / expense totals for the given date range.
    Does a single SQL aggregation — does not load transaction rows.
    """
    stmt = select(
        func.count().label("transaction_count"),
        func.sum(
            case((BudgetTransaction.amount > 0, BudgetTransaction.amount), else_=0)
        ).label("total_income"),
        func.sum(
            case((BudgetTransaction.amount < 0, BudgetTransaction.amount), else_=0)
        ).label("total_expenses"),
    ).where(
        BudgetTransaction.household_id == household_id,
        _transaction_visible_to(BudgetTransaction, user_id),
        BudgetTransaction.archived_at.is_(None),
    )
    if account_id is not None:
        stmt = stmt.where(BudgetTransaction.account_id == account_id)
    if date_from is not None:
        stmt = stmt.where(BudgetTransaction.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(BudgetTransaction.date <= date_to)

    result = await db.execute(stmt)
    row = result.one()
    return BudgetSummaryResponse(
        total_income=float(row.total_income or 0),
        total_expenses=float(abs(row.total_expenses or 0)),
        transaction_count=int(row.transaction_count or 0),
        date_from=date_from,
        date_to=date_to,
    )


async def get_transaction(
    db: AsyncSession,
    transaction_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> BudgetTransaction | None:
    stmt = select(BudgetTransaction).where(
        BudgetTransaction.id == transaction_id,
        BudgetTransaction.household_id == household_id,
        _transaction_visible_to(BudgetTransaction, user_id),
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_transaction(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: BudgetTransactionCreate,
) -> BudgetTransactionResponse:
    """
    Create a single transaction. The account must belong to this household.
    If scope is not provided it is inherited from the account's scope
    (personal account → personal, shared account → household).
    """
    # Resolve account for scope inheritance and owner_user_id
    account = await get_account(db, data.account_id, household_id)
    if account is None:
        raise ValueError(f"Account {data.account_id} not found in household")

    # Scope inheritance: personal account → personal, shared account → household
    scope = data.scope
    if scope is None:
        scope = "personal" if account.scope == "personal" else "household"

    dedup_hash = _compute_dedup_hash(data.account_id, data.date, data.amount, data.description)

    txn = BudgetTransaction(
        household_id=household_id,
        account_id=data.account_id,
        owner_user_id=account.owner_user_id,
        category_id=data.category_id,
        date=data.date,
        amount=data.amount,
        currency=data.currency,
        description=data.description,
        merchant_name=data.merchant_name,
        notes=data.notes,
        scope=scope,
        split_override=data.split_override,
        import_source=data.import_source,
        external_id=data.external_id,
        dedup_hash=dedup_hash,
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)
    return BudgetTransactionResponse.model_validate(txn)


async def update_transaction(
    db: AsyncSession,
    transaction_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: BudgetTransactionUpdate,
) -> BudgetTransactionResponse | None:
    txn = await get_transaction(db, transaction_id, household_id, user_id)
    if txn is None:
        return None
    for field in data.model_fields_set:
        setattr(txn, field, getattr(data, field))
    txn.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(txn)
    return BudgetTransactionResponse.model_validate(txn)


async def auto_categorize_transactions(
    db: AsyncSession,
    household_id: uuid.UUID,
    account_id: uuid.UUID | None = None,
) -> int:
    """
    Assign categories to uncategorized transactions using keyword matching.

    For each category that has keywords defined, check every uncategorized
    transaction's description and merchant_name (case-insensitive substring).
    The first matching category wins.  Already-categorized transactions are
    left untouched.

    Returns the number of transactions updated.
    """
    # Load all categories that have at least one keyword
    cat_stmt = select(BudgetCategory).where(
        BudgetCategory.household_id == household_id,
        BudgetCategory.archived_at.is_(None),
        BudgetCategory.keywords.isnot(None),
    )
    cat_result = await db.execute(cat_stmt)
    categories = cat_result.scalars().all()

    if not categories:
        return 0

    # Load uncategorized transactions
    txn_stmt = select(BudgetTransaction).where(
        BudgetTransaction.household_id == household_id,
        BudgetTransaction.category_id.is_(None),
        BudgetTransaction.archived_at.is_(None),
    )
    if account_id is not None:
        txn_stmt = txn_stmt.where(BudgetTransaction.account_id == account_id)
    txn_result = await db.execute(txn_stmt)
    transactions = txn_result.scalars().all()

    updated = 0
    for txn in transactions:
        haystack = " ".join(
            filter(None, [txn.description, txn.merchant_name])
        ).lower()
        for cat in categories:
            keywords: list[str] = cat.keywords or []
            if any(kw.strip().lower() in haystack for kw in keywords if kw.strip()):
                txn.category_id = cat.id
                updated += 1
                break  # first match wins

    if updated:
        await db.commit()
    return updated


async def delete_transaction(
    db: AsyncSession,
    transaction_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    txn = await get_transaction(db, transaction_id, household_id, user_id)
    if txn is None:
        return False
    await db.delete(txn)
    await db.commit()
    return True


async def delete_all_transactions(
    db: AsyncSession,
    household_id: uuid.UUID,
    account_id: uuid.UUID | None = None,
) -> int:
    """
    Bulk-delete transactions scoped to the household.
    Optionally restricted to a single account.
    Returns the number of rows deleted.
    """
    stmt = delete(BudgetTransaction).where(
        BudgetTransaction.household_id == household_id
    )
    if account_id is not None:
        stmt = stmt.where(BudgetTransaction.account_id == account_id)
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount  # type: ignore[return-value]


async def bulk_import_transactions(
    db: AsyncSession,
    household_id: uuid.UUID,
    account_id: uuid.UUID,
    import_source: str,
    transactions: list[BudgetTransactionCreate],
) -> BudgetTransactionBulkImportResponse:
    """
    Insert a batch of transactions, skipping any that are duplicates.

    Dedup logic (checked in order):
      1. external_id match against budget_transactions.external_id for the same account
      2. dedup_hash match against budget_transactions.dedup_hash for the same account

    Returns counts of inserted vs skipped rows.
    """
    account = await get_account(db, account_id, household_id)
    if account is None:
        raise ValueError(f"Account {account_id} not found in household")

    # Fetch existing dedup keys for this account in one query
    existing_stmt = select(
        BudgetTransaction.external_id,
        BudgetTransaction.dedup_hash,
    ).where(
        BudgetTransaction.account_id == account_id,
        BudgetTransaction.household_id == household_id,
    )
    existing_result = await db.execute(existing_stmt)
    existing_rows = existing_result.all()
    existing_external_ids = {r.external_id for r in existing_rows if r.external_id}
    existing_dedup_hashes = {r.dedup_hash for r in existing_rows if r.dedup_hash}

    inserted = 0
    skipped = 0

    for t in transactions:
        dedup_hash = _compute_dedup_hash(account_id, t.date, t.amount, t.description)

        # Skip if we've seen this external_id or hash before
        if t.external_id and t.external_id in existing_external_ids:
            skipped += 1
            continue
        if dedup_hash in existing_dedup_hashes:
            skipped += 1
            continue

        scope = t.scope
        if scope is None:
            scope = "personal" if account.scope == "personal" else "household"

        txn = BudgetTransaction(
            household_id=household_id,
            account_id=account_id,
            owner_user_id=account.owner_user_id,
            category_id=t.category_id,
            date=t.date,
            amount=t.amount,
            currency=t.currency,
            description=t.description,
            merchant_name=t.merchant_name,
            notes=t.notes,
            scope=scope,
            split_override=t.split_override,
            import_source=import_source,
            external_id=t.external_id,
            dedup_hash=dedup_hash,
        )
        db.add(txn)

        # Track hashes seen in this batch to catch in-batch duplicates
        if t.external_id:
            existing_external_ids.add(t.external_id)
        existing_dedup_hashes.add(dedup_hash)
        inserted += 1

    await db.commit()
    return BudgetTransactionBulkImportResponse(inserted=inserted, skipped=skipped)
