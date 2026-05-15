/**
 * Household-friendly display labels for the underlying role permission levels.
 *
 * The stored values (owner/admin/member/viewer/agent) are the API contract and
 * the database enum — we never change those. This map translates them into
 * language that makes sense for a household/family context in the UI.
 *
 * member → Parent  (full read/write, the default adult role)
 * viewer → Child   (read-only, suitable for younger household members)
 */
export const ROLE_LABEL: Record<string, string> = {
  owner:  "Owner",
  admin:  "Admin",
  member: "Parent",
  viewer: "Child",
  agent:  "Agent",
};
