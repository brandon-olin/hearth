"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, Sparkles } from "lucide-react";

import { $api } from "@/lib/api/query";
import { Button } from "@/components/ui/button";

/**
 * "Exploring with sample data" banner (onboarding-002).
 *
 * Renders nothing until the API says this household is actually holding seeded
 * content, so it never flashes on a household that has none. Clearing removes
 * only what the seeder created — anything the user wrote while exploring
 * survives, which is what makes the button safe to press without a warning
 * dialog in the way.
 */
export function SampleDataBanner() {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const { data } = $api.useQuery("get", "/households/demo-data");
  const { mutateAsync, isPending } = $api.useMutation("delete", "/households/demo-data");

  if (!data?.present) return null;

  async function handleClear() {
    setError(null);
    try {
      await mutateAsync({});
      // Every domain the seeder wrote to needs refetching, and the banner's own
      // query decides whether this component keeps rendering. Invalidating the
      // whole cache is the honest scope here — the seeder touched eight domains
      // and enumerating them would drift the moment it learns a ninth.
      await qc.invalidateQueries();
    } catch {
      setError("Couldn't clear the sample data. Try again in a moment.");
    }
  }

  return (
    <div className="border-b bg-primary/5 px-6 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-start gap-2.5 min-w-0">
          <Sparkles className="h-4 w-4 text-primary shrink-0 mt-0.5" />
          <div className="min-w-0">
            <p className="text-sm font-medium">
              Exploring with sample data — clear it when ready
            </p>
            <p className="text-xs text-muted-foreground">
              These to-dos, habits, recipes and transactions are examples. Clearing
              removes only those — anything you&apos;ve added yourself stays.
            </p>
            {error && <p className="text-xs text-destructive mt-1">{error}</p>}
          </div>
        </div>
        <Button size="sm" variant="outline" onClick={handleClear} disabled={isPending}>
          {isPending ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
              Clearing…
            </>
          ) : (
            "Clear sample data"
          )}
        </Button>
      </div>
    </div>
  );
}
