# Memory System

This directory is the coding agent's learning infrastructure. It captures observations, corrections, and graduated rules across sessions.

## How it works

```
Session start
    │
    ▼
VERIFICATION SWEEP   ← Runs every rule's verify: check silently
    │
    ▼
Session activity
    │
    ▼
observations.jsonl   ← Verified discoveries (not guesses)
corrections.jsonl    ← User corrections with auto-generated verify: checks
violations.jsonl     ← Rule violations caught by sweep
sessions.jsonl       ← Session scorecards and trend data
    │
    ▼
/evolve              ← Periodic review (run manually, ~every 10 sessions)
    │
    ▼
learned-rules.md     ← Graduated patterns WITH verify: checks
    │
    ▼
.claude/rules/       ← Promoted to permanent path-scoped rules
```

## File purposes

### observations.jsonl
Append-only. One JSON object per line. Claude writes here when it discovers something non-obvious and verifiable about the codebase.

```json
{"timestamp": "2026-05-26T14:30:00Z", "type": "convention", "hypothesis": "All service functions return None (not raise) when entity not found", "evidence": "Grep confirmed: 12 service functions, 0 raise HTTPException in service layer", "counter_examples": 0, "confidence": "confirmed", "file_context": "api/src/life_dashboard/domains/*/service.py", "verify": "Grep('raise HTTPException', path='api/src/life_dashboard/domains/*/service.py') → 0 matches"}
```

Types: `convention`, `gotcha`, `dependency`, `architecture`, `performance`, `pattern`
Confidence: `low` (inferred), `medium` (observed once), `high` (observed multiple times), `confirmed` (verified with grep)

### corrections.jsonl
Append-only. Claude writes here when the user corrects its behavior.

```json
{"timestamp": "2026-05-26T16:00:00Z", "correction": "Don't add cursor-pointer to buttons — globals.css already handles it", "context": "Was adding cursor-pointer to a Button component", "category": "style", "times_corrected": 1, "verify": "Grep('cursor-pointer', path='web/src/components/') → 0 matches"}
```

Categories: `style`, `architecture`, `security`, `testing`, `naming`, `process`, `behavior`

### violations.jsonl
Append-only. Records every rule violation caught by the verification sweep. Recurring violations across sessions are strong candidates for graduation from `learned-rules.md` to a path-scoped `.claude/rules/` file.

### sessions.jsonl
One entry per session. Tracks corrections received, rules checked/passed/failed, observations. Used for trend detection.

### learned-rules.md
Curated rules that graduated from observations and corrections. Loaded once per session at startup. Max 60 lines — forces graduation to rules files or pruning.

### evolution-log.md
Audit trail of every `/evolve` run. Records what was proposed, approved, rejected, and why. Prevents re-proposing rejected rules.

## Promotion ladder

| Signal | Destination |
|--------|------------|
| Corrected once | corrections.jsonl (logged) |
| Corrected twice, same pattern | learned-rules.md (auto-promoted with verify:) |
| Observed 3+ times, confirmed | learned-rules.md (via /evolve) |
| In learned-rules 10+ sessions, always followed | Candidate for .claude/rules/ file |
| Recurring violation (same rule fails multiple sessions) | Must graduate to .claude/rules/ file |
| Rejected during /evolve | evolution-log.md (never re-proposed) |

## .gitignore recommendation

Add to `.gitignore`:
```
.claude/memory/observations.jsonl
.claude/memory/corrections.jsonl
.claude/memory/violations.jsonl
.claude/memory/sessions.jsonl
```

Commit: `learned-rules.md` and `evolution-log.md` (curated team knowledge).
Do not commit: the raw signal files (personal session data, can grow large).
