# 018 — Tier structure brainstorm

Status: BRAINSTORM 2026-07-22. Nothing here is decided. Input for a later
planning session, per the pricing discussion.
Related: `plans/marketing-site-spec.md` (pricing section),
`plans/017-paid-tier-limits.md` (the pledge conflict),
`plans/016-teller-to-quiltt-bank-sync-migration.md` (bank sync is currently dark).

---

## The organizing principle worth adopting

**Tiers should differ by metered capacity of things that cost money to run, not
by which features are switched off.**

This is the only tiering model that survives contact with the open-core pledge.
It also happens to be the honest one: a household on a bigger plan is genuinely
consuming more, and the price reflects that rather than punishing them for
wanting a feature that costs nothing to serve.

What actually costs money per household:

| Resource | Marginal cost | Notes |
|---|---|---|
| AI inference | ~$0.006–0.033 / message | see below; varies by model and caching |
| Bank connections | ~$2 / household / month | plus a fixed ~$100/mo aggregator floor |
| Document storage | pennies / GB | real but small |
| Transactional email | negligible | |
| Compute | small, roughly flat | |

What costs nothing: **every domain feature**, including business budgeting
(`profit_tracking` profiles). Any tier boundary drawn around a zero-cost feature
is a value judgement about willingness to pay, not a cost recovery — which is a
legitimate business move, but it must be named honestly rather than dressed up
as a cost.

---

## AI unit economics (the number that should drive tier design)

Current Claude API rates: Sonnet 4.6 $3/$15 per million input/output tokens,
Haiku 4.5 $1/$5. Prompt caching cuts cached input by 90%; Hearth's system prompt
plus household context is highly cacheable, so the cached column is the
realistic one.

Cost per AI message, assuming household context is injected:

| Model | Light (10k in) | Typical (20k in) | Heavy (35k in) |
|---|---|---|---|
| Sonnet 4.6, cached | $0.010 | **$0.018** | $0.033 |
| Haiku 4.5, cached | $0.004 | **$0.006** | $0.011 |

Monthly cost at volume (typical load, cached):

| Messages/mo | Sonnet | Haiku |
|---|---|---|
| 100 | $1.80 | $0.60 |
| 200 | $3.60 | $1.20 |
| 500 | $9.00 | $3.00 |
| 1,000 | $18.00 | $6.00 |
| 3,000 | $54.00 | $18.00 |

**⚠️ Correction (same day).** The paragraph that used to sit here concluded that
an $8 plan is "fully consumed by ~444 Sonnet messages" and that allowances must
therefore differentiate tiers. That reasoning was wrong: it costed every customer
as if they maxed their allowance. **Expected cost is driven by mean usage; the
cap only binds the tail.**

Modelled against a plausible household distribution (30% barely use it, 35%
occasional, 22% regular, 10% heavy, 3% power users):

| Cap | Mean usage | Cost/customer/mo (pure Sonnet) | Share hitting cap |
|---|---|---|---|
| 200 | 49 msgs | $0.88 | 13% |
| 500 | 60 msgs | $1.08 | 3% |
| 1,000 | 66 msgs | $1.19 | 0% |

At a 500 cap with **no model routing at all**, AI costs ~$1.08/customer/month —
13% of an $8 plan. Routing is a nice-to-have, not a prerequisite. The worst case
for a single customer maxing a 500 cap is $4.80.

**Therefore AI should not be a tier axis.** Three reasons:

1. **Illegible unit.** Nobody can tell whether 200 messages is generous or
   stingy, so it does no persuasive work on a pricing page.
2. **It penalises the BYOK upgrader** — someone moving up for business features
   pays for AI headroom they will never touch.
3. **It isn't doing pricing work anyway.** The difference between a 200 and a
   1,000 cap is $0.31/customer/month.

**Recommended:** one fair-use ceiling (~500/month), identical on every paid
plan, stated in the FAQ rather than on the plan cards, sized so no normal
household ever meets it. Once real usage data exists, publishing it — "the
median household uses about 50 a month, the cap is 500" — makes the limit read
as generous rather than restrictive, and fits the transparency positioning.

---

## Annual vs monthly: the ×1.25 rule

To stay inside the 15–25% norm with flat numbers every time:

> **monthly = annual × 1.25** → exactly 20% off, always.

| Annual rate | Monthly rate | Annual total | Discount |
|---|---|---|---|
| $8 | $10 | $96 | 20% |
| $12 | $15 | $144 | 20% |
| $16 | $20 | $192 | 20% |
| $20 | $25 | $240 | 20% |
| $24 | $30 | $288 | 20% |
| $28 | $35 | $336 | 20% |

If a softer discount is wanted, **×1.2** gives 17% (the "two months free"
equivalent) and also lands flat: $10→$12, $15→$18, $20→$24, $25→$30.

