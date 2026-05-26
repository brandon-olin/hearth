---
description: Review the evolution system and promote/prune rules. Run after 10+ sessions or when learned-rules.md is getting full.
---

## Current state

### Learned rules
!`cat .claude/memory/learned-rules.md 2>/dev/null || echo "No learned rules yet"`

### Recent corrections (last 30)
!`tail -30 .claude/memory/corrections.jsonl 2>/dev/null || echo "No corrections logged"`

### Recent observations (last 20)
!`tail -20 .claude/memory/observations.jsonl 2>/dev/null || echo "No observations logged"`

### Recent violations (last 20)
!`tail -20 .claude/memory/violations.jsonl 2>/dev/null || echo "No violations logged"`

### Session trend
!`tail -10 .claude/memory/sessions.jsonl 2>/dev/null || echo "No session history"`

### Previous evolution decisions
!`tail -60 .claude/memory/evolution-log.md 2>/dev/null || echo "No evolution history"`

## Your task

You are the meta-engineer. Improve the system that runs the coding agent.

### Step 1: Analyze corrections

Group corrections by pattern. Look for:
- Same correction appearing 2+ times (should already be in learned-rules — if not, promote now)
- Corrections pointing to a gap in the path-scoped rules (`core-invariants.md`, `security.md`, `api-design.md`, `performance.md`, `frontend.md`)
- Corrections that contradict an existing rule (the rule needs updating, not the correction)

### Step 2: Analyze observations

Group by type. Look for:
- High-confidence observations confirmed multiple times
- Observations that match corrections (convergent signals are strongest)
- Hearth-specific gotchas (JSONB patterns, Tauri build quirks, SQLAlchemy async issues) that could prevent future bugs

### Step 3: Audit learned rules

For each rule in learned-rules.md:
- **Still relevant?** Does the codebase still follow this pattern?
- **Graduation candidate?** If it's been in learned-rules 10+ sessions and always followed, propose moving it to a path-scoped rules file or to the root CLAUDE.md
- **Redundant?** Already covered by a rules/ file or already in CLAUDE.md?
- **Too vague?** Can the coding agent actually follow it without interpretation?
- **Missing verify: line?** Every rule needs one — add it

### Step 4: Check violations log

Recurring violations (same rule failing in multiple sessions) are the strongest signal for graduation — they mean the rule needs to be in a path-scoped file that re-injects on every tool call, not just in learned-rules.

### Step 5: Check evolution log

Never re-propose a rejected rule unless you have new evidence. Evolution-log.md is the audit trail.

### Step 6: Propose changes

For each proposal:

```
PROPOSE: [action]
  Rule: [the rule text]
  Source: [corrections / observations / violations / learned-rules]
  Evidence: [why this should change — cite session counts or correction counts]
  Destination: [learned-rules.md | core-invariants.md | security.md | api-design.md | performance.md | frontend.md | CLAUDE.md | DELETE]
```

Categories:
- **PROMOTE** — move from observations to learned-rules
- **GRADUATE** — move from learned-rules to a path-scoped rules file or CLAUDE.md
- **PRUNE** — remove redundant or outdated rule
- **UPDATE** — modify existing rule based on new evidence
- **ADD** — new rule from correction patterns

### Step 7: Wait for approval

List all proposals. Do NOT apply any changes yet.
For each, you will receive: approve, reject, or modify.
Apply only approved changes. Log everything (approved AND rejected) to evolution-log.md.

## Constraints

- Never remove security rules or household scoping rules
- Never weaken idempotency requirements
- Never add rules that contradict the root CLAUDE.md or sub-level CLAUDE.md files
- Max 60 lines in learned-rules.md (force graduation or pruning if full)
- Every rule must be specific enough to test compliance
- Bias toward specificity over abstraction — "always check household_id" is better than "be careful with queries"
