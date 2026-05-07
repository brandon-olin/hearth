# Roadmap

## Current state (as of May 2026)

The core infrastructure and several feature domains are fully working in self-hosted mode (Docker on NAS + Tailscale + Caddy TLS).

**Completed:**
- Auth — JWT access tokens, httpOnly refresh cookies, argon2 hashing, first-run bootstrap
- Shell — responsive sidebar nav with drag-to-resize, command palette (⌘P), themed scrollbars
- Theme system — full palette presets (light + dark categories), per-variable color customization, synced to user profile across devices
- Sidebar customization — show/hide and reorder nav items, persisted to user profile
- Documents — hierarchical page tree, BlockNote rich-text editor, drag-to-resize tree panel, markdown import (Notion, Obsidian, Bear, Logseq, and any markdown zip)
- Stub feature pages — Tasks, Habits, Goals, Recipes, Grocery Lists, Workouts, Contacts, Calendar
- Basic API domains — todos, habits, goals, recipes, grocery lists, workouts, contacts, calendar events, tags

---

## Near-term (next sessions)

### UI polish
- [ ] Compress sidebar — search to icon-only (⌘P trigger), Ask AI + Settings to footer icon buttons
- [ ] Settings page left-nav shell (Appearance, Account, Household sections)
- [ ] Per-variable color pickers in Appearance settings (themes as presets, full override capability)

### Notes / Zettelkasten
- [ ] Notes stub added to sidebar nav
- [ ] Notes domain — atomic notes, tags (many-to-many), `[[wikilink]]` backlinks (stored in a backlinks table, populated on save)
- [ ] Notes UI — tag browser, backlinks panel, distinct from Documents

### Documents polish
- [ ] Archive/delete individual pages
- [ ] Drag-to-reorder pages in the tree

---

## Medium-term

### Core domains — build out the stubs
Priority order (highest daily value first):
1. **Tasks** — full CRUD UI, due dates, recurrence, member assignment, completion
2. **Habits** — streak tracking, completion calendar, frequency config
3. **Goals** — progress tracking, milestones, linking to tasks
4. **Recipes** — full UI, ingredients, steps, URL import via JSON-LD
5. **Grocery Lists** — linked to recipes, household-shared lists
6. **Workouts** — log entries, exercise library, strength/cardio metrics
7. **Calendar** — event creation, recurrence, member assignment views

### Household multi-member
- [ ] Invite flow — create additional household accounts
- [ ] Role enforcement in UI (owner vs member)
- [ ] Per-member views for tasks and habits

### Search
- [ ] Full-text search across documents and notes (Postgres `tsvector` or pg_search)
- [ ] Command palette integration

---

## Later

### AI layer (`agent/`)
- [ ] MCP server exposing domain services as tools
- [ ] Claude integration — household context, task suggestions, weekly summaries
- [ ] BYOK configuration (OpenAI, Anthropic key)
- [ ] Local LLM option (Ollama)
- [ ] Audit log for all AI-triggered writes

### Cloud-hosted tier
- [ ] Multi-tenant infrastructure design
- [ ] Tiered pricing (free self-hosted forever; paid for managed hosting, backups, managed AI)
- [ ] Automated backup service
- [ ] Migration path: self-hosted → cloud-hosted

### Mobile
- [ ] Mobile-responsive polish on existing web app
- [ ] Native mobile apps (push notifications, offline) — premium tier

### Integrations
- [ ] iCal export for calendar events
- [ ] Recipe import from URLs (JSON-LD scraping)
- [ ] External calendar sync (Google Calendar, etc.) — premium

---

## Deferred indefinitely

- Real-time collaborative editing
- Inter-household sharing
- Payments infrastructure (until cloud tier is ready to launch)
- Deep third-party integrations with ongoing operational cost (until premium tier exists to fund them)