Either rule beats picking numbers per tier, because it keeps the discount
consistent across the whole page. An inconsistent discount between tiers is the
kind of thing a prospect notices and reads as arbitrary.

The originally proposed $8/$12 and $7/$10 are 33% and 30% — outside the norm,
and past the point where the monthly price starts reading as artificial.

---

## Three candidate models

### Model A — One plan + add-ons

```
Hearth Cloud          $8/mo annual   ($10 monthly)
  + Bank sync         $7/mo annual   ($9 monthly)
  + AI top-up         metered, buy more when the allowance runs out
```

**For:** cheapest entry point. Fewest SKUs to build, price, support and explain.
Every add-on is self-funding and the cost pass-through story stays intact and
honest. Nothing is ever withheld from anyone who wants to pay for it.

**Against:** lowest ARPU. No middle-tier anchoring, which is a real and
well-documented conversion mechanic. Doesn't capture the home-business customer
who would happily pay 3×. Add-on lists get fiddly past two or three items.

### Model B — Three tiers by capacity

```
Home              $8/mo annual  ($10)   everything · 200 AI msgs · no bank sync · 5GB
Household        $16/mo annual  ($20)   + bank sync (3 institutions) · 1,000 AI msgs · 25GB
Home & Business  $28/mo annual  ($35)   + business budgeting · unlimited institutions · 3,000 AI msgs · 100GB
```

**For:** conventional and instantly legible — buyers know how to read this.
Anchoring lifts ARPU. Room to grow into.

**Against:** tier 2 is essentially "bank sync + more AI" at double the price,
which is a hard sell unless more goes into it. Loses the cost-pass-through
transparency that makes the bank-sync charge feel fair. And with zero customers,
the segment boundaries are guesses — you'd be designing three products for an
audience you haven't met.

### Model C — Two tiers + bank sync add-on *(recommended starting point)*

```
Hearth            $8/mo annual  ($10)   everything · AI allowance · 10GB
Hearth Business  $20/mo annual  ($25)   + business budgeting · multiple profiles ·
                                          larger AI allowance · 100GB · priority support
  + Bank sync     $7/mo annual  ($9)    available on either tier
```

**For:** keeps sync as an honest pass-through, where the "$2 costs us, $7
covers it" transparency still makes sense. Adds one upmarket tier aimed at a
segment with genuinely different willingness to pay — someone running a business
from home is not price-shopping against Cozi. Only three SKUs. Leaves room to
split into three tiers later once there is usage data to draw the line with.

**Against:** the business tier's headline feature costs nothing to serve, so the
pledge language still has to widen (see below). Two tiers plus an add-on is
marginally more to explain than one plan plus an add-on.

---

## The BYOK-upgrade problem

Flagged in discussion and worth taking seriously: **a self-hosted user running
AI on their own API key, who migrates to Cloud, currently loses that ability and
gets a metered allowance instead.** They will experience paying money as a
downgrade. That is the worst possible first impression from the exact
segment most likely to become advocates.

Three ways out:

1. **Allow BYOK on Cloud as an "unlimited AI" escape hatch.** Reverses the
   self-hosted-only decision, but note the code path *already exists* —
   `ai/service.py` resolves a per-user key first and falls back to the system
   key. The feared complexity is largely already built and currently being
   suppressed on purpose. Most Cloud buyers have no Anthropic key and will never
   use it, so it doesn't undermine pricing; it just removes the migration
   grievance. **Cheapest fix by a wide margin.**
2. **Make the allowance generous enough that nobody notices.** Works until a
   power user notices, which is precisely the person who had a BYOK key.
3. **Grandfather migrating self-hosted users** onto BYOK. Solves the grievance,
   creates a permanent special case in the billing logic. Worst of the three.

Option 1 is worth revisiting the earlier decision for. The original reasoning
("don't want the complexity of paid subscribers bringing their own keys") is
sound in general but doesn't hold when the plumbing is already written and the
alternative is annoying your most vocal users at the moment they start paying.

### Does allowing BYOK on Cloud cannibalise anything?

Short answer: no, and it probably improves margin. The worry is that offering
BYOK undercuts the value of the included AI. That only holds if AI is a
*revenue* line — if inference were being marked up and sold. It isn't. The
allowance is bundled into the subscription and it is a **cost**, so every BYOK
subscriber pays full price and consumes zero inference. They are the most
profitable customers on the books.

**What managed AI actually gives the customer, versus BYOK:**

| | Managed (ours) | BYOK |
|---|---|---|
| Setup | none | Anthropic account, billing, key, rotation |
| Billing | one predictable charge | a second variable bill |
| Runaway usage | capped by the allowance | uncapped, on their card |
| Model routing | handled | handled either way |
| Support | one party to ask | two |
| Heavy usage | limited by allowance | unlimited at cost |

For the typical Cloud buyer — a household that wants the thing to work — BYOK
is strictly worse. They do not want a second account and will never create an
API key. Managed AI wins on setup alone, and that is the whole ballgame for
this audience.

