"use client";

import { useState } from "react";
import { $api } from "@/lib/api/query";
import { apiClient } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import { CheckCircle2, Circle, Loader2, MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { components } from "@/lib/api/schema";

type Habit = components["schemas"]["HabitResponse"];
type Occurrence = components["schemas"]["OccurrenceResponse"];

function HabitRow({ habit, today }: { habit: Habit; today: string }) {
  const [isToggling, setIsToggling] = useState(false);

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

  const { mutateAsync: generateOccs } = $api.useMutation(
    "post",
    "/habits/{habit_id}/occurrences/generate"
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
        await generateOccs({
          params: { path: { habit_id: habit.id } },
          body: { from_date: today, to_date: today },
        });
        const fresh = await refetchOcc();
        occ = fresh.data?.items[0] ?? null;
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
    <button
      type="button"
      onClick={handleToggle}
      disabled={isToggling}
      className={cn(
        "flex items-center gap-3 w-full text-left rounded-md px-2 py-2 hover:bg-muted/60 transition-colors group cursor-pointer disabled:cursor-wait",
        isCompleted && "opacity-50"
      )}
    >
      {isToggling ? (
        <Loader2 className="h-4 w-4 shrink-0 animate-spin text-muted-foreground" />
      ) : isCompleted ? (
        <CheckCircle2 className="h-4 w-4 shrink-0 text-primary" />
      ) : (
        <Circle className="h-4 w-4 shrink-0 text-muted-foreground group-hover:text-foreground transition-colors" />
      )}
      <span
        className={cn(
          "text-sm",
          isCompleted && "line-through text-muted-foreground"
        )}
      >
        {habit.name}
      </span>
    </button>
  );
}

export function HabitsWidget({ today }: { today: string }) {
  const { data, isLoading, isError } = $api.useQuery("get", "/habits", {
    params: { query: { limit: 50 } },
  });

  const habits = data?.items ?? [];
  const total = habits.length;

  return (
    <div className="space-y-6">
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

      {/* AI cheerleader placeholder */}
      <div className="rounded-lg border border-dashed bg-muted/20 p-4">
        <div className="flex items-center gap-2 mb-1.5">
          <MessageSquare className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            AI Coach
          </span>
        </div>
        <p className="text-sm text-muted-foreground">
          Coming soon — your local AI will cheer you on here.
        </p>
        <Button variant="outline" size="sm" className="mt-3 w-full" disabled>
          Ask AI
        </Button>
      </div>
    </div>
  );
}
