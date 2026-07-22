"use client";

import { useCallback, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { $api } from "@/lib/api/query";
import type { HintId } from "./hints";

/** Query key for the hint-state document. */
const HINTS_KEY = ["get", "/households/onboarding/hints"];

/**
 * Read and write this member's first-visit hint state (onboarding-003).
 *
 * Dismissal is per member and lives in `users.preferences.dismissed_hints`, so
 * it survives a reload and follows the person to another device — which is the
 * whole point of not using localStorage for it. One partner dismissing the
 * budget hint leaves it in place for the other, who has never opened the page.
 *
 * `isLoaded` matters more than it looks: until the server answers we do not
 * know whether a hint was dismissed, and rendering it optimistically would
 * flash a banner the user closed weeks ago on every page load.
 */
export function useHints() {
  const qc = useQueryClient();
  const { data, isLoading } = $api.useQuery("get", "/households/onboarding/hints");

  const dismissMutation = $api.useMutation(
    "post",
    "/households/onboarding/hints/dismiss",
  );
  const resetMutation = $api.useMutation("delete", "/households/onboarding/hints");

  // Memoised so the callbacks below keep a stable identity across renders —
  // `?? []` would otherwise mint a new array every time.
  const dismissed = useMemo(() => data?.dismissed_hints ?? [], [data]);

  const isDismissed = useCallback(
    (id: HintId) => dismissed.includes(id),
    [dismissed],
  );

  const dismiss = useCallback(
    async (id: HintId) => {
      // Hide it before the round-trip finishes — a close button that waits on
      // the network reads as broken. The write is idempotent, so a retry after
      // a failure cannot double-append, and the invalidate below reconciles.
      qc.setQueryData(HINTS_KEY, (old: typeof data) =>
        old
          ? {
              ...old,
              dismissed_hints: [...new Set([...(old.dismissed_hints ?? []), id])],
            }
          : old,
      );
      try {
        await dismissMutation.mutateAsync({ body: { hint_id: id } });
      } finally {
        qc.invalidateQueries({ queryKey: HINTS_KEY });
      }
    },
    [qc, dismissMutation],
  );

  const resetAll = useCallback(async () => {
    await resetMutation.mutateAsync({});
    await qc.invalidateQueries({ queryKey: HINTS_KEY });
  }, [qc, resetMutation]);

  return {
    /** False until the server has told us what was dismissed. */
    isLoaded: !isLoading && data !== undefined,
    dismissed,
    isDismissed,
    dismiss,
    resetAll,
    isResetting: resetMutation.isPending,
  };
}
