# Roadmap

Implementation details for everything in **Completed** live in the `CLAUDE.md` hierarchy — this file tracks direction, not architecture.

---

## Completed

Self-hosted stack is fully running (Docker on NAS + Tailscale + Caddy TLS).

- **Auth** — JWT access/refresh tokens, httpOnly cookies, argon2, first-run bootstrap
- **Shell** — responsive sidebar with drag-to-resize, command palette (⌘P), themed scrollbars; ⌘P searches all nav items regardless of sidebar visibility
- **Theme system** — palette presets (light + dark), per-variable CSS customization, synced to user profile; CSS variable-based badge system (`badge-primary`, `badge-neutral`, `badge-warning`, `badge-progress`, `badge-success`, `badge-error`)
- **Sidebar customization** — show/hide/reorder nav items, collapsible folder groups (SVG icon picker, drag-to-reorder, contents management), persisted to user profile
- **Settings page** — left-nav shell with tabs ordered: Household, Account, Navigation, Appearance, AI; Household tab hidden for non-admin users
- **Documents** — hierarchical page tree (collapse state persisted), BlockNote rich-text editor, document icons (emoji), drag-to-resize panel, focus mode (collapses sidebars), inline image/media upload
- **Notion import** — HTML + markdown zip; toggle lists, page icons, inter-page link rewriting
- **Recipes** — full UI: card grid, detail page, sheet (create/edit/delete), ingredients, steps, notes, rich-text body (BlockNote), tags, cover images stored locally, URL import via Schema.org JSON-LD; server-side search (debounced), multi-tag filter (combobox, OR logic), pagination (24/page)
- **Notes / Zettelkasten** — atomic notes, tags (many-to-many), `[[wikilink]]` backlinks, graph view (force-directed), tag browser, full-text search including BlockNote JSON content; bulk delete; full CRUD UI
- **Contacts** — full CRUD contact list
- **Workouts** — full training domain (workouts-001…005, migrations 0048–0049). Exercise catalog (~60 seeded globals plus household-created), workout templates with superset groups and drag-to-reorder, session logging with per-user ghost values and a rest timer, progress tracking (max weight, Epley 1RM, volume, failed-set markers), and calendar integration. Sets are first-class rows; the legacy `workouts`/`exercise_entries` tables were retired in 0049. Sessions are personal (owned by `created_by_user_id`, never shown to other members); the exercise catalog and templates are household-shared
- **Calendar** — month view with day-click detail sidebar, event chips, prev/next navigation; event creation/editing via sheet (title, date, time, all-day, location, description); event deletion with confirm step
- **AI assistant** — SSE streaming chat, conversation history with sidebar, markdown rendering, tool use (read + write: workouts, todos, habits, goals, notes, calendar events, recipes, documents, contacts, grocery lists), BYOK (Anthropic key), conversation memory
- **AI panel** — ⌘K slide-out panel from anywhere in the app, draggable left-edge resize (persisted), conversation popover in panel header, full-page fallback at `/ai`
- **Todos** — full CRUD UI: active/all/done filters, quick-add, TodoSheet for create/edit, per-item completion toggle, sort control; **recurrence** (daily, weekdays, weekly, monthly_date, monthly_weekday, yearly with configurable interval and end date — auto-spawns next instance on completion)
- **Habits** — full CRUD UI: table view with streak + 7d/30d completion rates, HabitSheet for create/edit; **streak tracking** (current streak + completion rates); **frequency config** (daily/weekly/monthly, day-of-week picker Sun-first, times per period, start date); **page links** (each habit can link to any app page — tapping the habit name navigates, tapping the circle completes); week tracker in sheet with ←/→ navigation
- **Back navigation** — all detail pages (projects, recipes, collections, sub-projects) have back buttons that respect parent hierarchy
- **Household management** — Settings → Household: rename household (admin/owner only), add members by email with role picker (admin/member/viewer), inline member list with role badges; new accounts provisioned with default password for dev ease, email invitations deferred
- **Role enforcement** — `role` attached on `get_current_user` and returned in `UserResponse`; `ADMIN_ROLES` set gates sensitive UI (Household tab, member management); role badges shown on member list
- **Dev impersonation** — admin can click avatar in sidebar footer to open a member switcher; clicking any member POSTs to `POST /households/dev/impersonate/{id}` and swaps session; amber banner + amber avatar indicate impersonated state; "Back to your account" restores original session; disabled in non-development environments
- **Password change** — Settings → Account: modal with current password verification, new password + confirm fields (visibility toggles), 8-char minimum, inline validation for mismatch
- **Transactional email** (email-001) — Mailgun-backed forgot-password / reset-password flow, verified end-to-end against live credentials 2026-07-20
- **Outbound webhooks** (webhook-001, migration 0050) — semantic event layer riding the existing commit-time plumbing, member-owned subscriptions filtered through the single `events/scope.py` `can_see`, HMAC-signed at-least-once delivery with backoff and auto-disable, central payload allowlist in `webhooks/summaries.py`. Makes Hearth an event source, mirroring the Home Assistant inbound path
- **Schema/model reconciliation** (schema-001, ADR-015, migration 0047) — native Postgres enums converted to VARCHAR + CHECK so `create_all` and migration-replay produce identical schemas; closes the drift class behind the 0046 deploy failure

