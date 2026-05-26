# Evolution Log

Audit trail of /evolve runs. Records proposals, approvals, and rejections.
Prevents the system from re-proposing rejected rules.

---

<!-- Format for each entry:

=== DATE — Session N ===
Corrections in period: N
Observations in period: N

PROPOSED:
- [action]: [rule text]
  Evidence: [source and count]
  Destination: [where]
  Decision: approved | rejected | modified
  Notes: [if rejected or modified, why]

APPLIED:
- [what was actually changed]

-->

=== 2026-05-26 — Initial harness setup ===
Corrections in period: 0 (system initialization)
Observations in period: 2 (from initial verification sweep)

INITIAL SWEEP FINDINGS:
- "custom" frequency rule was too strict — habits/schemas.py still has it in the Literal type.
  Rule updated to: "exists in Literal but has no parser implementation"
  The check now targets service.py only, not the schema file.

- Hardcoded Tailwind color utilities found in budget/ pages (bg-amber-50, bg-green-500/80, bg-red-400/80).
  These are pre-existing violations, not new regressions.
  Added as a known-exception entry in learned-rules.md so the sweep doesn't false-alarm.
  Action: do not replicate in new code; defer cleanup to a dedicated theming pass.

APPLIED:
- Updated "custom frequency" learned rule to reflect reality
- Added pre-existing budget color violations as a documented exception

=== 2026-05-26 — Fixing initial sweep violations ===
Corrections in period: 0
Observations in period: 2 (from sweep + investigation)

FIXES APPLIED:

1. HabitFrequency "custom" in input schemas
   Problem: HabitFrequency Literal included "custom" on HabitCreate and HabitUpdate,
   meaning the API would accept "custom" as valid input despite having no parser.
   Fix: Split into HabitFrequencyInput = Literal["daily","weekly","monthly"] for
   input schemas, keeping full HabitFrequency (with "custom") on response schemas
   only for backwards-compat with legacy DB rows.
   Frontend habit-sheet.tsx already coerced "custom" → "monthly" when opening the
   edit form, so no frontend change needed.
   File: api/src/life_dashboard/domains/habits/schemas.py

2. Hardcoded Tailwind green/red/amber in budget pages
   Problem: 39 instances across budget/page.tsx, budget/import/page.tsx, and
   budget/categories/[id]/page.tsx using raw Tailwind color scale utilities that
   break theme switching.
   Fix: Added --budget-positive/negative family CSS variables to globals.css
   (:root and .dark blocks), plus utility classes (.text-budget-positive,
   .text-budget-negative, .bg-budget-*, .border-budget-*, .dot-budget-*,
   .text-warning, .bg-warning). Replaced all 39 instances across 3 files.
   Dark-mode overrides baked into CSS variables — no dark: prefix needed in JSX.
   File: web/src/app/globals.css + 3 budget TSX files

LEARNED RULES UPDATED:
- Removed pre-existing-violations exception for budget colors (fixed)
- Corrected HabitFrequency rule to reflect the input/response split
- Added budget semantic color rule to learned-rules.md
