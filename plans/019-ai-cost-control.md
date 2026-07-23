# 019 — AI cost control: tool payload, caching, and metering

Status: PROPOSED 2026-07-22 (rewritten same day — see "Correction" below).
Priority: **P1 before any paid launch.** The pricing page cannot state an AI
allowance until this is settled.
Effort: caching S/M · tool subsetting M · metering M.
Related: `plans/018-tier-structure-brainstorm.md`, `plans/marketing-site-spec.md`.

---

## Correction

An earlier draft of this plan named the "talk it out" journaling flow as the
dominant AI cost and proposed treating it as a paid add-on. **Measurement against
the actual code says the opposite.** Journal mode restricts the tool array to
`update_profile` only (`journal-001`), so a journaling turn ships ~300 tokens of
tool schema. **Ordinary chat ships all 66 tools — ~15,582 tokens — on every
single API call.** Regular tool-using chat is the cost problem; journaling is not.

---

## Finding 1: the tool payload dominates everything

`TOOL_DEFINITIONS` in `ai/tools.py` holds **66 tool schemas measuring ~15,582
tokens** (median 212 tokens per tool, largest 725). That entire array is sent on
every call to `stream_chat`.

At Sonnet input rates that is **$0.047 per API call before a single word of
conversation.**

**And the tool loop multiplies it.** `generate_stream` runs up to
`_MAX_TOOL_ROUNDS = 5`, meaning one user message can trigger six API calls, each
re-shipping the full tool array, system prompt, and accumulated history:

| Scenario | Uncached | Cached | Saving |
|---|---|---|---|
| Simple question, no tools (1 call) | $0.072 | $0.025 | 2.9× |
| Typical, 1 tool round (2 calls) | $0.146 | $0.051 | 2.8× |
| Busy, 3 tool rounds (4 calls) | $0.324 | $0.134 | 2.4× |
| Worst case, 5 rounds (6 calls) | $0.532 | $0.248 | 2.2× |

A "typical" chat turn is **$0.15**, not the $0.018 assumed throughout the
pricing discussion in plan 018. Every allowance number derived from that figure
is roughly 8× too optimistic.

## Finding 2: journaling is comparatively cheap

| Session | Uncached | Cached |
|---|---|---|
| 8-turn | $0.161 | $0.101 |
| 20-turn | $0.602 | $0.450 |
| 35-turn | $1.486 | $1.221 |

Still the most expensive *single interaction*, but a 20-turn journaling session
costs about the same as four busy chat turns — and caching helps it far less
(1.3×) precisely because it has no big tool prefix to cache. Journaling's cost
is real conversation, not overhead.

## Expected cost per subscriber, not per active user

Earlier tables in this plan described an *active* user (60 chats + 8 journaling
sessions/month) and loosely called that "regular". It isn't — it is roughly the
top fifth of a base. Across a realistic mix of subscribers, including those who
never touch the assistant:

| Segment | Share | Cost/month |
|---|---|---|
| Never touches AI | 25% | $0.00 |
| Tries it, drifts off | 25% | $0.27 |
| Light | 25% | $1.19 |
| Regular | 17% | $3.72 |
| **Heavy** | 8% | **$13.47** |
| **Expected per subscriber** | | **$2.08 (26% of $8)** |

**$2.08 average is survivable. The 8% heavy user at 168% of revenue is not.**
That is what an allowance exists to bound — not the average, which takes care of
itself.

## What this means monthly, per active household

| Usage | Cached | Uncached |
|---|---|---|
| Light — 20 chats, 2 journals | $1.93 (24% of $8) | $4.13 (52%) |
| Regular — 60 chats, 8 journals | **$6.68 (84%)** | $13.59 (170%) |
| Heavy — 150 chats, 30 journals | $21.21 (265%) | $39.99 (500%) |

**A merely *regular* user consumes 84% of an $8 plan even with caching.** That is
the number that should drive both the engineering work and the pricing.

---

## Finding 3: prompt caching is not implemented

`cache_control` / `ephemeral` appears nowhere in `api/src/life_dashboard/ai/`.

### What implementing it takes

The architecture is clean and the change is contained to `provider.py`.

1. **Cache the tool array.** Anthropic caches a prefix in the order
   *tools → system → messages*. Marking the final entry of the tools list with
   `cache_control: {"type": "ephemeral"}` caches all ~15.6k tokens of schema.
   Biggest single win.
2. **Cache the system prompt.** `stream_chat` currently passes `system` as a
   plain string. Change to a content-block list:
   ```python
   system=[{"type": "text", "text": system,
            "cache_control": {"type": "ephemeral"}}]
   ```
   `_build_system_prompt` / `_build_journal_system_prompt` output is stable
   within a conversation, so this caches cleanly.
