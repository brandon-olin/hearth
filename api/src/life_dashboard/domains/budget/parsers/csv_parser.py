"""
CSV bank statement parser.

Two responsibilities:

  1. detect_csv_columns(content) — heuristically identifies which CSV columns
     map to date / amount / description and returns a ColumnMapping suggestion
     along with the column headers and sample rows for the UI to display.

  2. parse_csv(content, mapping) — applies a confirmed ColumnMapping to the
     full CSV and returns a list of ParsedTransaction objects.

Amount formats handled:
  - Single signed column:  "-45.67"  or  "45.67"
  - Separate debit/credit:  debit="45.67", credit=""  →  amount = -45.67
                            debit="",      credit="100" → amount = +100.00
  - Parenthesised negatives: "(45.67)" → -45.67
  - Commas as thousands separators: "1,234.56"

Detection strategy:
  Header-name heuristics run first. If no amount column is found by name, a
  data-driven pass scans column values: any column with ≥70 % numeric values
  and at least one negative value is promoted as the signed amount column.
  This handles banks that name their amount column "Credit/Debit", "Net",
  "Transaction", or other non-standard labels.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import NamedTuple


# ── Shared output type (same as OFX parser) ───────────────────────────────────

@dataclass
class ParsedTransaction:
    date: date
    amount: float
    description: str
    external_id: str | None = None
    transaction_type: str | None = None


# ── Column mapping ─────────────────────────────────────────────────────────────

class ColumnMapping(NamedTuple):
    """
    Maps CSV column header names to transaction fields.
    Exactly one of (amount_col) or (debit_col + credit_col) must be set.
    """
    date_col: str
    description_col: str
    amount_col: str | None = None      # signed single column
    debit_col: str | None = None       # outflow (positive value = money out)
    credit_col: str | None = None      # inflow  (positive value = money in)
    merchant_col: str | None = None    # optional second description field


@dataclass
class CSVDetectResult:
    columns: list[str]
    sample_rows: list[list[str]]       # up to 5 rows, values as strings
    detected_mapping: ColumnMapping | None
    confidence: float                  # 0.0–1.0
    errors: list[str] = field(default_factory=list)


@dataclass
class CSVParseResult:
    transactions: list[ParsedTransaction] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ── Heuristics ────────────────────────────────────────────────────────────────

# Column name patterns — ordered from most to least specific
_DATE_PATTERNS = [
    "transaction date", "trans date", "trans. date", "posting date",
    "post date", "posted date", "value date", "settlement date", "date",
]
_AMOUNT_PATTERNS = [
    "transaction amount", "trans amount", "amount (usd)", "amount (cad)",
    "amount (gbp)", "amount (eur)", "amount", "net amount", "net",
    "credit/debit", "debit/credit", "total amount", "total", "amt",
    "transaction value", "value",
]
_DEBIT_PATTERNS = [
    "debit amount", "withdrawal amount", "debit", "withdrawal", "withdrawals",
]
_CREDIT_PATTERNS = [
    "credit amount", "deposit amount", "credit", "deposit", "deposits",
]
_DESCRIPTION_PATTERNS = [
    "transaction description", "description", "details", "narrative",
    "payee", "merchant", "memo", "name", "particulars", "reference",
]
_MERCHANT_PATTERNS = [
    "merchant name", "merchant", "payee name", "payee",
]


def _best_match(headers_lower: list[str], patterns: list[str]) -> str | None:
    """Return the first header that matches any pattern, preferring earlier patterns."""
    for pattern in patterns:
        for h in headers_lower:
            if h == pattern or h.startswith(pattern) or pattern in h:
                return h
    return None


def _score_mapping(mapping: ColumnMapping) -> float:
    """Rough confidence: 1.0 if all required fields found, less if partial."""
    score = 0.0
    if mapping.date_col:
        score += 0.4
    if mapping.description_col:
        score += 0.3
    if mapping.amount_col or (mapping.debit_col and mapping.credit_col):
        score += 0.3
    elif mapping.debit_col or mapping.credit_col:
        score += 0.15  # only one of debit/credit found
    return score


def _find_signed_amount_column(
    headers: list[str],
    rows: list[dict],
    exclude: set[str],
) -> str | None:
    """
    Data-driven fallback: scan each column's values looking for one that is
    ≥70% numeric AND contains at least one negative value.  The first such
    column that isn't already claimed as date/description is returned.

    This catches amount columns named "Credit/Debit", "Net", "Transaction",
    "Balance movement", etc. that don't match any header-name heuristic.
    """
    for header in headers:
        if header in exclude:
            continue
        values = [row.get(header, "").strip() for row in rows if row.get(header, "").strip()]
        if not values:
            continue
        parsed = [_parse_amount(v) for v in values]
        numeric = [v for v in parsed if v is not None]
        if len(numeric) < max(1, len(values) * 0.7):
            continue  # fewer than 70 % of cells are numeric
        if any(v < 0 for v in numeric):
            return header  # has at least one negative → signed amount column
    return None


def detect_csv_columns(content: bytes | str) -> CSVDetectResult:
    """
    Read the CSV and return column headers, sample rows, and a best-guess
    ColumnMapping. Always succeeds — errors are non-fatal.
    """
    text = _decode(content)
    reader, rows = _read_csv(text)
    headers = reader.fieldnames or []

    if not headers:
        return CSVDetectResult(
            columns=[], sample_rows=[], detected_mapping=None, confidence=0.0,
            errors=["No column headers found in CSV."],
        )

    headers_lower = [h.strip().lower() for h in headers]
    original = {h.strip().lower(): h.strip() for h in headers}

    def orig(key: str | None) -> str | None:
        return original.get(key) if key else None

    date_key = _best_match(headers_lower, _DATE_PATTERNS)
    desc_key = _best_match(headers_lower, _DESCRIPTION_PATTERNS)
    amount_key = _best_match(headers_lower, _AMOUNT_PATTERNS)
    debit_key = _best_match(headers_lower, _DEBIT_PATTERNS)
    credit_key = _best_match(headers_lower, _CREDIT_PATTERNS)
    merchant_key = _best_match(headers_lower, _MERCHANT_PATTERNS)
    # Don't use the same column for merchant and description
    if merchant_key == desc_key:
        merchant_key = None

    # If debit and credit heuristics resolved to the *same* column (e.g. a
    # column literally named "Credit/Debit"), treat it as a signed amount
    # column rather than separate debit/credit — the minus sign carries sign.
    if debit_key and credit_key and debit_key == credit_key:
        amount_key = amount_key or debit_key
        debit_key = None
        credit_key = None

    # If only a debit column was found (no matching credit column), check
    # whether its values are actually signed (some negative).  Banks sometimes
    # export a single column named "Debit", "Withdrawal", etc. that contains
    # both debits (positive) and credits (negative).  Forcing -abs() on those
    # would flip the sign of income rows, so we reclassify it as amount_col.
    if debit_key and not credit_key:
        debit_orig = original.get(debit_key)
        if debit_orig:
            debit_sample = [
                _parse_amount(str(row.get(debit_orig, "")))
                for row in rows[:20]
            ]
            if any(v is not None and v < 0 for v in debit_sample):
                amount_key = amount_key or debit_key
                debit_key = None

    # Prefer separate debit/credit if two *distinct* columns found.
    if debit_key and credit_key:
        mapping = ColumnMapping(
            date_col=orig(date_key) or headers[0],
            description_col=orig(desc_key) or headers[min(1, len(headers) - 1)],
            debit_col=orig(debit_key),
            credit_col=orig(credit_key),
            merchant_col=orig(merchant_key),
        )
    else:
        # If the header scan didn't find an amount column, try a data-driven
        # pass: look for a column whose values are ≥70% numeric with at least
        # one negative (i.e. a signed credit/debit column).
        resolved_amount = orig(amount_key)
        if not resolved_amount:
            claimed = {
                orig(date_key) or headers[0],
                orig(desc_key) or headers[min(1, len(headers) - 1)],
            }
            if orig(merchant_key):
                claimed.add(orig(merchant_key))
            if orig(debit_key):
                claimed.add(orig(debit_key))
            if orig(credit_key):
                claimed.add(orig(credit_key))
            resolved_amount = _find_signed_amount_column(
                [h.strip() for h in headers], rows, claimed  # type: ignore[arg-type]
            )

        mapping = ColumnMapping(
            date_col=orig(date_key) or headers[0],
            description_col=orig(desc_key) or headers[min(1, len(headers) - 1)],
            amount_col=resolved_amount,
            debit_col=orig(debit_key),
            credit_col=orig(credit_key),
            merchant_col=orig(merchant_key),
        )

    sample = [[str(row.get(h, "")) for h in headers] for row in rows[:5]]

    return CSVDetectResult(
        columns=[h.strip() for h in headers],
        sample_rows=sample,
        detected_mapping=mapping,
        confidence=_score_mapping(mapping),
    )


# ── Amount parsing ────────────────────────────────────────────────────────────

def _parse_amount(raw: str) -> float | None:
    """Parse a variety of formatted amount strings to a float."""
    s = raw.strip()
    if not s:
        return None
    negative = s.startswith("-") or (s.startswith("(") and s.endswith(")"))
    # Remove currency symbols, spaces, commas, parens
    s = re.sub(r"[^\d.]", "", s)
    if not s:
        return None
    try:
        val = float(s)
        return -val if negative else val
    except ValueError:
        return None


# ── Date parsing ──────────────────────────────────────────────────────────────

_DATE_FORMATS = [
    "%m/%d/%Y", "%m/%d/%y",
    "%Y-%m-%d",
    "%d/%m/%Y", "%d/%m/%y",
    "%m-%d-%Y", "%m-%d-%y",
    "%d-%m-%Y",
    "%b %d, %Y", "%B %d, %Y",
    "%Y%m%d",
]


def _parse_date(raw: str) -> date | None:
    s = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# ── CSV parsing ───────────────────────────────────────────────────────────────

def parse_csv(content: bytes | str, mapping: ColumnMapping) -> CSVParseResult:
    """
    Parse a CSV file using the provided column mapping and return transactions.
    Non-fatal row errors are collected in result.errors.
    """
    result = CSVParseResult()
    text = _decode(content)
    reader, rows = _read_csv(text)

    for i, row in enumerate(rows, start=2):  # start=2 because row 1 = headers
        # Date
        raw_date = row.get(mapping.date_col, "").strip()
        txn_date = _parse_date(raw_date)
        if txn_date is None:
            result.errors.append(f"Row {i}: skipped — unparseable date {raw_date!r}")
            continue

        # Amount
        if mapping.amount_col:
            raw_amt = row.get(mapping.amount_col, "")
            amount = _parse_amount(raw_amt)
            if amount is None:
                result.errors.append(f"Row {i}: skipped — unparseable amount {raw_amt!r}")
                continue
        elif mapping.debit_col or mapping.credit_col:
            debit_raw = row.get(mapping.debit_col or "", "").strip()
            credit_raw = row.get(mapping.credit_col or "", "").strip()
            debit = _parse_amount(debit_raw) if debit_raw else None
            credit = _parse_amount(credit_raw) if credit_raw else None
            if debit is not None and debit != 0:
                amount = -abs(debit)   # debit = money out = negative
            elif credit is not None and credit != 0:
                amount = abs(credit)   # credit = money in = positive
            else:
                result.errors.append(f"Row {i}: skipped — no debit or credit value")
                continue
        else:
            result.errors.append(f"Row {i}: skipped — no amount column configured")
            continue

        # Description
        description = row.get(mapping.description_col, "").strip()
        if not description:
            description = "Unknown"

        # Optional merchant name
        merchant = row.get(mapping.merchant_col or "", "").strip() if mapping.merchant_col else None
        if merchant == description:
            merchant = None

        result.transactions.append(ParsedTransaction(
            date=txn_date,
            amount=amount,
            description=description,
        ))

    return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _decode(content: bytes | str) -> str:
    if isinstance(content, str):
        return content
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("Could not decode CSV file.")


def _read_csv(text: str) -> tuple[csv.DictReader, list[dict]]:
    """Sniff delimiter and return a DictReader + all rows pre-read."""
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t|;")
    except csv.Error:
        dialect = csv.excel  # type: ignore[assignment]
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = list(reader)
    # Reset reader so callers can re-use fieldnames
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    list(reader)  # consume to populate fieldnames
    return reader, rows
