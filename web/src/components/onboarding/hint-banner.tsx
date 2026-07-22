"use client";

import Link from "next/link";
import { Lightbulb, X } from "lucide-react";

import { HINTS, type HintId } from "@/lib/onboarding/hints";
import { useHints } from "@/lib/onboarding/use-hints";
import { cn } from "@/lib/utils";

/**
 * A first-visit hint: one sentence about what this section is for, with a close
 * button (onboarding-003).
 *
 * Deliberately not a tour. It sits in the page flow rather than over it, has no
 * "next" button and nothing to step through, and one click makes it gone for
 * good — someone who wants to dive straight in loses one line of vertical space
 * and never sees it again. Re-enable from Settings → Account.
 *
 * Renders nothing until hint state has loaded, so a dismissed hint never
 * flashes back on a page load.
 */
export function HintBanner({
  id,
  className,
}: {
  id: HintId;
  className?: string;
}) {
  const { isLoaded, isDismissed, dismiss } = useHints();
  const hint = HINTS[id];

  if (!isLoaded || isDismissed(id)) return null;

  return (
    <div
      className={cn(
        "flex items-start gap-2.5 rounded-lg border bg-primary/5 px-4 py-2.5",
        className,
      )}
    >
      <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
      <p className="min-w-0 flex-1 text-sm text-muted-foreground">
        {hint.text}
        {hint.link && (
          <>
            {" "}
            <Link
              href={hint.link.href}
              className="font-medium text-primary hover:underline"
            >
              {hint.link.label}
            </Link>
          </>
        )}
      </p>
      <button
        type="button"
        onClick={() => dismiss(id)}
        aria-label="Dismiss tip"
        className="-mr-1 shrink-0 rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
