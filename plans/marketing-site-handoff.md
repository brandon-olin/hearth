# gethearth.net — context handoff

Written 2026-07-21 to start marketing-site work in a fresh thread. Read
`plans/marketing-site-spec.md` first — it is the real spec (99 lines, decisions
locked 2026-07-09). This document exists to give you current state and to
correct the parts of that spec that have gone stale since it was written.

---

## Where the product stands

**The v1 app is complete.** Every feature tagged `phase: v1` in
`feature_list.json` passes — 13 of 13, including onboarding (wizard, sample
data, first-visit hints), PWA, transactional email, household/invites, and the
subscription schema stubs. 27 features remain pending, all v1.1 / later / p2–p3
polish. Nothing in the app is blocking a launch.

**What that means for you:** the marketing site and payments are now the
critical path. They are the only work standing between a finished product and a
business, and neither is tracked in `feature_list.json`.

Recently shipped that matters to this effort:
- **Demo/sample data** (`onboarding-002`, migration 0052) — seeds a realistic
  household and tracks what it created in a manifest table so it can be cleanly
  cleared. This is the dependency the spec names for both `/demo` and the
  Playwright screenshot pipeline. It exists now. Entry points are in
  `api/src/life_dashboard/onboarding/service.py` (`demo_data_status`,
  `household_has_real_data`).
- **Agent surface** — outbound webhooks (0050), agent proposals (0051), MCP
  tools, OAuth 2.1 + Personal Access Tokens. Relevant because the
  service-to-service provisioning API the spec calls for may be able to reuse
  PAT or OAuth client-credentials rather than inventing a new auth scheme.

Current migration head is **0053**. Any new app-repo migration parents on that.

---

## Corrections to the spec (it is ~2 weeks stale)

1. **`subscription-001` now passes.** The spec says "not yet passing". It was
   verified 2026-07-21 and closed. All three household columns exist and are
   live: `subscription_status` (`free|trialing|active|past_due|canceled`),
   `stripe_customer_id`, `is_exempt`. `DEPLOYMENT_TIER` (`local|self_hosted|
   cloud`) exists in settings and gates enforcement.

   Important caveat: that entry's scope was **schema stubs only**. Stripe
   checkout, the webhook handler, and actual feature gating were explicitly
   deferred and **do not exist**. There is no payment path today.

2. **`billing_email` is still absent.** The spec correctly flagged it as not in
   migration 0039 and needing a follow-up. That is still true — it is not in
   the models. It is the one known schema gap for billing.

3. **The onboarding-002 dependency is satisfied**, as above. The spec was
   written when it was still pending.

4. **License is AGPL-3.0** — confirmed, so the open-source pledge copy on
   `/privacy` or `/philosophy` can be written against that specifically. The
   spec listed this as an open question.

5. **Brand assets exist** at `hearth/brand/`: `logo.svg`, `logo-dark.svg`,
   `logo-square.svg`, `logo-wordmark.svg`.

---

## The unresolved decision that blocks the pricing page

The spec flags this and it is still open. It is not a copywriting problem — it
is a product-positioning decision:

Root `CLAUDE.md` promises **"all domain features"** in the open core. But two
features are gated paid in the service layer with no self-hosted bypass:
- **Business budget profiles** — `FREE_TIER_MAX_PROFILES = 2` in
  `api/src/life_dashboard/domains/budget/service.py:85`, returning HTTP 402 via
  `budget/router.py:99`.
- **Coinbase portfolio** (`budget-019`, pending).

So the code and the pledge currently contradict each other. Resolve before
writing `/pricing`:
- **Option A** — free when self-hosted, paid on cloud. Requires a
  `DEPLOYMENT_TIER` / `is_exempt` bypass in those gates. Keeps the pledge intact.
- **Option B** — paid everywhere, and change the pledge language to be honest
  about it.

Also still open: **price points** (nothing exists in the repo). Draft anchors
in the spec: Cloud ~$8–12/mo or ~2 months free annually, AI credits as a
metered add-on. Comparables listed there: Cozi Gold ~$39/yr, Bitwarden Families
$40/yr, Actual Budget hosted ~$5/mo, Ghost Starter $9/mo. The `trialing` status
already in the schema implies a trial; 14 days is the working assumption.

---

## Work split across two repos

**Site repo** (new, working name `hearth-site`, Next.js on Vercel):
marketing pages, checkout, Stripe webhooks, account portal, docs/blog as MDX.

**App repo** (this one, `hearth`) — new work the spec identifies:
- internal provisioning API, authenticated service-to-service
- `subscription_status` enforcement/gating (stubs exist, enforcement does not)
- `billing_email` migration (parents on 0053)

Provisioning must be **idempotent by `stripe_customer_id`** — this is a
repo-wide principle, not a nicety. See root `CLAUDE.md` → "Write idempotently"
and `api/CLAUDE.md` → "Idempotency". A duplicate `checkout.session.completed`
webhook must not create a second household.

---

## Conventions to follow if you touch the app repo

These are enforced and have caused real breakage when skipped:

- **`feature_list.json` + `claude-progress.txt` must be updated** after any
  meaningful unit of work — but in the *final* commit only, after rebasing.
  They are the top merge-conflict source.
- **Migrations must run on Postgres AND SQLite.** Use `op.batch_alter_table`
  for ALTER-shaped work; never an early `return` for SQLite. Verify with
  `make migrate-verify`, which replays the full history against a throwaway
  Postgres DB the way Railway's `preDeployCommand` does. A green local run
  against SQLite proves nothing.
- **One migration-bearing branch at a time**; they cannot run concurrently.
- **`git push origin main` stays human.** Pushing main triggers the Railway
  build and an automatic `alembic upgrade head` against the deployed database.
- **No feature ships without its agent surface** (MCP tool, resource, or bus
  event) in the same build.
- Tone for all copy: `docs/writing-tone.md`. Blog seed topics:
  `docs/blog-topics.md`.

---

## Suggested first moves

1. Resolve the open-core boundary conflict — it gates `/pricing` and it is a
   decision, not a task.
2. Decide price points and trial length.
3. Break the spec's phases into tracked entries. The spec's own phase list is
   good: mocks → copy → static build → Stripe + provisioning → screenshots and
   demo. Everything else in this project is tracked in `feature_list.json`;
   the marketing work is currently the exception, which is why it has been
   invisible.
4. Name the site repo.

Note the spec's phase 2 is "mocks / style exploration in Claude Design" — that
was the recorded next action as of 2026-07-09 and has not happened yet.
