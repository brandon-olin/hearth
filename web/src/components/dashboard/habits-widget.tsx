"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { $api } from "@/lib/api/query";
import { cn } from "@/lib/utils";
import { CheckCircle2, Circle, Link2, Loader2 } from "lucide-react";
import type { components } from "@/lib/api/schema";

type Habit = components["schemas"]["HabitWithStats"];
type Occurrence = components["schemas"]["OccurrenceResponse"];

function HabitRow({ habit, today }: { habit: Habit; today: string }) {
  const router = useRouter();
  const [isToggling, setIsToggling] = useState(false);

  // Read link from cadence JSONB
  const cadence = (habit.cadence ?? {}) as Record<string, unknown>;
  const linkRaw = cadence.link as { path: string; label: string } | null | undefined;
  const habitLink = linkRaw?.path && linkRaw?.label ? linkRaw : null;

  const { data: occData, refetch: refetchOcc } = $api.useQuery(
    "get",
    "/habits/{habit_id}/occurrences",
    {
      params: {
        path: { habit_id: habit.id },
        query: { from_date: today, to_date: today, limit: 5 },
      },
    }
  );

  const { mutateAsync: createOcc } = $api.useMutation(
    "post",
    "/habits/{habit_id}/occurrences"
  );

  const { mutateAsync: updateOcc } = $api.useMutation(
    "patch",
    "/habits/{habit_id}/occurrences/{occurrence_id}"
  );

  const occurrence: Occurrence | null = occData?.items[0] ?? null;
  const isCompleted = occurrence?.status === "completed";

  async function handleToggle() {
    setIsToggling(true);
    try {
      let occ = occurrence;

      if (!occ) {
        // No occurrence for today yet — create one then immediately complete it.
        const created = await createOcc({
          params: { path: { habit_id: habit.id } },
          body: { scheduled_date: today, status: "completed" },
        });
        refetchOcc();
        // The occurrence was created as completed, so we're done.
        if (created) return;
      }

      if (occ) {
        const newStatus = occ.status === "completed" ? "pending" : "completed";
        await updateOcc({
          params: {
            path: { habit_id: habit.id, occurrence_id: occ.id },
          },
          body: { status: newStatus },
        });
        refetchOcc();
      }
    } finally {
      setIsToggling(false);
    }
  }

  return (
    <div
      className={cn(
        "flex items-center gap-3 w-full rounded-md px-2 py-2 hover:bg-muted/60 transition-colors group",
        isCompleted && "opacity-50"
      )}
    >
      {/* Completion toggle — always tappable */}
      <button
        type="button"
        onClick={handleToggle}
        disabled={isToggling}
        className="shrink-0 cursor-pointer disabled:cursor-wait"
        aria-label={isCompleted ? "Mark incomplete" : "Mark complete"}
      >
        {isToggling ? (
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        ) : isCompleted ? (
          <CheckCircle2 className="h-4 w-4 text-primary" />
        ) : (
          <Circle className="h-4 w-4 text-muted-foreground group-hover:text-foreground transition-colors" />
        )}
      </button>

      {/* Name — navigates to linked page if set, otherwise just text */}
      {habitLink ? (
        <button
          type="button"
          onClick={() => router.push(habitLink.path)}
          className="flex-1 flex items-center gap-1.5 min-w-0 text-left group/name"
          title={`Go to ${habitLink.label}`}
        >
          <span
            className={cn(
              "text-sm truncate group-hover/name:text-primary transition-colors",
              isCompleted && "line-through text-muted-foreground"
            )}
          >
            {habit.name}
          </span>
          <Link2 className="h-3 w-3 shrink-0 text-muted-foreground/50 group-hover/name:text-primary transition-colors" />
        </button>
      ) : (
        <span
          className={cn(
            "flex-1 text-sm truncate",
            isCompleted && "line-through text-muted-foreground"
          )}
        >
          {habit.name}
        </span>
      )}
    </div>
  );
}

export function HabitsWidget({ today }: { today: string }) {
  const { data, isLoading, isError } = $api.useQuery("get", "/habits", {
    params: { query: { limit: 50 } },
  });

  // Filter to habits that have actually started (start_date <= today).
  // Uses the browser's local date so this is always timezone-correct.
  const habits = (data?.items ?? []).filter((h) => {
    const cadence = (h.cadence ?? {}) as Record<string, unknown>;
    const startDate = cadence.start_date as string | null | undefined;
    return !startDate || startDate <= today;
  });
  const total = habits.length;

  return (
    <div>
      <div>
        <div className="flex items-baseline gap-2 mb-3">
          <h2 className="text-sm font-semibold">Habits</h2>
          {!isLoading && !isError && total > 0 && (
            <span className="text-xs text-muted-foreground">today</span>
          )}
        </div>

        {isLoading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Loading…
          </div>
        )}

        {isError && (
          <p className="text-sm text-destructive py-2">
            Failed to load habits.
          </p>
        )}

        {!isLoading && !isError && habits.length === 0 && (
          <p className="text-sm text-muted-foreground py-2">No active habits.</p>
        )}

        {habits.length > 0 && (
          <div className="space-y-0.5">
            {habits.map((habit) => (
              <HabitRow key={habit.id} habit={habit} today={today} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
