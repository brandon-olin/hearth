---
name: evolution-engine
description: >
  Autonomous learning and verification system for the Hearth coding agent. Triggers on:
  - Session start (verification sweep of all learned rules)
  - User corrections ("no", "wrong", "we don't do that", "I told you")
  - Task completion (session scoring)
  - Discoveries during work (hypothesis verification)
  - User explicit ("remember this", "add this as a rule")
allowed-tools: Read, Write, Edit, Grep, Glob, Bash
---

# Evolution Engine

You are not a journal. You are an immune system. You verify, enforce, and learn.

---

## SECTION 1: VERIFICATION SWEEP (run at session start)

Before starting any complex task, run every learned rule's verification check silently. Only surface failures.

### Protocol

Read `.claude/memory/learned-rules.md`. For every rule that has a `verify:` line:
1. Execute the check (Grep, Glob, or Read).
2. **PASS** → silent. Move on.
3. **FAIL** → log to `.claude/memory/violations.jsonl`:
   ```json
   {"timestamp": "[now]", "rule": "[rule text]", "check": "[what was run]", "result": "[what was found]", "file": "[where]", "auto_fixed": false}
   ```
   Surface the violation:
   ```
   RULE VIOLATIONS DETECTED:
   - [rule]: found [violation] in [file:line]
     fix: [specific fix]
   ```

If ALL checks pass, say nothing. The best immune system is invisible.

Track pass rates in `.claude/memory/sessions.jsonl`:
```json
{"date": "[today]", "rules_checked": 8, "rules_passed": 8, "rules_failed": 0, "violations": []}
```

### Rules without verification

If a rule has no `verify:` line, add one. If you cannot write a machine-checkable test for a rule, the rule is too vague. Rewrite it until you can. Verification patterns:
- Code pattern banned: `Grep("[pattern]", path="[scope]") → 0 matches`
- Code pattern required: `Grep("[pattern]", path="[scope]") → 1+ matches`
- File must exist: `Glob("[pattern]") → 1+ matches`

---

## SECTION 2: HYPOTHESIS-DRIVEN OBSERVATIONS

Never log a guess. Verify it immediately or don't log it.

### Protocol

When you notice a pattern during work:

1. Formulate as a testable claim. Not "I think service functions return None on missing" — but "All service functions return `None` (not raise) when an entity is not found."

2. Test it immediately. Grep for counter-examples. Count occurrences vs exceptions.

3. Record with evidence to `.claude/memory/observations.jsonl`:
   ```json
   {
     "timestamp": "[now]",
     "type": "convention",
     "hypothesis": "[testable claim]",
     "evidence": "[what grep found]",
     "counter_examples": 0,
     "confidence": "confirmed",
     "file_context": "[relevant file]",
     "verify": "Grep('[pattern]', path='[scope]') → [expected result]"
   }
   ```

4. **Auto-promote confirmed observations** (0 counter-examples, confidence "confirmed"):
   - Add directly to `learned-rules.md` with a `verify:` line
   - Tell the user: "Verified and added as rule: [rule]. Check: [verify pattern]."

Types: `convention`, `gotcha`, `dependency`, `architecture`, `performance`, `pattern`

---

## SECTION 3: CORRECTION CAPTURE

When the user corrects you:

1. Acknowledge naturally.

2. Log to `.claude/memory/corrections.jsonl`:
   ```json
   {
     "timestamp": "[now]",
     "correction": "[what]",
     "context": "[what you were doing when corrected]",
     "category": "[style | architecture | security | testing | naming | process | behavior]",
     "times_corrected": 1,
     "verify": "[auto-generated grep check, or 'manual' if not greppable]"
   }
   ```

3. Generate a `verify:` pattern immediately. If the correction is "don't do X", the check is `Grep("[X pattern]") → 0 matches`. If you cannot generate a check, note `"verify": "manual"` — this is debt to resolve during `/evolve`.

4. Promotion rules:
   - **1st time** → log only
   - **2nd time (same pattern)** → auto-promote to `learned-rules.md` with a `verify:` line. Tell the user.
   - **Already in learned-rules** → check if `verify:` exists. If not, add it now.

5. Apply the correction immediately. Don't just log it.

---

## SECTION 4: SESSION SCORING

When wrapping up a session, write a scorecard to `.claude/memory/sessions.jsonl`:
```json
{
  "date": "[today]",
  "session_number": "[increment from previous]",
  "corrections_received": 0,
  "rules_checked": 8,
  "rules_passed": 8,
  "rules_failed": 0,
  "violations_found": [],
  "violations_fixed": [],
  "observations_made": 1,
  "observations_verified": 1,
  "rules_added": 0
}
```

### Trend detection

If `sessions.jsonl` has 5+ entries, check:
- **Corrections decreasing?** System is working.
- **Corrections flat or increasing?** Rules aren't specific enough or not being consulted. Flag for `/evolve`.
- **Same violation recurring?** Needs to graduate from `learned-rules.md` to a path-scoped rules file (rules files re-inject on every tool call; `learned-rules.md` only loads once per session).
- **Rules count growing past 50?** Warn that graduation to rules files is needed.

Surface trend in one line: "Session 7: 1 correction (down from 3 avg). 9/9 rules passing."

---

## SECTION 5: EXPLICIT "REMEMBER THIS"

When the user asks you to remember something:

1. Rewrite it as a testable rule.
2. Generate a `verify:` pattern.
3. Add to `learned-rules.md`:
   ```
   - [Rule text]
     verify: [check]
     [source: user-explicit, DATE]
   ```
4. Confirm: "Added rule: [rule]. Verification: [check]. Will auto-enforce from now on."

If you cannot make it machine-checkable: "Added as manual rule. I'll follow it but can't auto-verify. Consider rephrasing so I can write a grep check."

---

## Hearth-specific correction categories to watch for

These are the patterns most likely to be corrected in this codebase. Extra vigilance warranted:
- Missing `household_id` filter on a query → `security` category
- Logic placed in router instead of service → `architecture` category
- State transition without atomicity → `architecture` category
- Hardcoded color in JSX → `style` category
- Raw fetch to `/api/` instead of `$api` → `architecture` category
- `useParams` on dynamic route instead of `useSegmentId` → `architecture` category
- Reading JSONB sub-field without `.get()` or `or {}` → `behavior` category

---

## Capacity management

Before adding to `learned-rules.md`:
1. Count lines. Max 60.
2. If approaching 60, check which rules have passed 10+ consecutive sessions → candidates for graduation to rules files.
3. Suggest `/evolve` if at capacity.

A rule without a verification check is a wish. A rule with one is a guardrail. Only guardrails survive.
