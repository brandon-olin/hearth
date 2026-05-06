"use client";

// PreferencesSyncer — bridges auth, theme, and sidebar into cross-device sync.
//
// Strategy:
//   • On mount (user first resolves): read user.preferences from DB, compare
//     with localStorage. If DB differs, apply the DB version (newer wins).
//   • On theme or sidebar change: debounced PATCH /auth/me so the DB stays
//     in sync for the user's next device.
//
// This component renders nothing — it's a pure side-effect hook.

import { useEffect, useRef } from "react";
import { useAuth } from "@/lib/auth/context";
import { useThemeCustomizer } from "@/lib/theme/context";
import { useSidebarConfig, loadSidebarConfig, type SidebarConfig } from "@/lib/sidebar/context";
import { loadThemeConfig, type ThemeConfig } from "@/lib/theme/presets";
import { apiClient } from "@/lib/api/client";

const PATCH_DEBOUNCE_MS = 1000;

export function PreferencesSyncer() {
  const { user } = useAuth();
  const { config: themeConfig, setConfig: setThemeConfig } = useThemeCustomizer();
  const { sidebarConfig, setSidebarConfig } = useSidebarConfig();

  // Track which user ID we've already synced from DB to avoid re-applying on
  // every render when user object identity changes.
  const syncedUserIdRef = useRef<string | null>(null);

  // Guard: while we're applying DB values, skip the outgoing PATCH to avoid
  // a pointless echo back to the server.
  const isSyncingFromDb = useRef(false);

  // Debounce timers for PATCH calls.
  const themeTimerRef   = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sidebarTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Sync FROM DB ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!user) {
      syncedUserIdRef.current = null;
      return;
    }
    // Only run once per user session.
    if (syncedUserIdRef.current === user.id) return;
    syncedUserIdRef.current = user.id;

    const prefs = user.preferences as Record<string, unknown> | null;
    if (!prefs) return;

    isSyncingFromDb.current = true;

    if (prefs.theme) {
      const dbTheme = prefs.theme as ThemeConfig;
      const localTheme = loadThemeConfig();
      if (JSON.stringify(dbTheme) !== JSON.stringify(localTheme)) {
        // Animate the transition so the remote theme fades in rather than snapping.
        setThemeConfig(dbTheme, /* animate = */ true);
      }
    }

    if (prefs.sidebar) {
      const dbSidebar = prefs.sidebar as SidebarConfig;
      const localSidebar = loadSidebarConfig();
      if (JSON.stringify(dbSidebar) !== JSON.stringify(localSidebar)) {
        setSidebarConfig(dbSidebar);
      }
    }

    // Clear the guard after React has processed the state updates.
    setTimeout(() => { isSyncingFromDb.current = false; }, 0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);

  // ── Sync theme TO DB ────────────────────────────────────────────────────────
  useEffect(() => {
    if (isSyncingFromDb.current || !user) return;

    if (themeTimerRef.current) clearTimeout(themeTimerRef.current);
    themeTimerRef.current = setTimeout(() => {
      apiClient.PATCH("/auth/me", {
        body: {
          preferences: {
            theme: themeConfig as unknown as Record<string, unknown>,
          },
        },
      });
    }, PATCH_DEBOUNCE_MS);

    return () => {
      if (themeTimerRef.current) clearTimeout(themeTimerRef.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [themeConfig, user?.id]);

  // ── Sync sidebar TO DB ──────────────────────────────────────────────────────
  useEffect(() => {
    if (isSyncingFromDb.current || !user) return;

    if (sidebarTimerRef.current) clearTimeout(sidebarTimerRef.current);
    sidebarTimerRef.current = setTimeout(() => {
      apiClient.PATCH("/auth/me", {
        body: {
          preferences: {
            sidebar: sidebarConfig as unknown as Record<string, unknown>,
          },
        },
      });
    }, PATCH_DEBOUNCE_MS);

    return () => {
      if (sidebarTimerRef.current) clearTimeout(sidebarTimerRef.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sidebarConfig, user?.id]);

  return null;
}
