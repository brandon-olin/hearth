# Roadmap

Implementation details for everything in **Completed** live in the `CLAUDE.md` hierarchy — this file tracks direction, not architecture.

---

## Completed

Self-hosted stack is fully running (Docker on NAS + Tailscale + Caddy TLS).

- **Auth** — JWT access/refresh tokens, httpOnly cookies, argon2, first-run bootstrap
- **Shell** — responsive sidebar with drag-to-resize, command palette (⌘P), themed scrollbars
- **Theme system** — palette presets (light + dark), per-variable CSS customization, synced to user profile
- **Sidebar customization** — show/hide/reorder nav items, persisted to user profile
- **Documents** — hierarchical page tree (collapse state persisted), BlockNote rich-text editor, document icons (emoji), drag-to-resize panel
- **Notion import** — HTML + markdown zip; toggle lists, page icons, inter-page link rewriting
- **Stub pages** — Tasks, Habits, Goals, Recipes, Grocery Lists, Workouts, Contacts, Calendar (routes + basic API domains exist, no UI built yet)

---

## In progress

- **Notion import edge case** — checkbox items nested inside toggle blocks trigger a BlockNote `blockContainer` parse error; debug logging added, fix pending

---

## Near-term

### Documents
- [ ] Fix Notion HTML import: checkbox-inside-toggle parse error
- [ ] Image upload — inline media attachments in BlockNote editor
- [ ] Archive/delete individual pages
- [ ] Drag-to-reorder pages in the tree

### Notes / Zettelkasten
- [ ] Notes domain — atomic notes, tags (many-to-many), `[[wikilink]]` backlinks stored in a backlinks table and populated on save
- [ ] Notes UI — tag browser, backlinks panel, visually distinct from Documents

### Calendar
- [ ] Build out the existing stub — event creation, month/week/day views, recurrence, member assignment

### Sidebar folders
- [ ] Single-level folder grouping in sidebar nav (e.g. a "Writing" folder containing Documents, Notes, Journal links)
- [ ] Design TBD: named sections vs collapsible folders, persistence model

### UI polish
- [ ] Compress sidebar — search to icon-only (⌘P trigger), Ask AI + Settings to footer icon buttons
- [ ] Settings page left-nav shell (Appearance, Account, Household sections)

---

## Medium-term

### Core domain UIs (priority order)
1. **Tasks** — full CRUD, due dates, recurrence, member assignment, completion
2. **Habits** — streak tracking, completion calendar, frequency config
3. **Goals** — progress tracking, milestones, task linking
4. **Recipes** — full UI, ingredients, steps, URL import via JSON-LD
5. **Grocery Lists** — linked to recipes, household-shared
6. **Workouts** — log entries, exercise library, strength/cardio metrics

### Household multi-member
- [ ] Invite flow — create additional accounts in a household
- [ ] Role enforcement in UI (owner vs member)
- [ ] Per-member views for tasks and habits

### Search
- [ ] Full-text search across documents and notes (Postgres `tsvector`)
- [ ] Command palette integration

---

## Later

### AI layer (`agent/`)
- MCP server exposing domain services as tools
- Claude integration — household context, task suggestions, weekly summaries
- BYOK configuration (OpenAI, Anthropic key)
- Local LLM option (Ollama)
- Audit log for all AI-triggered writes

### Cloud-hosted tier
- Multi-tenant infrastructure, tiered pricing (free self-hosted forever; paid for managed hosting, backups, managed AI)
- Automated backup service, migration path from self-hosted

### Mobile
- Mobile-responsive polish on existing web app
- Native mobile apps (push notifications, offline) — premium tier

### Integrations
- iCal export for calendar events
- Recipe import from URLs (JSON-LD scraping)
- External calendar sync (Google Calendar, etc.) — premium

---

## Deferred indefinitely

- Real-time collaborative editing
- Inter-household sharing
- Payments infrastructure (until cloud tier is ready to launch)
- Deep third-party integrations with ongoing operational cost (until premium tier exists to fund them)
