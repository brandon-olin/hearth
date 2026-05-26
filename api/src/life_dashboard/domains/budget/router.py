import io
import json
import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi import status as http_status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import User
from life_dashboard.core.database import get_db
from life_dashboard.domains.budget.parsers.ofx_parser import OFXParseError, parse_ofx
from life_dashboard.domains.budget.parsers.csv_parser import (
    ColumnMapping as _CSVColumnMapping,
    detect_csv_columns,
    parse_csv,
)
from life_dashboard.domains.budget.schemas import (
    ApplyToSimilarResponse,
    AutoCategorizeResponse,
    BudgetAccountCreate,
    BudgetAccountUpdate,
    BudgetAccountResponse,
    TellerConnectRequest,
    TellerSyncResult,
    TellerSyncAllResult,
    TellerConfigResponse,
    BudgetAnalyticsResponse,
    BudgetCategoryCreate,
    BudgetCategoryUpdate,
    BudgetCategoryResponse,
    BudgetCategoryGroupCreate,
    BudgetCategoryGroupUpdate,
    BudgetCategoryGroupResponse,
    BudgetCategoryGroupWithCategories,
    BudgetProfileCreate,
    BudgetProfileUpdate,
    BudgetProfileResponse,
    BudgetProfileMemberAdd,
    BudgetProfileMemberUpdate,
    BudgetProfileMemberResponse,
    BudgetProfitAnalyticsResponse,
    BudgetTargetUpsert,
    BudgetTargetResponse,
    BudgetTargetMonthResponse,
    ReattributeResponse,
    RolloverComputeResponse,
    SeedProfilesResponse,
    BudgetSummaryResponse,
    BudgetTransactionCreate,
    BudgetTransactionUpdate,
    BudgetTransactionReattribute,
    BudgetTransactionResponse,
    BudgetTransactionListResponse,
    BudgetTransactionBulkImport,
    BudgetTransactionBulkImportResponse,
    CSVColumnMapping,
    BudgetImportDetectResponse,
    BudgetFileImportResponse,
    BudgetTrendsResponse,
    IncomeForecastResponse,
    RecurringGenerateResponse,
)
from life_dashboard.domains.budget import service

router = APIRouter(prefix="/budget", tags=["budget"])


# ── Budget Profiles (budget-009) ──────────────────────────────────────────────

@router.get("/profiles", response_model=list[BudgetProfileResponse])
async def list_profiles(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BudgetProfileResponse]:
    """Return all budget profiles the current user is a member of."""
    return await service.list_profiles(db, current_user.household_id, current_user.id)


@router.post(
    "/profiles",
    response_model=BudgetProfileResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def create_profile(
    data: BudgetProfileCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetProfileResponse:
    """
    Create a new budget profile. Business profiles (profit_tracking) are a
    paid-tier feature — returns 402 if the free-tier limit is exceeded.
    """
    try:
        return await service.create_profile(db, current_user.household_id, current_user.id, data)
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc))


