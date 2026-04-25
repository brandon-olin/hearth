# Agent vocabulary

The list of operations the local LLM is allowed to call on the
life_dashboard backend. Will be fleshed out in Phase 3. This file is
the contract between the agent and the system.

## Design principles

- **Verbs, not SQL.** Every operation is a high-level action with a
  stable name and a predictable JSON shape. The agent never writes
  queries.
- **Idempotency where possible.** Operations that create things should
  accept an idempotency key and return the existing row if the key
  was already used.
- **Scoped by household.** Every operation is implicitly scoped to
  the agent's household. The agent cannot reach into another household's
  data.
- **Auditable.** Every write operation produces an `audit_log` row with
  a structured diff.

## Operation tiers

**Tier 1 — Read (no approval required)**
- `list_todos(filter)`, `get_todo(id)`
- `list_goals(filter)`, `get_goal(id)`
- `list_habits(filter)`, `get_habit_occurrences(date_range)`
- `list_calendar_events(date_range)`
- `list_notes(filter)`, `get_note(id)`
- `list_recipes(filter)`, `get_recipe(id)`
- `list_grocery_lists(status)`, `get_grocery_list(id)`
- `list_contacts(filter)`, `get_contact(id)`
- `get_dashboard_summary(date)` — composite read for "today"

**Tier 2 — Single-entity writes (audited, no approval)**
- `create_todo(title, ...)`, `update_todo(id, patch)`
- `create_note(...)`, `update_note(id, patch)`
- `create_calendar_event(...)`
- `log_habit_occurrence(habit_id, date, status)`
- `add_grocery_item(list_id, item)`, `check_off_grocery_item(id)`
- `record_progress_on_goal(goal_id, new_value)`

**Tier 3 — Bulk or destructive (require approval)**
- `delete_todo(id)`, `delete_note(id)`, `delete_*(id)`
- `bulk_update_todos(filter, patch)`
- `bulk_delete_*`
- `archive_completed_todos(before_date)`
- `import_*_from_external(payload)`

Tier-3 operations return a `proposed_change_id` instead of executing
immediately. The proposed change appears in the UI for Brandon to
approve or reject. Approval executes the operation with the full audit
trail pointing back to the proposal.

## Schema will be machine-readable

When Phase 3 lands, this vocabulary will be expressed as:
- OpenAPI operations with `x-agent-tier: 1|2|3` extensions, and
- An MCP server exposing the same operations as tools with JSON
  Schema for inputs.

The agent loads the MCP tool list at startup and the human UI reads
the OpenAPI spec — one source of truth.
