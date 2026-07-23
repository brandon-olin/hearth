# 016 — Bank sync: Teller shutdown → provider abstraction (Quiltt)

Status: PROPOSED 2026-07-22. Not yet scoped into `feature_list.json`.
Priority: **P1 — a shipped feature is currently dark.**
Effort: L. Bears a migration, so it cannot run concurrently with another
migration-bearing branch (root `CLAUDE.md` → parallel agent work).

---

## Why this exists

Teller is withdrawing its API product. The announcement gave roughly a week's
notice and landed in early July 2026, so **bank sync is likely already dead in
production** — verify before planning around a grace period.

Everything in `api/src/life_dashboard/domains/budget/teller_client.py` talks to
`https://api.teller.io` over mTLS. When that host stops answering, the
background scheduler jobs (`teller_background_sync` every 4h,
`teller_balance_sync` weekly, `main.py:386-406`) start failing on a timer, and
every linked account silently stops updating.

This matters commercially, not just technically: bank sync is the headline of
the paid Cloud add-on ($7/mo — see `plans/marketing-site-spec.md`). The pricing
page cannot ship while the feature behind it is dark.

## The strategic call: abstract, don't swap

The tempting move is `teller_*` → `quiltt_*` find-and-replace. Don't. You are
paying the migration cost once; spend it on a provider abstraction so the next
vendor exit is a config change instead of a rewrite. Quiltt's own migration
writeup makes this argument, and it is self-serving but correct — Teller's exit
is the second-order lesson, not the first.

There is also a Hearth-specific reason, below.

## The self-hosted problem (decide before building)

Quiltt's entry plan is **Builder at $100/mo** — 50 monthly active users
included, $2/MAU after, one aggregator, bring-your-own-Plaid-keys. That is
sane for Cloud and absurd for a single self-hosted household.

Since BYOK is now self-hosted-only, a self-hosted user is expected to supply
their own bank-linking credentials — but no self-hosted individual is paying
$100/mo to do it. **Without a second provider, self-hosted bank sync is
effectively dead**, which collides with the open-core pledge in the root
`CLAUDE.md`.

The known answer is **SimpleFIN Bridge (~$15/yr, read-only, daily refresh)** —
what Actual Budget's self-hosted users use. It is not production-fintech grade,
which is exactly why it suits self-hosted and not Cloud.

So the target shape is:

| Tier | Provider | Credentials |
|---|---|---|
| Cloud | Quiltt (→ MX / Finicity / Akoya / Plaid) | ours |
| Self-hosted / local | SimpleFIN Bridge | user's, ~$15/yr |

Two providers is the actual requirement. That is the strongest argument for the
abstraction, stronger than vendor-risk hedging.

**Open question:** ship SimpleFIN in the same build, or land Quiltt first and
follow with SimpleFIN? Shipping Quiltt alone means self-hosted bank sync stays
dark, and the pricing page can't honestly claim the feature is in the open core
until it lands.

## Target schema

Current state — six vendor columns on `BudgetAccount`
(`domains/budget/models.py:177-182`): `teller_enrollment_id`,
`teller_access_token` (EncryptedText), `teller_account_id`,
`teller_institution_name`, `teller_last_synced_at`, `teller_cursor`.

Proposed:

**New table `bank_connections`** — one row per linked institution, which is
what both Quiltt (Connection) and SimpleFIN model, and what Teller called an
enrollment:

```
id, household_id, provider ('quiltt' | 'simplefin'),
external_connection_id, institution_name, status,
last_synced_at, last_error, created_at, updated_at
```

**`BudgetAccount`** — replace the six `teller_*` columns with:

```
link_connection_id  FK → bank_connections.id, nullable
link_account_id     provider's account ID
link_cursor         provider sync cursor
link_last_synced_at
```

**Note what disappears: `teller_access_token`.** Quiltt holds the upstream
credentials and issues ephemeral session tokens, so Hearth stops storing bank
access tokens entirely. That is a real reduction in blast radius and it is
worth saying out loud on the `/privacy` page.

**Do not remove `"teller"` from the `ImportSource` enum.** Historical
transactions reference it and the value must survive as a read-only tombstone.
See `plans/015-enum-drift-reconciliation.md`. Add `"quiltt"` and `"simplefin"`
alongside.

Migration parents on head **0053**. Must run on Postgres *and* SQLite — use
`op.batch_alter_table`, never an early `return` for SQLite, and verify with
`make migrate-verify` (a green SQLite run proves nothing).

