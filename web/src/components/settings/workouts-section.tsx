"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { useSaveAsTemplatePrompt } from "@/lib/workouts/use-template-prompt";

/**
 * Settings → Workouts. One preference today: whether finishing an improvised
 * workout offers to save it as a template. Its home is `users.preferences`, so
 * it is per-member and needs no schema change.
 */
export function WorkoutsSection() {
  const { enabled, setEnabled, isSaving } = useSaveAsTemplatePrompt();
  const [error, setError] = useState<string | null>(null);

  async function toggle(next: boolean) {
    setError(null);
    try {
      await setEnabled(next);
    } catch {
      setError("Couldn't save that preference. Try again.");
    }
  }

  return (
    <div>
      <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-4">
        Workouts
      </h2>

      <div className="border rounded-lg bg-card p-4">
        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            className="checkbox-themed mt-0.5"
            checked={enabled}
            disabled={isSaving}
            onChange={(e) => toggle(e.target.checked)}
          />
          <span>
            <span className="text-sm font-medium block">
              Prompt to save new workouts as templates
            </span>
            <span className="text-xs text-muted-foreground block mt-0.5">
              When you finish a workout you built as you went, offer to keep it as
              a template. Workouts started from a template never prompt. You can
              always save one from the workout summary, whether or not this is on.
            </span>
          </span>
          {isSaving && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground mt-0.5" />}
        </label>
        {error && <p className="text-xs text-destructive mt-2">{error}</p>}
      </div>
    </div>
  );
}
