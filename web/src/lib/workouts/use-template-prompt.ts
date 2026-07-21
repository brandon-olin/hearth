"use client";

import { $api } from "@/lib/api/query";
import { useAuth } from "@/lib/auth/context";
import type { components } from "@/lib/api/schema";

type User = components["schemas"]["UserResponse"];

/**
 * "Prompt to save new workouts as templates" (workouts-003).
 *
 * This lives in the existing `users.preferences` JSON column rather than as a
 * new column: it is a per-member display preference that nothing queries or
 * filters on, which is exactly what that column is for — and workouts-003 ships
 * without a migration. Absent means enabled, so members who have never seen the
 * prompt still get it once.
 */
export const PROMPT_SAVE_AS_TEMPLATE_KEY = "prompt_save_as_template";

export function useSaveAsTemplatePrompt() {
  const { user, updateUser } = useAuth();
  const preferences = (user?.preferences ?? {}) as Record<string, unknown>;
  const enabled = preferences[PROMPT_SAVE_AS_TEMPLATE_KEY] !== false;

  const patchMe = $api.useMutation("patch", "/auth/me");

  async function setEnabled(next: boolean) {
    await patchMe.mutateAsync({
      // PATCH /auth/me merges into the existing preferences blob, so sending
      // just this key leaves theme, sidebar, and onboarding state untouched.
      body: { preferences: { [PROMPT_SAVE_AS_TEMPLATE_KEY]: next } },
    });
    // Keep the in-memory user in sync so the toggle doesn't snap back before
    // the next /auth/me refresh.
    updateUser({
      preferences: {
        ...preferences,
        [PROMPT_SAVE_AS_TEMPLATE_KEY]: next,
      } as User["preferences"],
    });
  }

  return { enabled, setEnabled, isSaving: patchMe.isPending };
}