@router.post("/profiles/seed-defaults", response_model=SeedProfilesResponse)
async def seed_default_profiles(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SeedProfilesResponse:
    """
    Idempotently create the default Personal and Household profiles for this
    household and seed all household members into each profile.
    """
    return await service.seed_default_profiles(
        db, current_user.household_id, current_user.id
    )


@router.get("/profiles/{profile_id}", response_model=BudgetProfileResponse)
async def get_profile(
    profile_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetProfileResponse:
    profile = await service.get_profile(db, profile_id, current_user.household_id)
    if profile is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return BudgetProfileResponse.model_validate(profile)


@router.patch("/profiles/{profile_id}", response_model=BudgetProfileResponse)
async def update_profile(
    profile_id: uuid.UUID,
    data: BudgetProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetProfileResponse:
    result = await service.update_profile(db, profile_id, current_user.household_id, data)
    if result is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return result


@router.delete("/profiles/{profile_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_profile(
    profile_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    try:
        deleted = await service.delete_profile(db, profile_id, current_user.household_id)
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if not deleted:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Profile not found")


# ── Profile Members (budget-014) ──────────────────────────────────────────────

@router.get(
    "/profiles/{profile_id}/members",
    response_model=list[BudgetProfileMemberResponse],
)
async def list_profile_members(
    profile_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BudgetProfileMemberResponse]:
    return await service.list_profile_members(db, profile_id, current_user.household_id)


@router.post(
    "/profiles/{profile_id}/members",
    response_model=BudgetProfileMemberResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def add_profile_member(
    profile_id: uuid.UUID,
    data: BudgetProfileMemberAdd,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetProfileMemberResponse:
    try:
        return await service.add_profile_member(db, profile_id, current_user.household_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.patch(
    "/profiles/{profile_id}/members/{user_id}",
    response_model=BudgetProfileMemberResponse,
)
async def update_profile_member(
    profile_id: uuid.UUID,
    user_id: uuid.UUID,
    data: BudgetProfileMemberUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetProfileMemberResponse:
    result = await service.update_profile_member(
        db, profile_id, current_user.household_id, user_id, data, current_user.id
    )
    if result is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Member not found")
    return result


@router.delete(
    "/profiles/{profile_id}/members/{user_id}",
    status_code=http_status.HTTP_204_NO_CONTENT,
)
async def remove_profile_member(
    profile_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    try:
        deleted = await service.remove_profile_member(
            db, profile_id, current_user.household_id, user_id, current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if not deleted:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Member not found")


# ── Accounts ──────────────────────────────────────────────────────────────────

@router.get("/accounts", response_model=list[BudgetAccountResponse])
async def list_accounts(
    include_archived: bool = Query(default=False),
    profile_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BudgetAccountResponse]:
    return await service.list_accounts(
        db, current_user.household_id, current_user.id,
        include_archived=include_archived,
        profile_id=profile_id,
    )


@router.post("/accounts", response_model=BudgetAccountResponse, status_code=http_status.HTTP_201_CREATED)
async def create_account(
    data: BudgetAccountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetAccountResponse:
    try:
        return await service.create_account(db, current_user.household_id, current_user.id, data)
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/accounts/{account_id}", response_model=BudgetAccountResponse)
async def get_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetAccountResponse:
    account = await service.get_account(db, account_id, current_user.household_id)
    if account is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Account not found")
    return BudgetAccountResponse.model_validate(account)


@router.patch("/accounts/{account_id}", response_model=BudgetAccountResponse)
async def update_account(
    account_id: uuid.UUID,
    data: BudgetAccountUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetAccountResponse:
    result = await service.update_account(db, account_id, current_user.household_id, data)
    if result is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Account not found")
    return result


@router.delete("/accounts/{account_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    deleted = await service.delete_account(db, account_id, current_user.household_id)
    if not deleted:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Account not found")


# ── Category groups ───────────────────────────────────────────────────────────

@router.get("/category-groups", response_model=list[BudgetCategoryGroupResponse])
async def list_groups(
    profile_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BudgetCategoryGroupResponse]:
    return await service.list_groups(db, current_user.household_id, profile_id=profile_id)


@router.post(
    "/category-groups",
    response_model=BudgetCategoryGroupResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def create_group(
    data: BudgetCategoryGroupCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetCategoryGroupResponse:
    try:
        return await service.create_group(db, current_user.household_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.patch("/category-groups/{group_id}", response_model=BudgetCategoryGroupResponse)
async def update_group(
    group_id: uuid.UUID,
    data: BudgetCategoryGroupUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetCategoryGroupResponse:
    result = await service.update_group(db, group_id, current_user.household_id, data)
    if result is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Group not found")
    return result


@router.delete("/category-groups/{group_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    deleted = await service.delete_group(db, group_id, current_user.household_id)
    if not deleted:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Group not found")


@router.post("/category-groups/seed-defaults", response_model=dict)
async def seed_default_groups(
    profile_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Idempotently create the default YNAB-inspired category groups for the
    household and assign matching categories by name.
    For profit_tracking profiles, seeds business-specific group names instead.
    """
    return await service.seed_default_groups(db, current_user.household_id, profile_id=profile_id)


# ── Categories ────────────────────────────────────────────────────────────────

@router.post("/categories/auto-budget", response_model=list[dict])
async def auto_budget_fixed(
    months: int = Query(default=3, ge=1, le=12, description="Number of full calendar months to average"),
    group_name: str = Query(default="Fixed Monthly", description="Group whose categories to auto-budget"),
    profile_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """
    Average the last N full months of spending for every category in the named
    group and write the result to each category's default_monthly_amount.
    Returns the list of categories that were updated with old/new amounts.
    """
    return await service.auto_budget_fixed_categories(
        db, current_user.household_id,
        profile_id=profile_id,
        months=months,
        group_name=group_name,
    )


@router.get("/categories/grouped", response_model=list[BudgetCategoryGroupWithCategories])
async def list_categories_grouped(
    include_archived: bool = Query(default=False),
    profile_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BudgetCategoryGroupWithCategories]:
    """Return categories nested inside their groups, with an implicit Other bucket for ungrouped."""
    return await service.list_categories_grouped(
        db, current_user.household_id,
        include_archived=include_archived,
        profile_id=profile_id,
    )


@router.get("/categories", response_model=list[BudgetCategoryResponse])
async def list_categories(
    include_archived: bool = Query(default=False),
    profile_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BudgetCategoryResponse]:
    return await service.list_categories(
        db, current_user.household_id,
        include_archived=include_archived,
        profile_id=profile_id,
    )


@router.post("/categories", response_model=BudgetCategoryResponse, status_code=http_status.HTTP_201_CREATED)
async def create_category(
    data: BudgetCategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetCategoryResponse:
    try:
        return await service.create_category(db, current_user.household_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/categories/{category_id}", response_model=BudgetCategoryResponse)
async def get_category(
    category_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetCategoryResponse:
    category = await service.get_category(db, category_id, current_user.household_id)
    if category is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Category not found")
    return BudgetCategoryResponse.model_validate(category)


@router.patch("/categories/{category_id}", response_model=BudgetCategoryResponse)
async def update_category(
    category_id: uuid.UUID,
    data: BudgetCategoryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetCategoryResponse:
    result = await service.update_category(db, category_id, current_user.household_id, data)
    if result is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Category not found")
    return result


@router.delete("/categories/{category_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    deleted = await service.delete_category(db, category_id, current_user.household_id)
    if not deleted:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Category not found")


# ── Budget Targets ────────────────────────────────────────────────────────────

@router.get("/targets", response_model=BudgetTargetMonthResponse)
async def get_targets(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    profile_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetTargetMonthResponse:
    return await service.get_effective_targets(
        db, current_user.household_id, year, month, profile_id=profile_id
    )


@router.put("/targets", response_model=BudgetTargetResponse | None)
async def upsert_target(
    data: BudgetTargetUpsert,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetTargetResponse | None:
    result = await service.upsert_target(db, current_user.household_id, data)
    if result is None and data.amount is not None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Category not found")
    return result


@router.post("/rollover", response_model=RolloverComputeResponse)
async def compute_rollover(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    profile_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RolloverComputeResponse:
    return await service.compute_and_store_rollover(
        db, current_user.household_id, year, month, profile_id=profile_id
    )


# ── Summary ───────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=BudgetSummaryResponse)
async def get_summary(
    account_id: uuid.UUID | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    profile_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetSummaryResponse:
    return await service.get_summary(
        db, current_user.household_id, current_user.id,
        account_id=account_id,
        date_from=date_from,
        date_to=date_to,
        profile_id=profile_id,
    )


# ── Analytics ─────────────────────────────────────────────────────────────────

@router.get("/analytics", response_model=BudgetAnalyticsResponse)
async def get_analytics(
    year: int | None = Query(default=None, ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    account_id: uuid.UUID | None = Query(default=None),
    profile_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetAnalyticsResponse:
    """
    Per-category spending breakdown for a calendar month or arbitrary date range.

    Pass year+month for the standard monthly view (with budget targets + rollover).
    Pass date_from+date_to for an arbitrary range (budget targets omitted).
    Defaults to the current month when all date params are omitted.
    For profit_tracking profiles, use GET /budget/analytics/profit instead.
    """
    # If explicit date range provided, use it directly
    if date_from is not None or date_to is not None:
        return await service.get_analytics(
            db, current_user.household_id, current_user.id,
            date_from=date_from,
            date_to=date_to,
            account_id=account_id,
            profile_id=profile_id,
        )
    # Otherwise fall back to month-based (default: current month)
    today = date.today()
    resolved_year = year if year is not None else today.year
    resolved_month = month if month is not None else today.month
    return await service.get_analytics(
        db, current_user.household_id, current_user.id,
        year=resolved_year,
        month=resolved_month,
        account_id=account_id,
        profile_id=profile_id,
    )


@router.get("/analytics/profit", response_model=BudgetProfitAnalyticsResponse)
async def get_profit_analytics(
    profile_id: uuid.UUID = Query(...),
    year: int | None = Query(default=None, ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetProfitAnalyticsResponse:
    """
    P&L analytics for a profit_tracking profile (budget-012 / budget-013).
    Returns revenue, expenses, net profit, MRR, ARR, and MoM MRR growth.
    """
    today = date.today()
    resolved_year = year if year is not None else today.year
    resolved_month = month if month is not None else today.month

    # Verify profile belongs to this household and is profit_tracking
    profile = await service.get_profile(db, profile_id, current_user.household_id)
    if profile is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Profile not found")

    return await service.get_profit_analytics(
        db, current_user.household_id, current_user.id,
        year=resolved_year,
        month=resolved_month,
        profile_id=profile_id,
    )


# ── Transactions ──────────────────────────────────────────────────────────────

@router.get("/transactions", response_model=BudgetTransactionListResponse)
async def list_transactions(
    account_id: uuid.UUID | None = Query(default=None),
    category_id: uuid.UUID | None = Query(default=None),
    uncategorized: bool = Query(default=False),
    txn_type: str | None = Query(default=None, pattern="^(uncategorized|transfers|income|expenses|recurring)$"),
    scope: str | None = Query(default=None, pattern="^(private|shared)$"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    include_archived: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    profile_id: uuid.UUID | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetTransactionListResponse:
    return await service.list_transactions(
        db, current_user.household_id, current_user.id,
        account_id=account_id,
        category_id=category_id,
        uncategorized=uncategorized,
        txn_type=txn_type,
        scope=scope,
        date_from=date_from,
        date_to=date_to,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
        profile_id=profile_id,
        search=search,
    )


@router.post("/transactions", response_model=BudgetTransactionResponse, status_code=http_status.HTTP_201_CREATED)
async def create_transaction(
    data: BudgetTransactionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetTransactionResponse:
    try:
        return await service.create_transaction(db, current_user.household_id, current_user.id, data)
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/transactions/export")
async def export_transactions_csv(
    account_id: uuid.UUID | None = Query(default=None),
    category_id: uuid.UUID | None = Query(default=None),
    scope: str | None = Query(default=None, pattern="^(private|shared)$"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    profile_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    csv_content = await service.export_transactions_csv(
        db, current_user.household_id, current_user.id,
        account_id=account_id,
        category_id=category_id,
        scope=scope,
        date_from=date_from,
        date_to=date_to,
        profile_id=profile_id,
    )
    ref_date = date_from or date.today()
    filename = f"hearth-budget-{ref_date.strftime('%Y-%m')}.csv"
    return StreamingResponse(
        io.BytesIO(csv_content.encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/transactions/{transaction_id}", response_model=BudgetTransactionResponse)
async def get_transaction(
    transaction_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetTransactionResponse:
    txn = await service.get_transaction(db, transaction_id, current_user.household_id, current_user.id)
    if txn is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return BudgetTransactionResponse.model_validate(txn)


@router.patch("/transactions/{transaction_id}", response_model=BudgetTransactionResponse)
async def update_transaction(
    transaction_id: uuid.UUID,
    data: BudgetTransactionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetTransactionResponse:
    result = await service.update_transaction(
        db, transaction_id, current_user.household_id, current_user.id, data
    )
    if result is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return result


@router.post(
    "/transactions/{transaction_id}/move-to-profile",
    response_model=ReattributeResponse,
)
async def reattribute_transaction(
    transaction_id: uuid.UUID,
    data: BudgetTransactionReattribute,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReattributeResponse:
    """
    budget-011: Re-attribute a transaction to a different profile for analytics.
    The account balance is unaffected — this is purely an analytics operation.
    Pass target_profile_id=null to revert to the account's default profile.
    """
    try:
        return await service.reattribute_transaction(
            db, transaction_id, current_user.household_id, current_user.id,
            data.target_profile_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/apply-to-similar", response_model=ApplyToSimilarResponse)
async def apply_category_to_similar(
    transaction_id: uuid.UUID = Query(...),
    category_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApplyToSimilarResponse:
    updated, keyword_added = await service.apply_category_to_similar(
        db, transaction_id, category_id, current_user.household_id, current_user.id
    )
    return ApplyToSimilarResponse(updated=updated, keyword_added=keyword_added)


@router.post("/apply-transfer-to-similar")
async def apply_transfer_to_similar(
    transaction_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    updated = await service.apply_transfer_to_similar(
        db, transaction_id, current_user.household_id, current_user.id
    )
    return {"updated": updated}


@router.delete("/transactions", status_code=http_status.HTTP_200_OK)
async def bulk_delete_transactions(
    account_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    deleted = await service.delete_all_transactions(
        db, current_user.household_id, account_id=account_id
    )
    return {"deleted": deleted}


@router.delete("/transactions/{transaction_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_transaction(
    transaction_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    deleted = await service.delete_transaction(
        db, transaction_id, current_user.household_id, current_user.id
    )
    if not deleted:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Transaction not found")


# ── Bulk import ───────────────────────────────────────────────────────────────

@router.post("/transactions/import", response_model=BudgetTransactionBulkImportResponse, status_code=http_status.HTTP_201_CREATED)
async def bulk_import_transactions(
    data: BudgetTransactionBulkImport,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetTransactionBulkImportResponse:
    try:
        result = await service.bulk_import_transactions(
            db,
            current_user.household_id,
            data.account_id,
            data.import_source,
            data.transactions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc))

    auto_categorized = 0
    if result.inserted > 0:
        auto_categorized = await service.auto_categorize_transactions(
            db, current_user.household_id, account_id=data.account_id
        )

    return BudgetTransactionBulkImportResponse(
        inserted=result.inserted,
        skipped=result.skipped,
        auto_categorized=auto_categorized,
    )


# ── Auto-categorize ───────────────────────────────────────────────────────────

@router.post("/auto-categorize", response_model=AutoCategorizeResponse)
async def auto_categorize(
    account_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AutoCategorizeResponse:
    updated = await service.auto_categorize_transactions(
        db, current_user.household_id, account_id=account_id
    )
    return AutoCategorizeResponse(updated=updated)


# ── File import ───────────────────────────────────────────────────────────────

@router.post("/import/detect", response_model=BudgetImportDetectResponse)
async def detect_import_file(
    file: UploadFile = File(...),
    _current_user: User = Depends(get_current_user),
) -> BudgetImportDetectResponse:
    content = await file.read()
    filename = (file.filename or "").lower()

    if filename.endswith((".ofx", ".qfx")):
        try:
            result = parse_ofx(content)
            dates = [t.date for t in result.transactions]
            return BudgetImportDetectResponse(
                format="ofx",
                estimated_transaction_count=len(result.transactions),
                date_range_start=min(dates) if dates else None,
                date_range_end=max(dates) if dates else None,
                errors=result.errors,
            )
        except OFXParseError as exc:
            raise HTTPException(status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    if filename.endswith((".csv", ".txt")):
        detect = detect_csv_columns(content)
        mapping = None
        if detect.detected_mapping:
            m = detect.detected_mapping
            mapping = CSVColumnMapping(
                date_col=m.date_col,
                description_col=m.description_col,
                amount_col=m.amount_col,
                debit_col=m.debit_col,
                credit_col=m.credit_col,
                merchant_col=m.merchant_col,
            )
        return BudgetImportDetectResponse(
            format="csv",
            columns=detect.columns,
            sample_rows=detect.sample_rows,
            detected_mapping=mapping,
            mapping_confidence=detect.confidence,
            errors=detect.errors,
        )

    # Unknown extension — try OFX then CSV
    try:
        result = parse_ofx(content)
        dates = [t.date for t in result.transactions]
        return BudgetImportDetectResponse(
            format="ofx",
            estimated_transaction_count=len(result.transactions),
            date_range_start=min(dates) if dates else None,
            date_range_end=max(dates) if dates else None,
            errors=result.errors,
        )
    except OFXParseError:
        pass

    detect = detect_csv_columns(content)
    mapping = None
    if detect.detected_mapping:
        m = detect.detected_mapping
        mapping = CSVColumnMapping(
            date_col=m.date_col,
            description_col=m.description_col,
            amount_col=m.amount_col,
            debit_col=m.debit_col,
            credit_col=m.credit_col,
            merchant_col=m.merchant_col,
        )
    if detect.columns:
        return BudgetImportDetectResponse(
            format="csv",
            columns=detect.columns,
            sample_rows=detect.sample_rows,
            detected_mapping=mapping,
            mapping_confidence=detect.confidence,
            errors=detect.errors,
        )

    return BudgetImportDetectResponse(format="unknown", errors=["Could not detect file format."])


@router.post("/import", response_model=BudgetFileImportResponse, status_code=http_status.HTTP_201_CREATED)
async def import_file(
    account_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    column_mapping: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetFileImportResponse:
    content = await file.read()
    filename = (file.filename or "").lower()
    parse_errors: list[str] = []

    from life_dashboard.domains.budget.schemas import BudgetTransactionCreate

    parsed_txns: list = []
    import_source: str

    is_ofx = filename.endswith((".ofx", ".qfx"))
    is_csv = filename.endswith((".csv", ".txt"))

    if not is_ofx and not is_csv:
        try:
            parse_ofx(content[:512])
            is_ofx = True
        except OFXParseError:
            is_csv = True

    if is_ofx:
        import_source = "ofx"
        try:
            result = parse_ofx(content)
        except OFXParseError as exc:
            raise HTTPException(status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        parse_errors.extend(result.errors)
        parsed_txns = result.transactions
    else:
        import_source = "csv"
        if column_mapping:
            try:
                raw = json.loads(column_mapping)
                mapping_data = CSVColumnMapping(**raw)
            except Exception as exc:
                raise HTTPException(
                    status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid column_mapping JSON: {exc}",
                )
            csv_mapping = _CSVColumnMapping(
                date_col=mapping_data.date_col,
                description_col=mapping_data.description_col,
                amount_col=mapping_data.amount_col,
                debit_col=mapping_data.debit_col,
                credit_col=mapping_data.credit_col,
                merchant_col=mapping_data.merchant_col,
            )
        else:
            detect = detect_csv_columns(content)
            if detect.detected_mapping is None:
                raise HTTPException(
                    status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Could not auto-detect CSV columns. Please provide a column_mapping.",
                )
            csv_mapping = detect.detected_mapping

        csv_result = parse_csv(content, csv_mapping)
        parse_errors.extend(csv_result.errors)
        parsed_txns = csv_result.transactions

    to_insert = [
        BudgetTransactionCreate(
            account_id=account_id,
            date=t.date,
            amount=t.amount,
            description=t.description,
            external_id=t.external_id,
            import_source=import_source,  # type: ignore[arg-type]
        )
        for t in parsed_txns
    ]

    if not to_insert:
        return BudgetFileImportResponse(inserted=0, skipped=0, parse_errors=parse_errors)

    try:
        bulk_result = await service.bulk_import_transactions(
            db,
            current_user.household_id,
            account_id,
            import_source,
            to_insert,
        )
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc))

    auto_categorized = 0
    if bulk_result.inserted > 0:
        auto_categorized = await service.auto_categorize_transactions(
            db, current_user.household_id, account_id=account_id
        )

    return BudgetFileImportResponse(
        inserted=bulk_result.inserted,
        skipped=bulk_result.skipped,
        auto_categorized=auto_categorized,
        parse_errors=parse_errors,
    )


# ── Income forecasting (budget-020) ──────────────────────────────────────────

@router.get("/income-forecast", response_model=IncomeForecastResponse)
async def get_income_forecast(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    profile_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> IncomeForecastResponse:
    """
    Project recurring income for the given month and compare against
    category budget targets. Returns per-source breakdown plus
    left_to_allocate = projected_income - total_targets.
    """
    return await service.get_income_forecast(
        db, current_user.household_id, current_user.id,
        year=year, month=month, profile_id=profile_id,
    )


# ── Recurring transactions ────────────────────────────────────────────────────

@router.post("/recurring/generate", response_model=RecurringGenerateResponse)
async def generate_recurring(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Idempotent: generates missing recurring-transaction instances for the given
    year/month from all active recurring templates in the household.
    Safe to call multiple times; already-existing instances are skipped.
    """
    return await service.ensure_recurring_for_month(
        db, current_user.household_id, year, month
    )


# ── Spending trends ────────────────────────────────────────────────────────────

@router.get("/trends", response_model=BudgetTrendsResponse)
async def get_spending_trends(
    months: int = Query(default=6, ge=1, le=24),
    profile_id: uuid.UUID | None = Query(default=None),
    account_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetTrendsResponse:
    """
    Return monthly income / expense / budget totals for the last N months.
    Ordered oldest → newest. Used by the trends chart on the budget page.
    """
    month_data = await service.get_spending_trends(
        db, current_user.household_id, current_user.id,
        months=months,
        profile_id=profile_id,
        account_id=account_id,
    )
    from life_dashboard.domains.budget.schemas import BudgetTrendMonth
    return BudgetTrendsResponse(
        months=[BudgetTrendMonth(**m) for m in month_data]
    )


# ── Teller bank sync ──────────────────────────────────────────────────────────

@router.get("/teller/config", response_model=TellerConfigResponse)
async def get_teller_config(
    _current_user: User = Depends(get_current_user),
) -> TellerConfigResponse:
    """
    Return public Teller configuration so the frontend knows whether bank
    sync is available and how to initialise the Teller Connect widget.
    The access token is never included in this response.
    """
    return service.get_teller_config()


@router.post(
    "/teller/connect",
    response_model=list[BudgetAccountResponse],
    status_code=http_status.HTTP_201_CREATED,
)
async def connect_teller_enrollment(
    data: TellerConnectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BudgetAccountResponse]:
    """
    Process a successful Teller Connect callback.

    The frontend calls this after the TellerConnect.setup() onSuccess fires,
    passing the access token, enrollment ID, and institution name.  The API
    calls Teller GET /accounts to discover all bank accounts in the enrollment
    and creates (or re-authenticates) a BudgetAccount for each.

    Returns the list of created/updated BudgetAccount objects.
    """
    try:
        return await service.connect_teller_enrollment(
            db, current_user.household_id, current_user.id, data
        )
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post(
    "/accounts/{account_id}/teller/sync",
    response_model=TellerSyncResult,
)
async def sync_teller_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TellerSyncResult:
    """
    Poll Teller for new transactions on a single linked account and import them.
    Uses the stored cursor so only transactions newer than the last sync are fetched.
    """
    account = await service.get_account(db, account_id, current_user.household_id)
    if account is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Account not found")
    if not account.teller_account_id:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="This account is not linked to Teller.",
        )
    try:
        return await service.sync_teller_account(db, account)
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/teller/sync-all", response_model=TellerSyncAllResult)
async def sync_all_teller_accounts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TellerSyncAllResult:
    """
    Sync all Teller-linked accounts in the household in sequence.
    Individual account failures are logged and skipped — the response always
    returns results for the accounts that succeeded.
    """
    return await service.sync_all_teller_accounts(db, current_user.household_id)


@router.delete(
    "/accounts/{account_id}/teller",
    status_code=http_status.HTTP_204_NO_CONTENT,
)
async def unlink_teller_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Remove the Teller connection from an account.
    Clears all teller_* fields; existing imported transactions are preserved.
    """
    account = await service.get_account(db, account_id, current_user.household_id)
    if account is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Account not found")

    account.teller_enrollment_id = None
    account.teller_access_token = None
    account.teller_account_id = None
    account.teller_institution_name = None
    account.teller_last_synced_at = None
    account.teller_cursor = None
    from datetime import datetime, timezone
    account.updated_at = datetime.now(timezone.utc)
    await db.commit()


@router.post(
    "/accounts/{account_id}/teller/reset-cursor",
    status_code=204,
)
async def reset_teller_cursor(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Clear the teller_cursor so the next sync re-fetches the full transaction
    history from scratch.  Useful after the initial connect when the cursor
    was set before full pagination was available.
    """
    account = await service.get_account(db, account_id, current_user.household_id)
    if not account or not account.teller_account_id:
        raise HTTPException(status_code=404, detail="Teller-linked account not found")
    from datetime import datetime, timezone
    account.teller_cursor = None
    account.updated_at = datetime.now(timezone.utc)
    await db.commit()