---

## In progress

- **Workouts data import** — 2026 workout logs still live as documents (and in Notion). Now that the session model exists (workouts-001), importing them means creating `workout_sessions` + `session_exercises` + `workout_sets` and resolving each free-text exercise name against the catalog. The AI workout tools were rebuilt in 0048/0049, so the original `create_workout` plan needs revisiting against the new tool surface. Still deprioritized — start fresh, import later.

---

## Near-term

### Todos polish
Core CRUD, sort, and recurrence are complete. Remaining:
- [ ] Due dates — date picker on TodoSheet, sorting/filtering by due date
- [ ] Priority levels (low / medium / high / urgent) — chip on cards, filter/sort
- [ ] Richer filters — filter by project, assignee, priority, due date range
- [ ] Assignee — assign todos to household members

### Habits polish
Streak tracking, frequency config, and page links are complete. Remaining:
- [ ] Completion calendar heatmap — GitHub-style grid per habit (the sheet has a week tracker; this is the full per-habit history view)

### Workouts polish
Most of this section shipped in workouts-001…005 (see Completed):
- [x] Volume/progress charts — shipped as workouts-004 (max weight, Epley 1RM, volume, failed sets)
- [x] Workout templates — shipped as workouts-002, plus the save-as-template prompt in workouts-003
- [x] Exercise name autocomplete — superseded by the exercise catalog; names are now FK references, so typo-duplicates are structurally impossible
- [ ] Exercise summary on the session list card (e.g. "Bench · Squat · Deadlift") — the catalog makes this cheap now
- [ ] AI workout programming — propose next week's progression from session history. Not yet a `feature_list.json` entry; workouts-001's schema (structured sets, templates, `target_reps`) is the prerequisite and is in place

### Documents & Notes
- [ ] **Document structure decision** — settle whether documents nest inside other documents (current model) or whether there should be a separate folder/collection concept. Affects nav UX significantly; decide before investing more in the page tree.

  Partially worked through 2026-07-20 (not yet decided, but the ground is mapped). Findings: `Collection` currently fuses three independent concerns — membership (`note.collection_id`), blueprint (`Template` + `CollectionTemplate`), and navigation (`show_in_nav`, which `projects` duplicates). Nesting already exists, but at the presentation layer: `SidebarConfig.folders` is a per-user, href-keyed grouping synced to user preferences, not a data-model hierarchy. The frontend already computes a polymorphic `NavItem` from four sources (builtins, collections, pinned projects, pinned documents) in `web/src/lib/sidebar/use-nav-items.ts`. Conclusion so far: collections should stay containers; saved/query views are speculative until something needs cross-cutting queries; the real limitation is `collections.domain` being a closed `('notes','documents')` enum. Open question is whether groupings are a tree (needs `collections.parent_id`) or a graph (tags/views).
- [ ] Archive/delete individual pages
- [ ] Drag-to-reorder / reparent pages in the tree (implemented but click-vs-drag conflict needs resolution after structure decision)

### Calendar
- [ ] Week / day views
- [ ] Recurrence UI (rrule entry)
- [ ] Member assignment on events

### Dashboard
- [x] Editable widget grid — gear/Edit toggle, drag-to-reorder (dnd-kit), remove button per widget
- [x] Column count selector (1–4 columns on desktop; mobile always 1 column)
- [x] Layout persisted server-side in `preferences.dashboard` (syncs across devices)
- [x] Widget types: `todos` (with overdue/today/week/all filter), `habits`, `goal_progress`, `project_progress`
- [x] Add widget sheet — two-step: pick type → configure goal or project if needed
- [ ] Widget colSpan control — let users resize individual widgets (1–N columns)
- [ ] Additional widget types: calendar upcoming events, workout streak, AI coach snippet

