# gethearth.net — Marketing Site Build Spec

Status: v2 — build decisions locked 2026-07-09, positioning + pricing locked 2026-07-22.
Design phase (mocks) is the next unstarted action.
Lives in a **separate repo** (confirmed 2026-07-22): `hearth-site`. Shared brand assets from `hearth/brand/`.

> Current state of the product, and corrections to anything below that has gone
> stale, live in `plans/marketing-site-handoff.md`. Read it alongside this file.

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

## Tier structure — DECIDED 2026-07-22

### The boundary: BYOK on self-hosted, managed on Cloud

**Every domain feature is in the open core.** Nothing is withheld from
self-hosted users. The paid line is drawn at *who pays the per-use bill*, not
at what the software can do.

Features that carry an ongoing third-party cost — AI, bank linking — run on
**your own credentials when self-hosted** (BYOK) and on **ours when you're on
Cloud**. Same feature, different bill payer.

**BYOK is self-hosted-only (decided 2026-07-22).** Cloud subscribers do not
bring keys — we supply them and the price covers it. Supporting customer-owned
credentials on a managed plan is complexity with no payoff. Mechanically this
means hiding the BYOK settings UI when `deployment_tier == "cloud"`; the code
path in `ai/service.py` (per-user key, system-key fallback) stays as-is for
self-hosted rather than being special-cased away.

Already implemented this way, so the story is honest today:
- **AI** — per-user BYOK key with fallback to a system key (`ai/service.py:71-80`).
- **Bank sync** — per-install credentials via env; blank credentials disable the
  feature cleanly rather than degrading it.

Resolved since the last draft:
- **`FREE_TIER_MAX_PROFILES` removed 2026-07-22.** It gated `profit_tracking`
  profiles behind a count that every household exceeded from creation, with no
  paid bypass — a dead feature, not an upsell. The limits it was reaching for
  (a linked-account cap, and business accounting as a Cloud tier) are captured
  in `plans/017-paid-tier-limits.md`. Neither blocks this site.
- **Coinbase is out of scope entirely** — far-future, not a v1 pricing concern.

⚠️ **Bank sync is the open risk.** Teller withdrew its API in early July 2026;
the migration to a provider abstraction is `plans/016-teller-to-quiltt-bank-sync-migration.md`.
The paid add-on below sells a feature that is currently dark. Sequence
accordingly — the pricing page should not ship ahead of the fix. That plan also
flags that self-hosted needs a cheap second provider (SimpleFIN ~$15/yr), since
Quiltt's $100/mo floor makes self-hosted BYOK bank sync a non-starter otherwise.

### Tiers — v1 shape (revised 2026-07-22)

Presented the standard way: the annual rate is shown as a monthly figure
("$8/month, $96 billed annually") and month-to-month costs more. Never display
a decimal monthly rate — flat numbers only.

| | Billed annually | Month-to-month |
|---|---|---|
| **Self-hosted** | Free forever | Free forever |
| **Cloud** | **$8/mo** ($96/yr) | $12/mo *(TBD)* |
| **Bank sync add-on** | **$7/mo** ($84/yr) | $10/mo *(TBD)* |
| **All-in** | $15/mo ($180/yr) | $22/mo |

⚠️ **The month-to-month rates are unresolved.** As drafted they imply a 33%
(Cloud) and 30% (sync) annual discount. Industry norm is 15–25%, with ~20% the
common sweet spot; above ~30% the monthly price starts reading as artificial
and buyers discount the annual number too. A 20% split — **$8 annual / $10
monthly**, **$7 annual / $9 monthly** — keeps flat numbers, stays inside the
norm, and still moves people to annual. Decide before the page is written.

Note this replaces the earlier "two months free" model. Under that scheme
annual was $80; here annual is $96 and the discount comes from the monthly rate
being higher rather than the annual rate being lower. Same convention most
apps use, and better for cash flow, but it *is* a real price increase for
annual buyers — worth being deliberate about rather than drifting into.

