# gethearth.net — Marketing Site Build Spec

Status: draft v1 — decisions locked 2026-07-09, design phase next.
Lives in a **separate repo** (working name: `hearth-site`). Shared brand assets from `hearth/brand/`.

---

## Domains

- **gethearth.net** — marketing site, checkout, account portal, docs, blog.
- **hearth.zone** — the product (customer instances). Shared instance today; subdomain-per-household (`smiths.hearth.zone`) is a future additive change (wildcard DNS + middleware), not part of v1.

## Stack

- **Next.js on Vercel** — same stack as the app; one codebase covers static marketing pages, checkout flow, Stripe webhooks, and the account portal.
- Static-render everything content-y; dynamic routes only for checkout/account/webhooks.
- Docs and blog as MDX in-repo (simplest; revisit CMS only if writing friction appears).

## Payments — Stripe Checkout + Billing

- One **Stripe Customer per household** (not per user). One Subscription per Customer.
- Store `stripe_customer_id`, `subscription_status`, and `billing_email` on the household.
- Stripe **Customer Portal** handles card updates, invoices, plan changes, cancellation — the "manage account" page is mostly a portal-session launcher plus instance info.
- US sales tax handled directly for now; revisit merchant-of-record (Paddle) only if international sales become material.

## Billing & account model

- **Household is the unit of account.** Users belong to a household.
- **Any household admin** can manage billing: backend verifies admin role, then mints a Stripe Portal session for the household's Customer. Multi-admin billing is purely an authz rule — no Stripe complexity.
- **Owner asymmetry (decided):** founding admin is `owner`. Admins have full rights including billing, but cannot demote/remove the owner. Owner transfer is an explicit action. Protects against admin-dispute lockout scenarios.
- `billing_email` on the household — **defaults to the email of the user who created the account** (the owner), editable by any admin. Note: not in migration 0039; needs a follow-up migration.
- **Account portal lives at `gethearth.net/account`** (decided) — not a separate subdomain.

## Provisioning flow (Cloud plan)

1. Buyer completes Stripe Checkout on gethearth.net.
2. `checkout.session.completed` webhook → site backend calls an **internal admin API** on hearth.zone.
3. Creates household + owner account, links `stripe_customer_id`. **Idempotent by `stripe_customer_id`** (per repo idempotency principle).
4. Welcome email with login/set-password link.
5. Lifecycle webhooks (`invoice.payment_failed`, `customer.subscription.deleted`) update `subscription_status`; the app gates access off that field. Grace period before lockout; **data export always allowed** regardless of status.

New work required in the app repo: internal provisioning API (authenticated service-to-service), `subscription_status` gating, household billing fields (`billing_email` migration).

**Existing groundwork in the app repo** (from 2026-07-09 sweep):
- `subscription-001` (feature_list, v1, not yet passing): migration 0039 adds `subscription_status` (`free|trialing|active|past_due|canceled`), `stripe_customer_id`, `is_exempt` to households; `DEPLOYMENT_TIER` env (local|self_hosted|cloud) controls enforcement. `trialing` status implies a free-trial flow was anticipated.
- Paid-gated features already in code: Business budget profile (`FREE_TIER_MAX_PROFILES = 2`, 402 + upgrade prompt) and Coinbase portfolio; GoCardless overage costs assigned to cloud tier.

## Tier structure

No price points exist anywhere in the repo (the "Decide and document open-core pricing model" task in M5 · Monetization is still open). Tier *shape* per ROADMAP/architecture/CLAUDE.md:

- **Self-hosted — Free forever.** Two flavors, both free: single-machine desktop app (Tauri + SQLite) and NAS/Docker (Postgres, multi-device). Full domain feature set, BYOK AI.
- **Cloud (paid).** Managed hosting, automated backups, transactional email, bank sync (Teller/GoCardless costs absorbed), mobile push (later), guided migration from self-hosted.
- **Paid feature candidates** (tier or add-on TBD): managed AI credits, Business budget profiles, Coinbase portfolio, external calendar sync, health integrations.

**Draft price anchors to react to (not decided):** Cloud ~$8–12/mo or ~2 months free annually; AI credits as metered add-on rather than a separate tier. Comparables: Cozi Gold ~$39/yr, Bitwarden Families $40/yr, Actual Budget hosted ~$5/mo, Ghost Starter $9/mo. 14-day trial fits the existing `trialing` status.

**Open conflict to resolve before the pricing page:** root CLAUDE.md promises "all domain features" in the open core, but Business profiles and Coinbase are gated paid in the service layer with no apparent `DEPLOYMENT_TIER`/`is_exempt` bypass. Decide: paid-only everywhere (and say so honestly) vs. free when self-hosted, paid on cloud.

## Sitemap (v1)

| Route | Purpose |
|---|---|
| `/` | Narrative homepage — hero + jobs-to-be-done scroll sections with real screenshots (Ghost pattern): "Run your household", "See your money", "Build routines that stick", "Owned by you" |
| `/features` | Module tour: budget + bank sync, todos w/ recurrence, habits + streaks, recipes + grocery, notes/zettelkasten, documents, calendar, AI assistant (BYOK), household roles |
| `/pricing` | Tier table + FAQ. Tiers: **Self-hosted — free forever** / **Cloud** / possible **Cloud + AI credits**. Price points TBD. |
| `/privacy` (or `/philosophy`) | Data ownership, encryption at rest, BYOK AI, open-source pledge, explicit "what's always free" |
| `/self-host` | Install guide entry point (Home Assistant acquisition model) |
| `/docs` | User docs + self-host guide (MDX) |
| `/blog`, `/changelog` | Content marketing + release notes (`docs/blog-topics.md` has seed topics) |
| `/vs/notion`, `/vs/cozi`, `/vs/spreadsheets` | Comparison pages — SEO, added incrementally |
| `/demo` | Live demo — read-only or nightly-reset demo household (depends on onboarding-002 sample-data seeder) |
| `/account` | Subscription status, instance info, Stripe Portal launcher |

## Screenshot pipeline

Playwright scripted against a seeded demo household on hearth.zone: fixed viewports, consistent theme, re-generatable on demand. Reuses the onboarding-002 sample-data seeder. Screenshots regenerate when UI changes instead of hand-cropping.

## Trust positioning (core differentiator)

Ghost/Plausible/Bitwarden playbook: open source, independent, no investors; "your household's data shouldn't live in a VC-funded startup's database." Footer badges (open source, self-hostable, GitHub stars). Honor `docs/writing-tone.md` in all copy.

## Phases

1. ~~Lock build spec~~ (this doc)
2. Mocks / style exploration in Claude Design — homepage, pricing, features
3. Copywriting pass (tone per `docs/writing-tone.md`)
4. Build site (static pages first)
5. Stripe integration + provisioning API in app repo
6. Screenshot pipeline, demo instance, launch checklist

## Open questions

- **Price points** for Cloud tier(s) — see draft anchors under Tier structure; monthly/annual split and AI-credits packaging still open.
- Trial length (schema already supports `trialing`; 14 days is the default assumption).
- **Open-core boundary conflict** — Business profiles / Coinbase gating vs. "all domain features free" pledge (see Tier structure).
- Repo name for the site repo.
- Analytics choice (Plausible fits the privacy story).
- License confirmation for the open-source pledge copy (check `LICENSE`).