### AI
- [ ] Scheduled AI summaries (e.g. weekly digest, habit nudges)
- [ ] Audit log for AI-triggered writes shown in chat

---

## Medium-term

### Goals
- [ ] Progress tracking and milestones UI
- [ ] Task linking — associate todos with a goal

### Grocery Lists
- [ ] Linked to recipes — pull ingredients from a recipe into a list
- [ ] Household-shared lists with check-off UX

### Household multi-member
- [x] Add member flow — create accounts in a household via Settings (email + role; default password for dev; email invite deferred)
- [x] Role enforcement in UI (owner/admin vs member/viewer) — Household tab gated; member management admin-only
- [ ] Per-member views for tasks and habits
- [ ] Invite flow — send email invitation instead of provisioning with default password

### Mobile
- [ ] Mobile-responsive audit — test and fix core pages on small screens
- [ ] PWA manifest + service worker for home screen install

---

## Desktop app (local single-machine tier)

The free local-install path targets non-technical users who can't run a terminal. Distribution model: a single downloadable `.dmg` / installer — drag to Applications, it works.

**Stack decisions:**
- **Tauri** as the desktop shell (uses OS WebView, ~15 MB binary vs Electron's ~180 MB; manages the FastAPI process as a sidecar)
- **SQLite** for the local tier (no database server to manage; scales fine for household data volumes)
- **Postgres** stays for self-hosted NAS and cloud tiers — unchanged
- **Next.js static export** for the bundled frontend (no Node.js runtime at install)
- **PyInstaller** to compile FastAPI into a platform binary for bundling

**Upgrade path:**  
SQLite → Postgres migration is a first-class use case for `pgloader`. JSON/JSONB are wire-compatible. A user paying for cloud hosting gets a guided one-click migration.

**Schema work required before SQLite:**
- Swap `JSONB` → `sqlalchemy.types.JSON` across all models (9 columns, 8 models)
- Swap `UUID` from the Postgres dialect → `sqlalchemy.types.Uuid` (dialect-agnostic; all 15 model files)
- TSVECTOR in AI models: skip for SQLite tier, fall back to LIKE search
- Alembic: dialect-aware migration paths for SQLite vs Postgres

**Two free tiers remain distinct:**
- Single-machine: Tauri app + SQLite (one person or household on one machine)
- Self-hosted NAS: Docker Compose + Postgres (multi-device, multi-member household)

**Tauri routing — resolved (static export quirks):**
All dynamic-route detail pages now work correctly in the Tauri build. Two distinct bugs were fixed:
- *Hard navigation* (direct URL / refresh): Tauri serves the pre-rendered `index` HTML for any UUID path; `useParams()` returns `"index"` instead of the real UUID. Fixed by the `useSegmentId` hook which falls back to `window.location.pathname`.
- *Client-side navigation* (clicking a link): Next.js router fetches RSC payload files for the UUID path; those files don't exist in the static export, causing a fallback to `/`. Fixed by `TauriRscPatch` — a fetch interceptor that rewrites same-origin RSC payload requests for UUID paths to their pre-generated `index` equivalents.

**Remaining Tauri work:**
- [ ] SQLite support (schema work above)
- [ ] PyInstaller sidecar bundling for FastAPI
- [ ] Auto-update mechanism
- [ ] `.dmg` / installer packaging and signing

---

## Later

### Cloud-hosted tier
- Multi-tenant infrastructure, tiered pricing (free self-hosted forever; paid for managed hosting, backups, managed AI)
- Automated backup service, migration path from self-hosted

### Native mobile
- Push notifications, offline support — premium tier

### Integrations
- iCal export for calendar events
- External calendar sync (Google Calendar, etc.) — premium
- Health tracking — Apple Watch (HealthKit), Garmin Connect integration; surface activity, sleep, HRV, and workout data as dashboard widgets and in the Workouts domain

---

## Deferred indefinitely

- Real-time collaborative editing
- Inter-household sharing
- Payments infrastructure (until cloud tier is ready to launch)
- Deep third-party integrations with ongoing operational cost (until premium tier exists to fund them)