3. **Optionally cache the message prefix.** Messages are currently
   `{"role": ..., "content": "<str>"}`; adding a breakpoint requires converting
   the marked message's content to a block list. Anthropic allows four
   breakpoints total. Do this second — the tool array is where the money is.
4. **Record cache hits.** `AiUsage` has `input_tokens` / `output_tokens` but no
   cache columns. Add `cache_creation_input_tokens` and `cache_read_input_tokens`
   (migration parenting on head 0053) so the benefit is measurable rather than
   assumed.

**Caveats worth knowing before building:**

- Cache *writes* cost 1.25× normal input. A one-shot question that never gets a
  second turn is slightly **more** expensive with caching on. The tables above
  assume multi-call turns, where it pays off immediately.
- Default TTL is 5 minutes. Fine for an active chat; a journaling session with
  long pauses may expire between turns. A 1-hour TTL exists at a higher write
  premium — worth measuring before choosing.
- Nothing user-visible changes, so this can ship without any product decision.

**Estimated effort:** ~30 lines in `provider.py` for steps 1–2, plus a small
migration for step 4. Half a day to a day including tests that assert
`cache_read_input_tokens > 0` on a second turn.

## Finding 4: tool subsetting — DOWNGRADED, do caching first and re-measure

**Correction 2026-07-22.** This section originally called tool subsetting "the
bigger lever". That was true *before* caching. After caching it is not.

Post-caching breakdown of a $0.034 chat turn (Sonnet 5, 2 rounds):

| Component | Cost | Share |
|---|---|---|
| Cached prefix (tools + system) | $0.0070 | 21% |
| Fresh history + accumulated tool results | $0.0172 | **50%** |
| Output tokens | $0.0100 | 29% |

Caching already reduces the 15.6k tool array to a $0.20/M cache read. **Tool
subsetting would now save roughly $0.003 per turn** — real, but no longer the
headline, and it carries product risk (wrong subset → missing tool).

**The levers that actually matter after caching**, measured against a heavy user
($13.47/month):

| Change | Result | Cut |
|---|---|---|
| `_CONTEXT_MESSAGE_LIMIT` 20 → 10 | $9.87 | 27% |
| + trim tool result payloads (−40% fresh input) | $9.23 | 31% |
| + shorter replies (500 → 300 output tokens) | $7.63 | 43% |
| + Haiku for journaling | $5.72 | 58% |
| *or simply* cap at 150 turns/month | $5.13 | — |

Notes on the trade-offs:
- **History limit is not free** — halving it means the assistant forgets earlier
  in a conversation. Real product cost, needs judgement.
- **Trimming tool results is nearly free.** A `list_*` tool returning 50 rows
  when 10 would do is pure waste, and every row gets re-sent on every subsequent
  round of the tool loop. Best effort-to-value ratio on the list.
- **Shorter replies are arguably better UX.** "Added milk to the list" does not
  need 500 tokens.

## Finding 4b (superseded): the original tool-subsetting argument

Caching makes the 15.6k tool payload 10× cheaper. **Not sending it makes it
free.** Shipping all 66 tools on a question like "how did I sleep last week"
is pure waste.

Options, roughly in order of effort:

1. **Subset by conversation kind.** Journal mode already does this — it passes
   one tool. The same pattern could apply elsewhere (a budget-focused
   conversation doesn't need recipe tools).
2. **Two-stage routing.** A cheap Haiku call classifies intent, then the Sonnet
   call carries only that category's tools. Adds latency and a failure mode
   (wrong category → missing tool), so it needs a fallback that retries with the
   full array.
3. **Trim the schemas.** 725 tokens for a single tool description is a lot.
   A pass over the largest definitions may recover meaningful tokens for no
   architectural change.

Combined with caching, this is where the cost curve actually bends.

## Finding 5: routing already half-exists

`provider.py` defines `CHAT_MODEL = "claude-sonnet-4-6"` and
`FAST_MODEL = "claude-haiku-4-5-20251001"`. `FAST_MODEL` already serves
background work — journal signal extraction, memory refresh, the credential
probe. `stream_chat` hardcodes `CHAT_MODEL`.

**To route interactively:** add a `model` parameter to `stream_chat` and pass it
from `generate_stream`. Mechanically trivial. What is *not* trivial is the
policy — which turns deserve the cheaper model. That is a quality judgement, and
given tool payload is the dominant term, model choice is the smaller lever.
**Do caching and subsetting first.**

## Finding 5b: model selection — and a dated pricing opportunity

Rates per Anthropic's published table, fetched 2026-07-22 ($/M tokens):

| Model | Input | Cache hit | Output |
|---|---|---|---|
| Haiku 4.5 | $1 | $0.10 | $5 |
| **Sonnet 5** (through **31 Aug 2026**) | **$2** | **$0.20** | **$10** |
| Sonnet 5 (from 1 Sep 2026) | $3 | $0.30 | $15 |
| Sonnet 4.6 — *current `CHAT_MODEL`* | $3 | $0.30 | $15 |
| Opus 4.8 | $5 | $0.50 | $25 |

**Sonnet 5 is currently 33% cheaper than the Sonnet 4.6 we're on, and reverts to
exactly the same price on 1 September.** Switching is a newer model at a
temporary discount and price parity thereafter — a one-line change in
`provider.py`. There is no scenario where staying on 4.6 is better.

Cost per interaction, with caching (see plan 020):

| Model | Chat turn | Journal turn | 60 chats + 8 journals/mo |
|---|---|---|---|
| Haiku 4.5 | $0.017 | $0.008 | $2.35 |
| **Sonnet 5** (promo) | $0.034 | $0.017 | **$4.70** |
| Sonnet 4.6 | $0.051 | $0.025 | $7.06 |
| Opus 4.8 | $0.086 | $0.041 | $11.76 |

### Recommendation by mode

- **Tool-using chat → Sonnet 5.** Selecting correctly from 66 tools and
  extracting parameters is demanding, and the failure mode is *writing wrong
  data into someone's household records* — a correctness problem, not a quality
  preference. Haiku is $1/household/month cheaper; that is cheap insurance to
  decline.
- **Journaling → Sonnet 5.** Haiku would save ~$1.30/household/month, but
  attunement *is* the feature, and it is used by people having a hard week.
  Degrading it is a bad trade commercially (it's the differentiator) and worse
  than that for the person. Worth A/B-ing personally before accepting this —
  quality here is subjective and Brandon is the target user.
- **Background structured work → Haiku, as now.** Journal signal extraction,
  auto-titling, memory refresh. Extraction into a fixed shape is exactly Haiku's
  job.
- **Consider Opus for profile synthesis.** It runs ~4×/month and its output is
  injected into every subsequent conversation. Opus costs $0.36/month vs $0.14
  on Sonnet — **$0.22 to improve the context quality of every interaction
  downstream.** Probably the best-value upgrade in the system.

**The principle: spend where the output is reused, save where it's disposable.**

Footnote: Haiku's cache floor is 4,096 tokens and journal mode's prefix is only
~2,800 (300 tools + 2,500 system), so a Haiku journaling path would silently get
no caching. The effect is small (~$0.0025/turn) because the journal prefix is
small anyway, but it erodes part of the apparent saving.

## Finding 6: usage is already instrumented

`AiUsage` (`ai/models.py`, via `service.record_usage`) records per-call
`input_tokens`, `output_tokens`, `model`, `conversation_id`, and `turn_kind`.

Plan 018's usage distribution was invented and flagged as its weakest
assumption. **It doesn't have to be.** Query this table grouped by user and
`turn_kind` to get the real shape, including how much of the cost is journaling
versus tool-using chat.

---

## Metering unit

"Messages" is the legible unit for a household but hides an ~8× spread between a
simple question and a five-round tool loop. Recommendation:

- **Count turns**, not sessions or API calls. A user says one thing → one turn,
  regardless of how many rounds it took internally. Honest from the user's side,
  and it stops the tool loop being a hidden multiplier they can't see or control.
- **Degrade, don't cut off.** At the ceiling, drop to `FAST_MODEL` for the rest
  of the month. This matters especially for journaling — a paywall appearing
  mid-session, in a feature people use when they're struggling, is a genuinely
  bad outcome and not merely a poor UX moment.
- **Show the gauge in Settings** before anyone approaches the limit.

## Should journaling be a paid add-on?

**On these numbers, no.** It was a strong candidate when it looked like the
dominant cost; it isn't. Regular tool-using chat costs more in aggregate, and
gating journaling would paywall the most emotionally distinctive feature while
leaving the actual cost driver unmetered.

There is also a framing problem worth naming: the coach is CBT-aware, and
"pay extra to talk about your feelings" is a bad look — and a worse experience
for someone who reaches for it during a hard week.

**If AI needs its own revenue line, sell "AI Unlimited" rather than "Journaling."**
Everyone gets the feature and discovers whether they want it; heavy users
self-select into paying for what they cost; nobody is locked out of an
emotional-support feature by a billing state. Same cost recovery, better framing.

---

## Sequence

1. **Prompt caching** (`provider.py`) — 2–3× on chat, no product risk, no user-visible change.
2. **Query `AiUsage`** — replace plan 018's invented distribution with measured data.
3. **Tool subsetting** — the larger structural win once caching is in.
4. **Decide the metering unit** (recommend: turns) and build the Settings gauge.
5. **Then, and only then**, put an AI number on the pricing page.

## Done when

- A typical tool-using chat turn costs ~$0.05 rather than ~$0.15.
- `AiUsage` records cache reads/writes, and they are non-zero in practice.
- Real per-user percentiles exist, split by `turn_kind`.
- A user can see their remaining allowance before hitting it.
- The pricing-page allowance is derived from measurement, not estimate.