### V1 scope — AI (decided 2026-07-22)

**One plan, AI included, capped.** Of the options modelled in
`plans/019-ai-cost-control.md`, option 1 was chosen: keep the $8 price, include
the assistant with a ceiling around **150 turns/month**, degrade to the fast
model beyond it rather than cutting off, and keep BYOK available on self-hosted
as the escape valve for heavy users.

À-la-carte add-ons remain the preferred long-term direction — they fit the
transparency positioning and extend without repricing — but v1 ships the
simplest thing that works.

**The conversational journal/coach is deferred on Cloud.** See
`plans/021-journal-coach-cloud-deferral.md`. Plain journal *writing* ships;
the AI conversation partner does not. The reason is not cost — it is that an AI
processing someone's difficult feelings can do real harm when it misreads a
moment, and it hasn't been tested enough to know it won't. Self-hosted keeps it,
on informed consent.

Effect on the economics: expected AI spend falls from $2.08 to **$1.24 per
subscriber** (26% → **15%** of an $8 plan), and the heavy-user worst case from
$13.47 to $6.85, bounded to ~$5.13 by the cap.

**Copy consequences — these are constraints, not suggestions:**

- The AI story on `/` and `/features` is exactly one sentence: *an assistant that
  knows your household.* Nothing about journaling, coaching, reflection,
  wellbeing, or anything therapy-adjacent.
- **Do not tease it as "coming soon."** A public promise creates pressure to ship
  before it's ready, which is the exact failure this decision exists to prevent.
- The homepage module grid already reads "AI assistant — Knows your household",
  which is correct as-is. The requirement is not to *add* anything.
- Any allowance number stated publicly must come from measured `AiUsage` data,
  not estimate — see `plans/019` and `plans/020`.

### Direction: three tiers (not yet designed)

The two-plan shape above is provisional. The intended end state is a
conventional three-tier model:

- **Tier 1** — core household app.
- **Tier 2** — adds bank linking, plus other features TBD.
- **Tier 3** — adds business budgeting (`profit_tracking` profiles), plus other
  features TBD.

**This needs a real brainstorm before it goes near the pricing page.** Two
things to resolve first:

1. **What actually populates tiers 2 and 3?** A tier with one feature in it is
   not a tier, it is a paywall with extra steps. Bank linking alone doesn't
   carry tier 2, and business budgeting alone doesn't carry tier 3.
2. **It contradicts the open-core boundary as currently written.** The root
   `CLAUDE.md` says the paid line is *who pays the per-use bill*, and forbids
   paywalling features that cost us nothing to run. Business budgeting costs
   nothing to run. Either the pledge narrows to "everything is free when
   self-hosted; Cloud tiers differ" — which is honest and still protects the
   thing the pledge exists to protect — or the tiering doesn't happen. See
   `plans/017-paid-tier-limits.md`, which frames the same decision.

Do not ship a tiered pricing page and an unchanged pledge. That is precisely
the contradiction cleaned up on 2026-07-22.

- **Self-hosted — free forever.** Single-machine desktop (Tauri + SQLite) and
  NAS/Docker (Postgres, multi-device). Full domain feature set. Cost-bearing
  integrations run BYOK.
- **Cloud — $8/mo or $80/yr.** Managed hosting, automated backups, transactional
  email, AI without bringing a key, mobile push (later), guided migration from
  self-hosted.
- **Bank sync — $7/mo ($84/yr) add-on** in the v1 two-plan shape; becomes a
  tier-2 unlock if the three-tier model lands. Either way it is a cost
  pass-through and the page should say so plainly: bank linking costs us roughly
  $2 per household per month, and the add-on covers that, the connection
  failures, and the support they generate.
- **Annual is the default-selected option.** Beyond the discount, prepay is the
  float that covers the aggregator's fixed monthly floor before there's
  meaningful MRR — roughly a dozen annual all-in subscribers cover a year of
  infrastructure up front.
