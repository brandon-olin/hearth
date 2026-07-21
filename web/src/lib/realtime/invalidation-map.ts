/**
 * realtime-001 — maps a backend entity type (the changed table's name, as sent
 * in a skinny invalidation event) to the React Query path prefixes to
 * invalidate.
 *
 * The stream sends `{ type, id, action }` where `type` is the table name. We map
 * that to one or more API path prefixes; the stream hook invalidates every
 * cached query whose path (the second element of its query key, e.g. "/todos"
 * or "/todos/{todo_id}") starts with one of those prefixes. Prefix matching
 * means a single mapping covers a domain's list query, its detail queries, and
 * any sub-routes without enumerating them.
 *
 * An unmapped type is ignored — the backend broadcasts an event for every
 * household-scoped table, but the UI only acts on the ones it actually caches.
 */
export const ENTITY_INVALIDATION_MAP: Record<string, string[]> = {
  todos: ["/todos"],
  habits: ["/habits"],
  goals: ["/goals"],
  projects: ["/projects"],
  recipes: ["/recipes"],
  grocery_lists: ["/grocery-lists"],
  // Workouts is a multi-table domain (sessions, session_exercises, sets, plus the
  // shared exercise catalog and templates); all map to the "/workouts" prefix,
  // which covers the sessions/exercises/templates cached queries.
  workout_sessions: ["/workouts"],
  session_exercises: ["/workouts"],
  workout_sets: ["/workouts"],
  exercises: ["/workouts"],
  workout_templates: ["/workouts"],
  template_exercises: ["/workouts"],
  contacts: ["/contacts"],
  calendar_events: ["/events"],
  notes: ["/notes"],
  documents: ["/documents"],
  tags: ["/tags"],
  collections: ["/collections"],
  templates: ["/templates"],
  notifications: ["/notifications"],
  // Budget is a multi-route domain (accounts, transactions, categories, …);
  // a single "/budget" prefix covers all of its cached queries.
  budget_accounts: ["/budget"],
  budget_categories: ["/budget"],
  budget_category_groups: ["/budget"],
  budget_profiles: ["/budget"],
  budget_targets: ["/budget"],
  budget_transactions: ["/budget"],
  budget_rollover_amounts: ["/budget"],
  household_memberships: ["/households"],
};

/** The path prefixes to invalidate for an entity type, or [] if unmapped. */
export function prefixesForEntityType(entityType: string): string[] {
  return ENTITY_INVALIDATION_MAP[entityType] ?? [];
}
