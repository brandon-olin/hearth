import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * The "you have nothing here yet" state for a domain page (onboarding-003).
 *
 * Deliberately distinct from a filtered-empty result. This state says what the
 * section is *for* and offers the one action that gets you started, so it is
 * only correct when the user genuinely has no data — showing it when a filter
 * happens to match nothing tells someone with 200 to-dos that they have none.
 * Pages keep their short "No results" line for that case.
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon: LucideIcon;
  /** What is missing, in the user's words: "No habits yet". */
  title: string;
  /** One or two sentences on what this section does. No jargon. */
  description: string;
  /** The primary call to action — usually a `<Button>`. */
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 px-6 py-14 text-center",
        className,
      )}
    >
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
        <Icon className="h-6 w-6 text-muted-foreground" />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-semibold">{title}</p>
        <p className="mx-auto max-w-sm text-sm text-muted-foreground">
          {description}
        </p>
      </div>
      {action}
    </div>
  );
}
