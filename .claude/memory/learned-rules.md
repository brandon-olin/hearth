# Learned Rules

Rules graduated from observations and corrections. Loaded at session start.
Max 60 lines. Rules beyond that should be promoted to .claude/rules/ files.
Each rule includes a source annotation and a machine-checkable verify line.

---

- Service functions return `None` when an entity is not found — they do not raise `HTTPException`. Only routers raise HTTP exceptions.
  verify: Grep("raise HTTPException", path="api/src/life_dashboard/domains/*/service.py") → 0 matches
  [source: verified observation, 2026-05-26]

- JSONB sub-fields are always read with `.get()` or `or {}` — never direct index access. The stored data may predate a new sub-field.
  verify: Grep("habit\.cadence\[|todo\.recurring\[|recipe\.ingredients\[", path="api/src/life_dashboard/domains/") → 0 matches
  [source: verified observation, 2026-05-26]

- `_as_aware()` from `auth/service.py` must be used when comparing a DB datetime against `datetime.now(timezone.utc)`. SQLAlchemy can return timezone-naive datetimes from TIMESTAMP WITH TIME ZONE columns.
  verify: manual — review any new datetime comparison in service files
  [source: documented gotcha, api/CLAUDE.md, 2026-05-26]

- `HabitFrequencyInput = Literal["daily", "weekly", "monthly"]` is the type for create/update input. `HabitFrequency` (which includes `"custom"`) is for response schemas only — legacy DB rows may contain `"custom"`, but the API must never accept it as input.
  verify: Grep("frequency: HabitFrequency =|frequency: HabitFrequency \| None", path="api/src/life_dashboard/domains/habits/schemas.py") → 0 matches
  [source: fixed 2026-05-26 — HabitCreate/HabitUpdate now use HabitFrequencyInput]

- Tag filtering joins Tagging with `.distinct()` to prevent duplicate rows when an entity has multiple matching tags. Always add `.distinct()` when joining Tagging with a `.in_()` filter.
  verify: manual — check any new Tagging join has .distinct()
  [source: verified from api/CLAUDE.md, 2026-05-26]

- `useSegmentId` replaces `useParams` on all dynamic-route pages. The Tauri static export serves a sentinel `index.html`; `useParams()` returns `"index"` on hard navigation.
  verify: Grep("useParams<", path="web/src/app/(protected)/") → 0 matches
  [source: verified with grep — passes, 2026-05-26]

- The dev API runs on port 1339 (`make api`) while the always-on launchd service runs on port 1338. `web/.env.local` points to 1339 for local dev. Do not mix these up in env config.
  verify: manual — check API_URL in web/.env.local after any env config change
  [source: verified from api/CLAUDE.md, 2026-05-26]

- Budget pages use semantic CSS utility classes for financial colors — never raw Tailwind green/red/amber. Positive amounts → `text-budget-positive`, negative → `text-budget-negative`, faded negative → `text-budget-negative-faint`, containers → `bg-budget-positive border-budget-positive` / `bg-budget-negative border-budget-negative`, chart dots → `dot-budget-positive` / `dot-budget-negative`, inline warnings → `text-warning bg-warning`. All dark-mode handling is in the CSS variables — no `dark:` prefix needed.
  verify: Grep("bg-(green|red|amber)-|text-(green|red|amber)-|border-(green|red|amber)-", path="web/src/app/(protected)/budget/") → 0 matches
  [source: fixed 2026-05-26 — CSS vars defined in globals.css :root/.dark blocks]

- Day-of-week values: backend stores Mon=0…Sun=6 (Python weekday()), but the frontend displays Sun-first using `DAY_DISPLAY_ORDER = [6, 0, 1, 2, 3, 4, 5]`. Use `DAY_DISPLAY_ORDER[i]` as the actual value when iterating day-picker buttons — do not map display index directly to backend value.
  verify: manual — check any new day-of-week UI component against habit-row.tsx
  [source: verified from web/CLAUDE.md, 2026-05-26]