**The one segment where BYOK wins is heavy users**, and the maths shows why
that is good news rather than bad. At a blended ~$0.01/message, a 200-message
allowance is worth about $2. Nobody switches to BYOK to save $2. It only becomes
attractive above roughly 500–1,000 messages a month — which is precisely the
customer who would otherwise be sitting at the top of the allowance costing more
than they pay. **BYOK is a pressure-release valve that removes the
worst-margin customers**, not a leak.

**Recommended shape:** managed AI is the default and the only thing the pricing
page mentions. BYOK lives in Settings as an unadvertised power-user option. The
pricing story stays simple ("200 messages included"), self-hosted migrants find
the setting and are pleased rather than aggrieved, and no revenue stream is
cannibalised because there isn't one to cannibalise.

The only future scenario where this changes is if AI top-ups become a real
revenue line — selling inference above cost. That is a low-margin business to be
in, and if it ever happens the BYOK setting can be revisited then.

---

## Buyer segments (answered 2026-07-22)

The hosted plan is being built for, in order of confidence:

1. **A couple or family running a busy home** — shared chores, meal planning,
   joint budget, everyone's schedule. Non-technical, wants it to work.
2. **The organised one in a household** — the person carrying the planning load
   who wants a system and drags the rest of the house along.

Three consequences fall straight out of this:

- **Neither will ever bring an API key.** BYOK-on-Cloud is confirmed as a
  non-issue for the core audience, which reinforces keeping it as an
  unadvertised Settings option rather than a pricing-page concept.
- **Illegible units are worse than usual here.** "600 AI messages" means nothing
  to this buyer. Every number on the pricing page has to be something they can
  evaluate against their own life.
- **They price-anchor against Cozi (~$39/yr) and their existing app pile**, not
  against developer tools. Self-hosted-free doesn't compete for their purchase —
  but it does work on them as a *trust signal*, which is why it stays on the page.

**The useful structural insight:** a Business tier segments a *different person*,
not a harder choice for the same person. The family buyer sees "Hearth $8" and
never has to evaluate the Business column. Tiers that split audiences are far
easier to sell than tiers that ask one buyer to weigh options — this structure
gets that for free, and it is a reason to prefer it over a Home/Household/Pro
ladder aimed at one segment.

## What goes in the Business tier

Business budgeting (the P&L profile view) alone is one feature in a tier
costume. The chosen addition is **invoicing and income tracking** — issue simple
invoices, track paid/unpaid, feed it into the P&L.

That makes the tier credible, and the price anchors well. Comparable freelancer
tools: FreshBooks Lite $23/mo (capped at 5 clients), Wave Pro $19/mo, mid-range
tools generally $10–25/mo. **Hearth Business at $20/mo annual sits inside that
band while also including the entire household app** — a strong story for a
freelancer whose home and business finances are already tangled.

**But invoicing does not exist yet.** It is a real build — arguably its own
product surface — and nothing in `feature_list.json` covers it.

**Consequence for sequencing: do not launch the Business tier at v1.** A
Business tier containing only the P&L view is exactly the thin-tier problem, and
shipping it thin to fill a pricing column is how you end up with a
`FREE_TIER_MAX_PROFILES` situation in pricing form. Launch one plan plus the
sync add-on; introduce Business when invoicing ships. Adding a higher tier later
upsets nobody.

## Sequencing recommendation

**Launch with the fewest SKUs that can work, add tiers when there is data.**

With zero customers, tier boundaries are guesses. Every extra tier multiplies
Stripe price objects, pricing-page cognitive load, support surface, and the
number of decisions that have to be right before launch. Tiers are also easy to
*add* later and painful to remove — nobody is upset by a new higher tier
appearing; plenty of people are upset when a tier they bought is restructured.

Concretely: ship **Model A or C**, instrument AI and bank-connection usage from
day one, and revisit at ~50 paying households when the distribution is visible
rather than assumed. The three-tier model is a good v2 and a bad v1.

---

## Open questions

- Which model. Recommendation is C, with A as the more conservative option.
- What unit the AI allowance is expressed in. "Messages" is legible to
  households; "credits" is more accurate but needs explaining. Whatever the
  unit, usage must be visible in-app *before* someone hits the ceiling.
- What happens at the ceiling: hard stop, degrade to Haiku, or offer a top-up.
  Degrading to a cheaper model is the gentlest and worth considering — the
  feature keeps working, it just gets a bit less sharp.
- Whether bank sync stays an add-on or becomes a tier unlock. Add-on keeps the
  honesty story; tier unlock is more conventional.
- The pledge rewrite required by *any* tiering of zero-cost features. See
  `plans/017-paid-tier-limits.md` — narrowing to "everything is free when
  self-hosted; Cloud tiers differ" is the honest version.
- Storage limits: not yet modeled. Document upload costs are real but small;
  needs a number before appearing on a pricing page.
