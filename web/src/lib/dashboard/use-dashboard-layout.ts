"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth/context";
import { apiClient } from "@/lib/api/client";
import { DEFAULT_LAYOUT, migrateLayout, type DashboardLayout } from "./types";

const PATCH_DEBOUNCE_MS = 1000;

export function useDashboardLayout() {
  const { user } = useAuth();

  const [layout, setLayoutState] = useState<DashboardLayout>(() =>
    migrateLayout(user?.preferences as Record<string, unknown> | null)
  );
  const [isEditMode, setIsEditMode] = useState(false);

  // Sync FROM DB when user first resolves (same pattern as PreferencesSyncer)
  const syncedUserIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (!user || syncedUserIdRef.current === user.id) return;
    syncedUserIdRef.current = user.id;
    const prefs = user.preferences as Record<string, unknown> | null;
    const serverLayout = migrateLayout(prefs);
    setLayoutState(serverLayout);
  }, [user?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Debounced PATCH TO DB on layout change
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const setLayout = useCallback((next: DashboardLayout) => {
    setLayoutState(next);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      apiClient.PATCH("/auth/me", {
        body: {
          preferences: {
            dashboard: next as unknown as Record<string, unknown>,
          },
        },
      });
    }, PATCH_DEBOUNCE_MS);
  }, []);

  // Exit edit mode automatically on unmount (e.g. navigating away and back)
  useEffect(() => {
    return () => {
      setIsEditMode(false);
    };
  }, []);

  return { layout, setLayout, isEditMode, setIsEditMode };
}

// Re-export DEFAULT_LAYOUT for convenience
export { DEFAULT_LAYOUT };
