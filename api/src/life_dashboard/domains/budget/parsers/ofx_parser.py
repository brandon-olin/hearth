"""
OFX / QFX file parser.

Handles both formats that banks actually produce:

  Old-style SGML OFX (most common — Chase, BofA, Citi, Wells Fargo QFX):
    <TAG>value  (no closing tags for leaf nodes)
    Tags are case-insensitive, header block followed by <OFX> body.

  OFX 2.x XML (less common — some credit unions, newer exports):
    Proper XML with closing tags, starts with <?OFX ... ?>

The parser extracts transactions from <STMTTRN> / <INVBANKTRAN> blocks
and returns them as ParsedTransaction objects ready for the service layer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone


# ── Output type ───────────────────────────────────────────────────────────────

@dataclass
class ParsedTransaction:
    date: date
    amount: float          # negative = expense, positive = income/refund
    description: str       # raw NAME/MEMO from file
    external_id: str | None = None   # FITID
    transaction_type: str | None = None  # DEBIT, CREDIT, etc.


@dataclass
class OFXParseResult:
    transactions: list[ParsedTransaction] = field(default_factory=list)
    date_start: date | None = None
    date_end: date | None = None
    errors: list[str] = field(default_factory=list)


# ── Date parsing ──────────────────────────────────────────────────────────────

def _parse_ofx_date(raw: str) -> date | None:
    """
    OFX date formats:
      YYYYMMDD
      YYYYMMDDHHMMSS
      YYYYMMDDHHMMSS.xxx
      YYYYMMDDHHMMSS.xxx[-N:TZ]
    We only need the calendar date.
    """
    raw = raw.strip().split("[")[0].split(".")[0]  # strip timezone + fractional
    raw = raw.strip()
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(raw[:len(fmt.replace("%", "XX").replace("X", ""))], fmt).date()
        except ValueError:
            continue
    # Fallback: try first 8 digits
    if len(raw) >= 8 and raw[:8].isdigit():
        try:
            return datetime.strptime(raw[:8], "%Y%m%d").date()
        except ValueError:
            pass
    return None


# ── SGML parser ───────────────────────────────────────────────────────────────

# Matches <TAG>value (SGML leaf) or <TAG> (SGML aggregate open tag)
_SGML_TAG_RE = re.compile(r"<([^/>\s]+)>([^<]*)", re.DOTALL)
_SGML_CLOSE_RE = re.compile(r"</([^>]+)>")


def _parse_sgml(content: str) -> OFXParseResult:
    result = OFXParseResult()

    # Collect all tag/value pairs
    tags: list[tuple[str, str]] = []
    for m in _SGML_TAG_RE.finditer(content):
        tag = m.group(1).upper().strip()
        value = m.group(2).strip()
        tags.append((tag, value))

    # Walk tags looking for STMTTRN / INVBANKTRAN blocks
    i = 0
    while i < len(tags):
        tag, value = tags[i]

        if tag in ("DTSTART",) and value:
            d = _parse_ofx_date(value)
            if d and result.date_start is None:
                result.date_start = d

        elif tag in ("DTEND",) and value:
            d = _parse_ofx_date(value)
            if d and result.date_end is None:
                result.date_end = d

        elif tag == "STMTTRN" or tag == "INVBANKTRAN":
            # Start of a transaction block — consume until next STMTTRN/INVBANKTRAN
            # or until a closing aggregate tag
            txn_tags: dict[str, str] = {}
            i += 1
            while i < len(tags):
                t, v = tags[i]
                if t in ("STMTTRN", "INVBANKTRAN"):
                    # Next transaction starts — don't advance i (outer loop will)
                    i -= 1
                    break
                txn_tags[t] = v
                i += 1
            txn = _build_transaction(txn_tags, result.errors)
            if txn:
                result.transactions.append(txn)

        i += 1

    return result


def _build_transaction(tags: dict[str, str], errors: list[str]) -> ParsedTransaction | None:
    # Date: prefer DTPOSTED, fall back to DTUSER
    raw_date = tags.get("DTPOSTED") or tags.get("DTUSER") or tags.get("DTTRADE") or ""
    txn_date = _parse_ofx_date(raw_date) if raw_date else None
    if txn_date is None:
        errors.append(f"Skipped transaction with unparseable date: {raw_date!r}")
        return None

    raw_amount = tags.get("TRNAMT") or tags.get("UNITS") or ""
    try:
        amount = float(raw_amount.replace(",", "").strip())
    except ValueError:
        errors.append(f"Skipped transaction with unparseable amount: {raw_amount!r}")
        return None

    # Description: prefer NAME + MEMO combined, fall back to either alone
    name = tags.get("NAME", "").strip()
    memo = tags.get("MEMO", "").strip()
    if name and memo and name.lower() not in memo.lower():
        description = f"{name} — {memo}"
    else:
        description = name or memo or "Unknown"

    return ParsedTransaction(
        date=txn_date,
        amount=amount,
        description=description,
        external_id=tags.get("FITID", "").strip() or None,
        transaction_type=tags.get("TRNTYPE", "").strip() or None,
    )


# ── XML parser ────────────────────────────────────────────────────────────────

def _parse_xml(content: str) -> OFXParseResult:
    """
    OFX 2.x is proper XML. Use a lightweight regex-based approach to avoid
    requiring lxml, and because OFX XML is well-structured enough for this.
    """
    result = OFXParseResult()

    def _text(tag: str, block: str) -> str | None:
        m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else None

    # Date range
    for block_tag in ("BANKTRANLIST", "INVTRANLIST"):
        block_m = re.search(
            rf"<{block_tag}>(.*?)</{block_tag}>", content, re.DOTALL | re.IGNORECASE
        )
        if block_m:
            block = block_m.group(1)
            start_raw = _text("DTSTART", block)
            end_raw = _text("DTEND", block)
            if start_raw:
                result.date_start = _parse_ofx_date(start_raw)
            if end_raw:
                result.date_end = _parse_ofx_date(end_raw)

    # Transactions
    for block_tag in ("STMTTRN", "INVBANKTRAN"):
        for m in re.finditer(
            rf"<{block_tag}>(.*?)</{block_tag}>", content, re.DOTALL | re.IGNORECASE
        ):
            block = m.group(1)
            tags: dict[str, str] = {}
            for leaf in re.finditer(r"<(\w+)>(.*?)</\1>", block, re.DOTALL | re.IGNORECASE):
                tags[leaf.group(1).upper()] = leaf.group(2).strip()
            txn = _build_transaction(tags, result.errors)
            if txn:
                result.transactions.append(txn)

    return result


# ── Public entry point ────────────────────────────────────────────────────────

class OFXParseError(Exception):
    """Raised when a file cannot be identified as OFX/QFX at all."""


def parse_ofx(content: bytes | str) -> OFXParseResult:
    """
    Parse an OFX or QFX file (as raw bytes or decoded string) and return
    an OFXParseResult with the extracted transactions and any non-fatal errors.

    Raises OFXParseError if the file does not appear to be OFX/QFX.
    """
    if isinstance(content, bytes):
        # OFX files are often Latin-1 or UTF-8 — try both
        for enc in ("utf-8", "latin-1", "cp1252"):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise OFXParseError("Could not decode file — expected UTF-8 or Latin-1 encoding.")
    else:
        text = content

    # Detect format
    stripped = text.lstrip()
    if not (
        "<OFX>" in text.upper()
        or "OFXHEADER:" in text.upper()
        or stripped.startswith("<?OFX")
        or stripped.startswith("<?xml")
    ):
        raise OFXParseError(
            "File does not appear to be OFX/QFX — no OFX header found."
        )

    # OFX 2.x: starts with <?OFX or <?xml and uses proper closing tags
    if stripped.startswith("<?OFX") or stripped.startswith("<?xml"):
        return _parse_xml(text)

    # Old-style SGML: may have a header block before <OFX>
    # Strip the header (everything before the first <OFX>)
    ofx_start = text.upper().find("<OFX>")
    body = text[ofx_start:] if ofx_start >= 0 else text
    return _parse_sgml(body)