- **Trial:** 14 days per the existing `trialing` status. Worth revisiting —
  YNAB gives 34 days, and a household budget tool arguably can't be evaluated
  in less than one full billing cycle. Not yet changed.

Further tiers with differentiated functionality come later — v1 ships one Cloud
plan plus the add-on. Do not build tier-comparison machinery the page doesn't
need yet.

### Positioning against YNAB

Being priced above YNAB ($14.99/mo, $109/yr) is **not a problem to apologize
for, and the copy must not chase a cheaper-than-YNAB angle.** Hearth is an
all-in-one home app; budgeting is one room in the house. The claim is:

> *We do all of this — tasks, habits, recipes, documents, calendar, the whole
> household — **and** something close to what YNAB does, at a good price.*

Not "we undercut YNAB." A visitor comparing line-item budgeting features
head-to-head with a dedicated budgeting product has already been framed wrong.
Comparables for context, not for a race to the bottom: Cozi Gold ~$39/yr,
Bitwarden Families $40/yr, Actual Budget hosted ~$5/mo, Ghost Starter $9/mo.

## Sitemap (v1)

| Route | Purpose |
|---|---|
| `/` | Narrative homepage — hero + jobs-to-be-done scroll sections with real screenshots (Ghost pattern): "Run your household", "See your money", "Build routines that stick", "Owned by you" |
| `/features` | Module tour: budget + bank sync, todos w/ recurrence, habits + streaks, recipes + grocery, notes/zettelkasten, documents, calendar, AI assistant (BYOK), household roles |
| `/pricing` | Two columns: **Self-hosted — free forever** / **Cloud — $8/mo, $80/yr**, with bank sync as a $7/mo add-on line rather than a third column. Annual preselected. FAQ answers "what's the catch with free?" head-on: nothing is withheld, you bring your own API keys for the things that cost money. |
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

## Resolved (2026-07-22)

- **Price points** — Cloud $8/mo billed annually ($96/yr); bank sync $7/mo
  ($84/yr). Month-to-month rates still TBD; three-tier model still to design.
- **Price presentation** — annual shown as a monthly rate with "billed
  annually" beneath; month-to-month priced higher. Flat numbers, never decimals.
- **Trial length** — 14 days (flagged for revisit, not changed).
- **Open-core boundary** — BYOK for cost-bearing features, **self-hosted only**;
  no domain feature withheld. See Tier structure.
- **Positioning** — all-in-one home app that also budgets; not a cheaper YNAB.
- **`FREE_TIER_MAX_PROFILES`** — removed. Follow-up in `plans/017-paid-tier-limits.md`.
- **Coinbase** — out of scope.
- **Site repo name** — `hearth-site`, separate from the app repo.
- **License** — AGPL-3.0, confirmed in `LICENSE`. Pledge copy can name it.

## Open questions

- Analytics choice (Plausible fits the privacy story).
- Whether the Cloud plan takes a card up front for the trial.
- Whether managed AI on Cloud is metered or fair-use-capped — affects the
  pricing-page footnote but not the price.
- Whether `/pricing` lists the bank-sync add-on before the provider migration
  lands, or ships without it and adds it later.

## App-repo work the pricing decision creates

Tracked separately, built in parallel with this site:

1. **Bank sync provider migration** — `plans/016-teller-to-quiltt-bank-sync-migration.md`.
   P1; the add-on's feature is currently dark.
2. **`billing_email` migration**, parenting on head 0053.
3. **`subscription_status` enforcement** — stubs exist, gating does not. Must
   also handle the add-on as a separate subscription item.
4. **Internal provisioning API** — may be able to reuse PAT / OAuth
   client-credentials rather than a new service-to-service scheme.
5. **Hide BYOK settings UI when `deployment_tier == "cloud"`.**
6. **Tier limits**, if ever — `plans/017-paid-tier-limits.md`. Must ship
   alongside matching pricing-page copy, never ahead of it.
