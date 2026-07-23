# 021 — Deferring the conversational journal/coach from Cloud v1

Status: DECIDED 2026-07-22.
**This is a deferral, not a cancellation.** The work is built, passing, and
staying in the repo. What changes is who it is exposed to at launch.

Related: `plans/019-ai-cost-control.md`, `plans/marketing-site-spec.md`,
`docs/ai-coach-redesign.md`.

---

## The decision

The **conversational** journal/coach surface is not offered on Cloud at v1.
Plain journal *writing* stays. The AI conversation partner waits.

Cost was not the deciding factor. Removing it cuts expected AI spend 40%
($2.08 → $1.24 per subscriber, 26% → 15% of an $8 plan) and halves the heavy-user
worst case ($13.47 → $6.85) — welcome, but not why.

**The reason is that an AI conversation partner for someone processing difficult
feelings can cause real harm when it gets a moment wrong, and it has not been
tested enough to know that it won't.** A household app that mishandles a chore is
an annoyance. This is a different category, and it deserves to be treated as one.

## What is built (all passing, all staying)

| Feature | What it does |
|---|---|
| `coach-001` / `001b` | User profile + bootstrap, notes-driven incremental proposer |
| `coach-002` | Journal signal extraction (Haiku, structured) |
| `coach-003` | CBT-aware coach prompt rewrite |
| `coach-004` – `007` | Focus field, silent profile, chat-driven updates, versioning + weekly refresh/decay |
| `journal-001` | Talk-it-out sessions with personalised opener |
| `journal-002` | Check-in modes — Mood, Body, Rant, Day review |

This is a substantial, thoughtfully-built body of work. The prompts show real
care: explicit role-clarity ("NOT a therapist, NOT a friend, NOT a substitute for
the people in your life"), never give unsolicited advice, point at humans for
interpersonal topics, short turns so the user does most of the talking.

## What is missing, specifically

1. **No crisis handling anywhere in `ai/`.** No detection, no escalation path, no
   resource surfacing. Verified by search 2026-07-22.
2. **`rant` mode instructs the model to "stay with them, do NOT reality-test."**
   For ordinary venting this is correct practice — validation before
   problem-solving. For a rumination spiral, expressed hopelessness, or
   self-critical spiralling it is close to the opposite of what helps. It is also
   the mode a person is most likely to choose on their worst day.
3. **Inferred emotional state persists and compounds.** `coach-002` extraction
   writes signals into a profile that `coach-007` versions and that gets injected
   into every subsequent conversation. A misread doesn't just pass — it silently
   shapes everything downstream.
4. **No accumulated evidence that it behaves well**, because it has not been used
   at length by anyone other than its author.

None of these is a design failure. They are the things that only surface through
iteration with real users — which is precisely the argument for not putting it in
front of strangers who bought a household organiser.

## What stays in v1

- **Journal entries as writing** — compose, tag, search, revisit. No inference,
  no conversation, no risk. This is what most people mean by journaling and it is
  genuinely useful on its own.
- **The household assistant** — tool-using chat over household data. Unaffected.

## What is deferred on Cloud

- Talk-it-out conversational mode (`journal-001`, `journal-002`)
- Journal signal extraction (`coach-002`)
- Profile synthesis fed by journal content (`coach-003`, `coach-007`)

**Self-hosted keeps all of it.** Someone running Hearth on their own hardware,
on their own inference, for themselves, with full knowledge it is experimental,
is a categorically different situation from a stranger who paid for a household
app. This is also the population that can keep the iteration going.

Note this inverts the usual open-core direction — self-hosted gets *more* here,
not less. That is deliberate and worth stating plainly rather than hiding: the
difference is informed consent, not tiering.

## The coach is not the same risk as talk-it-out (refined 2026-07-22)

The original framing lumped the dashboard coach in with the conversational
journal. On reflection that is too blunt — they carry different risk, and the
coach is largely salvageable for v1.

**The line that matters: describe the data, don't diagnose the person.**

| Lower risk — shippable | Higher risk — cut or guard |
|---|---|
| Factual reflection: "4 of 5 habits this week, 12-day streak" | Inferring *why*: "you seem to struggle on Mondays — everything ok?" |
| Encouragement tied to observed behaviour | Anything drawn from journal content or narrative signals |
| Forward-looking nudges about tasks and habits | CBT framing applied to someone who didn't ask for therapy |
| Data the user can see for themselves anyway | Persisted inferences about mood, motivation or character |

A coach that says "you did these three, the fourth is still open" is reporting.
A coach that says "you've been avoiding this one" is interpreting — and it is
interpreting a person, from thin evidence, with a memory that compounds.

### One specific hazard worth naming

**Streak and habit framing around food and exercise.** A cheerful coach that
dramatises a broken streak is a known harm pattern in habit apps — it can
reinforce perfectionist and disordered patterns, and it lands hardest on exactly
the people already vulnerable to them. Hearth has `workouts` as a first-class
domain, so this is not hypothetical.

Concrete guards:
- Never dramatise a loss. "3 of 5 this week" not "you broke your 47-day streak".
- No guilt or disappointment register, even lightly. No "try harder tomorrow".
- Treat a missed habit as information, not failure.
- Consider suppressing coach commentary entirely on food- and
  exercise-categorised habits, or keeping it strictly numeric there.

### Proposed v1 coach scope

Shippable on Cloud if it:
1. Draws **only** from structured data — habits, todos, goals, projects. Not
   journal content, not `coach-002` signals, not emotional profile fields.
2. Reports and encourages; never interprets motivation or state.
3. Uses neutral framing on misses, with the food/exercise guard above.
4. Is opt-in and dismissible.

That preserves most of what is valuable — the daily "here's where you are"
digest — and removes the part that requires the app to have opinions about who
you are.

**Note this changes the personal calculus too:** with a narrowed coach shipping
on Cloud, the only thing self-hosted-only is talk-it-out. That is a much smaller
gap than "all coaching", and it is worth deciding on the narrowed scope before
concluding that self-hosting is the only way to keep the feature.

## Conditions for shipping it on Cloud

Not a checklist to rush. Each is a real piece of work:

1. **Crisis detection with a genuine escalation path.** Recognising when someone
   has moved from processing to distress, and responding by pointing at human
   support rather than continuing the conversation.
2. **Accurate, current crisis resources.** These change — organisations
   restructure, helplines get disconnected. Wrong resources are worse than none.
3. **`rant` mode reworked** to distinguish venting from spiralling, and to stop
   validating when validation stops helping.
4. **Sustained real-world use** by the author and a small number of consenting
   testers, long enough to have seen it handle a bad day well.
5. **A considered position on inference persistence** — whether the profile
   should carry emotional inferences at all, how a user reviews and corrects
   them, and how wrong ones get unwound.
6. **Clear in-product framing** that it is a journaling aid, not care, without
   relying on a disclaimer nobody reads.

## Marketing consequences

- `/features` and `/` must not advertise journaling, coaching, or anything
  therapy-adjacent. The AI story at v1 is exactly one sentence: *an assistant
  that knows your household.*
- Do not tease it as "coming soon". A dated promise creates pressure to ship it
  before the conditions above are met, which is the failure mode this decision
  exists to avoid.
- The homepage module grid currently reads "AI assistant — Knows your household",
  which is already correct. No copy change needed; the requirement is not to
  *add* anything.
