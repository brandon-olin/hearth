import { getAccessToken } from "@/lib/auth/token";
import { apiBaseUrl } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type Project = components["schemas"]["ProjectResponse"];

// ── In-memory cache ───────────────────────────────────────────────────────────
// Keyed by projectId. Survives component unmounts/remounts within a session so
// navigating back to a project detail page shows the ring instantly instead of
// re-running the full fetch waterfall. TTL of 60 s is a reasonable balance
// between freshness and not hammering localhost on every visit.

const CACHE_TTL_MS = 60_000;

interface CacheEntry {
  value: number;
  expiresAt: number;
}

const progressCache = new Map<string, CacheEntry>();

/** Remove a single project's cached progress (call after saving todos/sub-projects). */
export function invalidateProgressCache(projectId: string) {
  progressCache.delete(projectId);
}

/** Clear the entire cache (e.g. after a bulk status change). */
export function clearProgressCache() {
  progressCache.clear();
}

// ── Core computation ──────────────────────────────────────────────────────────

/**
 * Recursively computes project completion as a value 0–1.
 *
 * Branch rule:  average of direct children's scores
 *               (complete/archived children → 1.0 without fetching further)
 * Leaf rule:    done_todos / total_todos  (0 if no todos)
 *
 * Max depth of 4 prevents runaway fetches on very deep hierarchies.
 * Results are cached in-memory for 60 s so re-visiting a page is instant.
 */
export async function fetchSubtreeProgress(
  projectId: string,
  depth = 0,
): Promise<number> {
  if (depth > 4) return 0;

  // Cache hit — skip all fetches for this subtree.
  const cached = progressCache.get(projectId);
  if (cached && Date.now() < cached.expiresAt) {
    return cached.value;
  }

  const token = getAccessToken();
  const headers: Record<string, string> = token
    ? { Authorization: `Bearer ${token}` }
    : {};

  const childRes = await fetch(
    `${apiBaseUrl}/projects?parent_id=${projectId}&limit=100`,
    { headers },
  );
  if (!childRes.ok) return 0;
  const childData = (await childRes.json()) as { items: Project[] };
  const children: Project[] = childData.items ?? [];

  let value: number;

  // ── Leaf: derive from todos ───────────────────────────────────────────────
  if (children.length === 0) {
    const todoRes = await fetch(
      `${apiBaseUrl}/todos?project_id=${projectId}&limit=500`,
      { headers },
    );
    if (!todoRes.ok) return 0;
    const todoData = (await todoRes.json()) as { items: { status: string }[] };
    const todos = todoData.items ?? [];
    if (todos.length === 0) {
      value = 0;
    } else {
      const done = todos.filter(
        (t) => t.status === "done" || t.status === "cancelled",
      ).length;
      value = done / todos.length;
    }
  } else {
    // ── Branch: average children (parallel) ──────────────────────────────────
    const scores = await Promise.all(
      children.map((child) => {
        if (child.status === "complete" || child.status === "archived") {
          return Promise.resolve(1.0);
        }
        return fetchSubtreeProgress(child.id, depth + 1);
      }),
    );
    value = scores.reduce((a, b) => a + b, 0) / scores.length;
  }

  // Store in cache before returning.
  progressCache.set(projectId, { value, expiresAt: Date.now() + CACHE_TTL_MS });
  return value;
}
