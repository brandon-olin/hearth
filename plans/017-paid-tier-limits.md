# 017 — Paid tier limits: linked-account cap + business accounting tier

Status: PROPOSED 2026-07-22. Design not started — this file exists so the two
open questions don't get lost now that `FREE_TIER_MAX_PROFILES` has been removed.
Priority: P2 — needed before `/pricing` promises anything specific, not before.
Effort: S (each), once the shape is decided.

---

## What was just removed, and why it isn't the answer

`FREE_TIER_MAX_PROFILES = 2` was deleted from
`domains/budget/service.py` on 2026-07-22. It was not a working paywall:

- every household is seeded with exactly two profiles at creation (Personal +
  Household, `seed_default_profiles`), so `existing_count >= 2` was true from
  day one, forever
- there was no `deployment_tier` or `is_exempt` bypass anywhere, so **paying
  didn't unlock it either** — business profiles were unreachable in every tier
- it capped nothing else: additional `zero_based` profiles were always unlimited

So the intent (charge for business accounting) was real; the implementation
gated a feature into nonexistence and told the user to buy a tier that doesn't
exist. Removing it restores the feature. The two limits below are the actual
business requirements, to be built deliberately.

---

## Limit 1 — cap linked bank accounts (cost control)

**Why:** bank linking is the only per-household variable cost in the product.
Under Quiltt Builder that's ~$2/household/month with 50 included, but the
number that bites is the **$100/mo floor** — see
`plans/016-teller-to-quiltt-bank-sync-migration.md`. A household linking 15
accounts is not 15× the cost *if* Quiltt bills per active Profile; it very much
is if they bill per connected account. **Do not design this limit until that
question is answered** — the right cap depends entirely on which unit is metered.

**Design constraints:**

- Gate on `deployment_tier` / `household.is_exempt`, never unconditionally.
  Self-hosted users pay their own provider bill, so a cap there is unjustifiable
  and violates the open-core boundary in the root `CLAUDE.md`.
- Cap **connections** (institutions) or **accounts**, matching whichever unit
  the provider actually bills. Mismatching these is how you build a limit that
  annoys users without controlling cost.
- A generous cap that is never hit by a normal household is fine and probably
  correct — this is an abuse guard, not a monetization lever. Two adults with
  checking, savings, two credit cards and a mortgage is ~6-8 accounts; the cap
  should sit well clear of that.
- Failure mode must be a clear message naming the limit and the upgrade path,
  not a bare 402.

**Open:** what the number is, and whether exceeding it blocks new links or
bills an overage.

---

## Limit 2 — business accounting behind a higher tier

**What:** `budgeting_style = 'profit_tracking'` profiles — the P&L view
(revenue vs expenses, net profit headline, no envelopes). Currently ungated and
therefore available to everyone, including self-hosted.

**The tension to resolve:** the root `CLAUDE.md` open-core boundary says the
paid line is *who pays the per-use bill*, and that features costing us nothing
to run must not be paywalled. Business accounting costs nothing per use. Gating
it contradicts the pledge as currently written.

Three honest ways out:

1. **Free everywhere, including Cloud.** Consistent with the pledge, forfeits
   the upsell. Business profiles become a differentiator against Cozi rather
   than a revenue line.
2. **Free self-hosted, paid on Cloud.** Consistent with the BYOK precedent, but
   note the precedent covers *cost-bearing* features — this one isn't, so the
   pledge language would need to widen from "who pays the per-use bill" to
   something like "self-hosted gets everything; Cloud tiers differ."
3. **Higher Cloud tier, and narrow the pledge to "all features free when
   self-hosted."** Cleanest business outcome, requires honestly rewriting the
   open-core section rather than quietly contradicting it.

**Recommendation: (3), decided explicitly.** It keeps self-hosted genuinely
uncrippled — the thing the pledge actually exists to protect — while allowing
Cloud tiers to differ. But it is a pledge change and must be made in the open,
in `CLAUDE.md` and on `/pricing`, not by leaving a gate in the service layer
that disagrees with the marketing copy. That is the exact failure mode being
cleaned up here.

**If gating is chosen**, the mechanics are already scaffolded: raise `ValueError`
from `service.create_profile` and the router's existing 402 path handles it
(`domains/budget/router.py`). Check `deployment_tier == "cloud"` and
`household.subscription_status` / `is_exempt` — never a bare count.

---

## Sequencing

Neither limit blocks the marketing site. `/pricing` v1 sells one Cloud plan
plus a bank-sync add-on and says nothing about profile counts, so both can be
designed after launch. What *would* block the pricing page is reintroducing a
gate that contradicts the published copy — so if either limit ships, the
pricing page and `CLAUDE.md` change in the same build.

Blocked on: the Quiltt MAU-vs-connected-account billing answer (limit 1), and
an explicit pledge decision (limit 2).
