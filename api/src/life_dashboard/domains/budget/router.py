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
    AutoCategorizeResponse,
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
    BudgetTransactionBulkImport,
    BudgetTransactionBulkImportResponse,
    CSVColumnMapping,
    BudgetImportDetectResponse,
    BudgetFileImportResponse,
)
from life_dashboard.domains.budget import service

router = APIRouter(prefix="/budget", tags=["budget"])


# ── Accounts ──────────────────────────────────────────────────────────────────

@router.get("/accounts", response_model=list[BudgetAccountResponse])
async def list_accounts(
    include_archived: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BudgetAccountResponse]:
    return await service.list_accounts(
        db, current_user.household_id, current_user.id,
        include_archived=include_archived,
    )


@router.post("/accounts", response_model=BudgetAccountResponse, status_code=http_status.HTTP_201_CREATED)
async def create_account(
    data: BudgetAccountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetAccountResponse:
    return await service.create_account(db, current_user.household_id, current_user.id, data)


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


# ── Categories ────────────────────────────────────────────────────────────────

@router.get("/categories", response_model=list[BudgetCategoryResponse])
async def list_categories(
    include_archived: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BudgetCategoryResponse]:
    return await service.list_categories(
        db, current_user.household_id,
        include_archived=include_archived,
    )


@router.post("/categories", response_model=BudgetCategoryResponse, status_code=http_status.HTTP_201_CREATED)
async def create_category(
    data: BudgetCategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetCategoryResponse:
    return await service.create_category(db, current_user.household_id, data)


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


# ── Summary ───────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=BudgetSummaryResponse)
async def get_summary(
    account_id: uuid.UUID | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetSummaryResponse:
    return await service.get_summary(
        db, current_user.household_id, current_user.id,
        account_id=account_id,
        date_from=date_from,
        date_to=date_to,
    )


# ── Transactions ──────────────────────────────────────────────────────────────

@router.get("/transactions", response_model=BudgetTransactionListResponse)
async def list_transactions(
    account_id: uuid.UUID | None = Query(default=None),
    category_id: uuid.UUID | None = Query(default=None),
    scope: str | None = Query(default=None, pattern="^(personal|household)$"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    include_archived: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetTransactionListResponse:
    return await service.list_transactions(
        db, current_user.household_id, current_user.id,
        account_id=account_id,
        category_id=category_id,
        scope=scope,
        date_from=date_from,
        date_to=date_to,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
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
    scope: str | None = Query(default=None, pattern="^(personal|household)$"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """
    Download all visible transactions as a CSV file.
    Filename: hearth-budget-YYYY-MM.csv based on date_from or the current month.
    """
    csv_content = await service.export_transactions_csv(
        db, current_user.household_id, current_user.id,
        account_id=account_id,
        category_id=category_id,
        scope=scope,
        date_from=date_from,
        date_to=date_to,
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


@router.delete("/transactions", status_code=http_status.HTTP_200_OK)
async def bulk_delete_transactions(
    account_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Delete all transactions for the household, optionally filtered to one account.
    Returns { "deleted": <count> }.
    """
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
        return await service.bulk_import_transactions(
            db,
            current_user.household_id,
            data.account_id,
            data.import_source,
            data.transactions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ── Auto-categorize ───────────────────────────────────────────────────────────

@router.post("/auto-categorize", response_model=AutoCategorizeResponse)
async def auto_categorize(
    account_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AutoCategorizeResponse:
    """
    Keyword-match uncategorized transactions against category keyword lists.
    Pass account_id to restrict to a single account; omit to scan the whole household.
    Returns { "updated": <count> }.
    """
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
    """
    Upload a file and get back format detection + column info.

    For OFX/QFX: returns estimated transaction count and date range.
    For CSV: returns column headers, up to 5 sample rows, and a best-guess
    column mapping for the frontend to display/edit before confirming import.
    """
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
    """
    Import transactions from an OFX/QFX or CSV file into the given account.
    Duplicates are silently skipped (dedup by hash + external_id).

    For CSV files, supply `column_mapping` as a JSON-encoded CSVColumnMapping.
    If omitted for CSV, heuristic detection is used.
    """
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

    return BudgetFileImportResponse(
        inserted=bulk_result.inserted,
        skipped=bulk_result.skipped,
        parse_errors=parse_errors,
    )
