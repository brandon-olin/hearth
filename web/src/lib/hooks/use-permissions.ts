"use client";

import { $api } from "@/lib/api/query";
import { useAuth } from "@/lib/auth/context";

// ── Role ranking (mirrors api/core/permissions.py) ────────────────────────────

const ROLE_RANK: Record<string, number> = {
  owner: 3,
  admin: 3,
  member: 2,
  viewer: 1,
  agent: 1,
};

// ── Default permissions (mirrors DEFAULT_DOMAIN_PERMISSIONS in Python) ─────────

const DEFAULT_PERMISSIONS: Record<string, Record<string, string>> = {
  calendar:  { read: "viewer", create: "viewer", manage_others: "member" },
  recipes:   { read: "viewer", create: "viewer", manage_others: "member" },
  grocery:   { read: "viewer", create: "viewer", manage_others: "member" },
  projects:  { read: "viewer", create: "viewer", manage_others: "member" },
  todos:     { read: "viewer", create: "viewer", manage_others: "member" },
  documents: { read: "viewer", create: "viewer", manage_others: "member" },
  goals:     { read: "viewer", create: "viewer", manage_others: "member" },
};

// ── Hook ──────────────────────────────────────────────────────────────────────

export type PermissionAction = "read" | "create" | "manage_others";

export interface UsePermissionsResult {
  /** True while the permissions are loading from the server. */
  isLoading: boolean;
  /**
   * Returns true if the current user can perform `action` on `domain`.
   *
   * `manage_own` is always true — users can always edit/delete their own items.
   * Pass `isOwnItem: true` to short-circuit the check for edit/delete actions.
   */
  can: (domain: string, action: PermissionAction, opts?: { isOwnItem?: boolean }) => boolean;
  /** The raw config dict (useful for the settings UI). */
  config: Record<string, Record<string, string>>;
}

export function usePermissions(): UsePermissionsResult {
  const { user } = useAuth();
  const userRole = (user as { role?: string } | null)?.role ?? "viewer";

  const { data, isLoading } = $api.useQuery("get", "/households/permissions", {}, {
    // Permissions rarely change — cache aggressively.
    staleTime: 5 * 60 * 1000,
    // Don't refetch on window focus — avoid unnecessary noise.
    refetchOnWindowFocus: false,
  });

  // Merge server config with defaults so we always have a full picture.
  const config: Record<string, Record<string, string>> = {};
  for (const domain of Object.keys(DEFAULT_PERMISSIONS)) {
    const serverDomain = data?.config?.[domain];
    config[domain] = {
      read:          serverDomain?.read          ?? DEFAULT_PERMISSIONS[domain].read,
      create:        serverDomain?.create        ?? DEFAULT_PERMISSIONS[domain].create,
      manage_others: serverDomain?.manage_others ?? DEFAULT_PERMISSIONS[domain].manage_others,
    };
  }

  function can(
    domain: string,
    action: PermissionAction,
    opts?: { isOwnItem?: boolean },
  ): boolean {
    // Users can always manage their own items.
    if (opts?.isOwnItem && (action === "manage_others")) {
      return true;
    }

    const domainConfig = config[domain] ?? DEFAULT_PERMISSIONS[domain];
    if (!domainConfig) return true; // unknown domain — allow by default

    const requiredRole = domainConfig[action] ?? "viewer";
    const userRank = ROLE_RANK[userRole] ?? 1;
    const requiredRank = ROLE_RANK[requiredRole] ?? 1;
    return userRank >= requiredRank;
  }

  return { isLoading, can, config };
}
