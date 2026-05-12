# Roadmap

Implementation details for everything in **Completed** live in the `CLAUDE.md` hierarchy — this file tracks direction, not architecture.

---

## Completed

Self-hosted stack is fully running (Docker on NAS + Tailscale + Caddy TLS).

- **Auth** — JWT access/refresh tokens, httpOnly cookies, argon2, first-run bootstrap
- **Shell** — responsive sidebar with drag-to-resize, command palette (⌘P), themed scrollbars; ⌘P searches all nav items regardless of sidebar visibility
- **Theme system** — palette presets (light + dark), per-variable CSS customization, synced to user profile
- **Sidebar customization** — show/hide/reorder nav items, collapsible folder groups (SVG icon picker, drag-to-reorder, contents management), persisted to user profile
- **Settings page** — left-nav shell with Appearance, Navigation (sidebar customizer), Account, Household, and AI tabs
- **Documents** — hierarchical page tree (collapse state persisted), BlockNote rich-text editor, document icons (emoji), drag-to-resize panel
- **Notion import** — HTML + markdown zip; toggle lists, page icons, inter-page link rewriting
- **Recipes** — full UI: card grid, detail page, sheet (create/edit/delete), ingredients, steps, notes, rich-text body (BlockNote), tags, cover images stored locally, URL import via Schema.org JSON-LD
- **Notes / Zettelkasten** — atomic notes, tags (many-to-many), `[[wikilink]]` backlinks, graph view (force-directed), tag browser, full-text search including BlockNote JSON content; bulk delete; full CRUD UI
- **Contacts** — full CRUD contact list
- **Workouts** — full gym-use-case UI: immediately persists on "Start workout", per-exercise per-set data model (`sets: [{weight_lbs, reps}]`), debounced auto-save for all fields, save status badge per exercise, bulk delete
- **AI assistant** — SSE streaming chat, conversation history with sidebar, markdown rendering, tool use (read + write: workouts, todos, habits, goals, notes, calendar events, recipes, documents, contacts, grocery lists), `create_workout` / `delete_workout` write tools for data migration, BYOK (Anthropic key), conversation memory
- **AI panel** — ⌘K slide-out panel from anywhere in the app, draggable left-edge resize (persisted), conversation popover in panel header, full-page fallback at `/ai`
- **Image upload** — inline media attachments in BlockNote editor (documents + recipes); backend upload router with UUID-based flat storage, Docker-volume-mounted; wired into `uploadFile` on all BlockNote instances
- **Todos** — full CRUD UI: active/all/done filters, quick-add, TodoSheet for create/edit, per-item completion toggle
- **Habits** — full CRUD UI: active/all/inactive filters, HabitSheet for create/edit, daily completion tracking

---

## In progress

- **Workouts data migration** — 2026 workout logs exist as documents; AI `create_workout` tool is ready to migrate them with per-set data preservation

---

## Near-term

### Workouts polish
- [ ] Exercise summary shown on the workout list card (e.g. "Bench · Squat · Deadlift")
- [ ] Volume/progress charts — weight over time per exercise, weekly volume
- [ ] Exercise name autocomplete from past entries (avoids typo-induced duplicates)
- [ ] Workout templates — save a session as a template to reuse

### Documents & Notes
- [x] **Focus mode** — toggle that collapses all left-hand sidebars off-screen, leaving only the writing surface; keyboard shortcut (⌘⇧F)
- [ ] Archive/delete individual pages
- [ ] Drag-to-reorder pages in the tree
- [ ] Inline image upload in BlockNote editor

### Calendar
- [x] Month view with day-click detail sidebar, event chips, prev/next navigation
- [x] Event creation and editing via sheet (title, date, time, all-day, location, description)
- [x] Event deletion with confirm step
- [ ] Week / day views
- [ ] Recurrence UI (rrule entry)
- [ ] Member assignment on events

### AI
- [x] `create_note` / `update_note` write tools
- [ ] `create_todo` write tool
- [ ] Scheduled AI summaries (e.g. weekly digest, habit nudges)
- [ ] Audit log for AI-triggered writes shown in chat

---

## Medium-term

### Core domain UIs (polish pass)
1. **Tasks (Todos)** — basic UI exists; needs due dates, recurrence, priority, and richer filters
2. **Habits** — basic UI exists; needs streak tracking, completion calendar heatmap, frequency config
3. **Goals** — progress tracking, milestones, task linking
4. **Grocery Lists** — linked to recipes, household-shared, check-off UX

### Household multi-member
- [ ] Invite flow — create additional accounts in a household
- [ ] Role enforcement in UI (owner vs member)
- [ ] Per-member views for tasks and habits

### Search
- [ ] Full-text search across documents and notes (Postgres `tsvector`)
- [ ] Command palette integration — search content, not just nav items

### Mobile
- [ ] Mobile-responsive audit — test and fix core pages on small screens
- [ ] PWA manifest + service worker for home screen install

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

---

## Deferred indefinitely

- Real-time collaborative editing
- Inter-household sharing
- Payments infrastructure (until cloud tier is ready to launch)
- Deep third-party integrations with ongoing operational cost (until premium tier exists to fund them)
