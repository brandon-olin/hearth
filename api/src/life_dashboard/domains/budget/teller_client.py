"""
Teller API client — async, mTLS-authenticated.

Teller uses mutual TLS for all API calls.  The certificate and private key
are the files downloaded from the Teller dashboard (certificate.pem +
private_key.pem).  Each bank connection has its own access_token, which is
sent as the Basic-auth username with an empty password.

Usage:
    client = TellerClient()
    if client.is_configured():
        accounts = await client.get_accounts(access_token)
        txns = await client.get_transactions(access_token, teller_account_id)

Teller transaction amount convention:
    Teller returns amounts as strings with a leading "-" for debits.
    e.g. "-45.99" (expense), "2500.00" (income/deposit).
    We negate the sign convention to match the Hearth internal convention:
        negative = expense, positive = income — so Teller "-45.99" → -45.99 ✓
        and Teller "2500.00" → +2500.00 ✓  (no change needed for income)
    In practice: float(teller_amount) maps directly to our convention.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx

from life_dashboard.core.settings import settings

logger = logging.getLogger(__name__)

TELLER_BASE_URL = "https://api.teller.io"


@dataclass
class TellerAccount:
    id: str
    name: str
    type: str           # "depository", "credit", "investment", "loan"
    subtype: str        # "checking", "savings", "credit_card", etc.
    institution_name: str
    currency: str
    last_four: str | None
    status: str         # "open", "closed"
    enrollment_id: str


@dataclass
class TellerBalance:
    account_id: str
    ledger: float | None     # Posted/settled balance
    available: float | None  # Available balance (may differ for credit/pending)


@dataclass
class TellerTransaction:
    id: str
    account_id: str
    date: date
    description: str
    amount: float       # negative = expense, positive = income (matches Hearth convention)
    status: str         # "posted" | "pending"
    merchant_name: str | None = None
    teller_category: str | None = None
    running_balance: float | None = None


def _teller_account_type(teller_type: str, teller_subtype: str) -> str:
    """Map Teller account type/subtype to Hearth account_type enum values."""
    subtype_map = {
        "checking": "checking",
        "savings": "savings",
        "credit_card": "credit_card",
        "money_market": "savings",
        "cd": "savings",
        "brokerage": "investment",
        "traditional_ira": "investment",
        "roth_ira": "investment",
        "401k": "investment",
        "student": "loan",
        "personal": "loan",
        "mortgage": "loan",
        "home_equity": "loan",
        "auto": "loan",
    }
    if teller_subtype in subtype_map:
        return subtype_map[teller_subtype]
    type_map = {
        "depository": "checking",
        "credit": "credit_card",
        "investment": "investment",
        "loan": "loan",
    }
    return type_map.get(teller_type, "other")


class TellerClient:
    """
    Async Teller API client.  Instantiate once and reuse — httpx.AsyncClient
    is created per-call to allow different access tokens per request.
    The mTLS cert/key are read from settings on every call so a reload
    (e.g. cert rotation) is picked up without restarting the server.
    """

    def is_configured(self) -> bool:
        """Return True if cert, key, and app_id are all set in settings."""
        return bool(
            settings.teller_app_id
            and settings.teller_cert_path
            and settings.teller_key_path
        )

    def _client(self, access_token: str) -> httpx.AsyncClient:
        """Build an httpx client with mTLS and Basic auth for one access token."""
        return httpx.AsyncClient(
            base_url=TELLER_BASE_URL,
            cert=(settings.teller_cert_path, settings.teller_key_path),
            auth=(access_token, ""),   # Basic auth: token as username, empty password
            timeout=30.0,
        )

    async def get_accounts(self, access_token: str) -> list[TellerAccount]:
        """
        List all accounts accessible with the given access token.
        Returns an empty list on auth errors (enrollment revoked / disconnected).
        Raises httpx.HTTPError for unexpected server errors.
        """
        async with self._client(access_token) as client:
            resp = await client.get("/accounts")

        if resp.status_code == 401:
            logger.warning("Teller: access token unauthorised — enrollment may be disconnected")
            return []
        resp.raise_for_status()

        return [self._parse_account(a) for a in resp.json()]

    async def get_transactions(
        self,
        access_token: str,
        teller_account_id: str,
        from_id: str | None = None,
        count: int = 100,
    ) -> list[TellerTransaction]:
        """
        Fetch one page of transactions for one account.

        from_id: Teller cursor.  Semantics depend on direction:
                 - Incremental sync (newest cursor stored): returns transactions
                   *newer* than this ID.
                 - Historical pagination (oldest ID from previous page): returns
                   transactions *older* than this ID (next page back in time).
        count:   max transactions per page (Teller max = 100).

        Returns newest-first.  Returns an empty list on 401/403.
        """
        params: dict[str, Any] = {"count": count}
        if from_id:
            params["from_id"] = from_id

        async with self._client(access_token) as client:
            resp = await client.get(
                f"/accounts/{teller_account_id}/transactions",
                params=params,
            )

        if resp.status_code in (401, 403):
            logger.warning(
                "Teller: %s fetching transactions for account %s",
                resp.status_code,
                teller_account_id,
            )
            return []
        resp.raise_for_status()

        return [self._parse_transaction(t) for t in resp.json()]

    async def get_balance(
        self,
        access_token: str,
        teller_account_id: str,
    ) -> TellerBalance | None:
        """
        Fetch the current balance for one account.

        Teller returns { "account_id": "...", "ledger": "1234.56", "available": "1200.00" }.
        Amounts are strings.  Returns None on auth errors.
        """
        async with self._client(access_token) as client:
            resp = await client.get(f"/accounts/{teller_account_id}/balances")

        if resp.status_code in (401, 403):
            logger.warning(
                "Teller: %s fetching balance for account %s",
                resp.status_code,
                teller_account_id,
            )
            return None
        resp.raise_for_status()

        raw = resp.json()
        def _parse_amount(val: Any) -> float | None:
            try:
                return float(val) if val is not None else None
            except (ValueError, TypeError):
                return None

        return TellerBalance(
            account_id=raw.get("account_id", teller_account_id),
            ledger=_parse_amount(raw.get("ledger")),
            available=_parse_amount(raw.get("available")),
        )

    async def get_all_transactions(
        self,
        access_token: str,
        teller_account_id: str,
    ) -> list[TellerTransaction]:
        """
        Fetch all available transaction history for an account.

        Teller's from_id parameter is forward-only (returns transactions *newer*
        than the given ID) and there is no backward pagination cursor.  Each
        call returns at most 100 transactions.  This means Teller caps available
        history at 100 transactions per account — there is no way to fetch
        older history beyond what a single max-count call returns.

        This method exists as a named alias so call sites are explicit about
        intent (full initial sync vs. incremental cursor sync).
        """
        return await self.get_transactions(
            access_token, teller_account_id, from_id=None, count=100
        )

    # ── Parsers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_account(raw: dict[str, Any]) -> TellerAccount:
        institution = raw.get("institution") or {}
        return TellerAccount(
            id=raw["id"],
            name=raw.get("name", "Unknown Account"),
            type=raw.get("type", "depository"),
            subtype=raw.get("subtype", "checking"),
            institution_name=institution.get("name", "Unknown Bank"),
            currency=raw.get("currency", "USD"),
            last_four=raw.get("last_four"),
            status=raw.get("status", "open"),
            enrollment_id=raw.get("enrollment_id", ""),
        )

    @staticmethod
    def _parse_transaction(raw: dict[str, Any]) -> TellerTransaction:
        details = raw.get("details") or {}
        counterparty = details.get("counterparty") or {}

        # Teller amounts are strings; negative = debit, positive = credit.
        # This matches Hearth's convention directly.
        try:
            amount = float(raw["amount"])
        except (KeyError, ValueError, TypeError):
            amount = 0.0

        # Parse date — Teller returns "YYYY-MM-DD"
        try:
            txn_date = date.fromisoformat(raw["date"])
        except (KeyError, ValueError):
            txn_date = date.today()

        merchant_name = counterparty.get("name") or None

        return TellerTransaction(
            id=raw["id"],
            account_id=raw.get("account_id", ""),
            date=txn_date,
            description=raw.get("description", ""),
            amount=amount,
            status=raw.get("status", "posted"),
            merchant_name=merchant_name,
            teller_category=details.get("category"),
            running_balance=float(raw["running_balance"]) if raw.get("running_balance") else None,
        )


# Module-level singleton — import and use directly in service.py
teller_client = TellerClient()