## Re-linking users

Access tokens are scoped to the issuing provider, so **every user must re-link.
That part is unavoidable.** What is avoidable is doing it all on one day.

Do not mass-email a reconnect deadline. Instead:

- prompt at next login, before any screen that needs live account data
- treat a failed refresh on a stale connection as the trigger into the new flow
- keep all historical imported transactions; only the connection dies

Active households re-link first because they show up first; dormant ones
reconnect when they return instead of counting as churn on a date you picked.
Given Hearth's current user count this is close to a non-issue, but the pattern
is right and costs nothing to follow.

Needs a clear in-app state for "connection dead, awaiting re-link" with the
last-known balance still visible rather than a zero or an error.

## Surface to touch

| Area | File | Notes |
|---|---|---|
| Client | `domains/budget/teller_client.py` (67 refs) | replace with `bank_sync/` package: provider protocol + `quiltt.py`, `simplefin.py` |
| Service | `domains/budget/service.py` (103 refs) | `get_teller_config`, `connect_teller_enrollment`, `sync_teller_account`, `sync_all_teller_accounts`, `sync_all_teller_accounts_globally`, `sync_teller_account_balance`, `sync_all_teller_balances_globally` |
| Router | `domains/budget/router.py` (47 refs) | 5 endpoints under `/teller/*` → `/bank-links/*`; keep old paths as deprecated redirects if any client is pinned |
| Models | `domains/budget/models.py` (19 refs) | per schema above |
| Schemas | `domains/budget/schemas.py` (23 refs) | `Teller*` request/response types → provider-neutral |
| Settings | `core/settings.py` (10 refs) | `teller_*` → `quiltt_api_key`, `quiltt_connector_id`, `quiltt_webhook_secret`, `quiltt_environment`; plus `simplefin_*`. Blank disables the feature gracefully — never degrades it |
| Scheduler | `main.py` (10 refs) | job IDs `teller_background_sync` / `teller_balance_sync`. Prefer Quiltt **webhooks** for freshness with a reconciliation poll as backstop, rather than a blind 4-hour poll |
| Agent surface | `ai/tools.py` (4 refs) | `teller_linked`, `teller_institution`, `teller_last_synced_at` exposed to the AI. Per the root `CLAUDE.md` no-feature-without-its-MCP-verb rule, these must move in the same build |
| Web | `web/src/app/(protected)/budget/page.tsx` (41 refs) | `TellerConnect.setup()` → `@quiltt/react` Connector SDK |

## Quiltt concept mapping

- **Profile** = an end user. Billing counts monthly active *Profiles*.
- **Connection** = one institution link (≈ Plaid Item / MX Member / Teller enrollment).
- **Connector** = the embeddable link UI; React SDK exists, which fits the Next.js frontend.
- Server-side **API key**; short-lived **session tokens** for the Profile GraphQL API and the Connector.
- **Webhooks** available — prefer them over polling.

**Map a Quiltt Profile to a Hearth _household_, not a member.** Household is
already the unit of account for billing, and per-member Profiles would multiply
the MAU bill by household size for no product benefit.

**Confirm with Quiltt before signing:** does a household connecting four banks
count as one MAU or four? Their pricing page says "monthly active users" but
their FAQ says plans are "based on the number of connected accounts." Those are
different numbers and the answer swings the unit economics ~4×. This is the
single most important question to ask on the sales call.

## Suggested order

1. Confirm Teller is actually dark; ship the in-app "reconnect needed" state first so users aren't staring at silently stale balances.
2. Quiltt sandbox spike — one household, one connection, one transaction pull. Validate the MAU-counting answer against a real bill.
3. Provider protocol + `bank_connections` table + migration off `teller_*` (one branch, one migration).
4. Quiltt provider implementation + Connector SDK in the web app.
5. Webhook ingestion, then retire the 4-hour poll to a reconciliation backstop.
6. Agent surface parity in `ai/tools.py`.
7. SimpleFIN provider for self-hosted.

## Done when

- A household can link a bank through Quiltt on Cloud and see transactions import.
- Historical Teller-imported transactions are intact and still attributed correctly.
- No `teller_*` column or live code path remains; `"teller"` survives only as an enum tombstone.
- `make migrate-verify` passes against Postgres.
- Self-hosted with blank credentials disables bank sync cleanly — no crash, no half-feature.
- `ai/tools.py` reports link state through the new provider-neutral fields.
