"use client";

import { useState } from "react";
import { $api } from "@/lib/api/query";
import { cn } from "@/lib/utils";
import { Circle, CheckCircle2, Loader2 } from "lucide-react";
import type { components } from "@/lib/api/schema";

type Habit = components["schemas"]["HabitResponse"];
type Occurrence = components["schemas"]["OccurrenceResponse"];

export function frequencyLabel(habit: Habit): string {
  const n = habit.times_per_period;
  switch (habit.frequency) {
    case "daily":
      return "Daily";
    case "weekly":
      return n && n > 1 ? `${n}× per week` : "Weekly";
    case "monthly":
      return n && n > 1 ? `${n}× per month` : "Monthly";
    case "custom":
      return n && habit.period_unit
        ? `${n}× per ${habit.period_unit}`
        : habit.period_unit
        ? `Per ${habit.period_unit}`
        : "Custom";
    default:
      return habit.frequency;
  }
}

interface HabitRowProps {
  habit: Habit;
  today: string;
  onEdit: (habit: Habit) => void;
}

export function HabitRow({ habit, today, onEdit }: HabitRowProps) {
  const [toggling, setToggling] = useState(false);

  const { data: occData, refetch } = $api.useQuery(
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

  async function handleToggle(e: React.MouseEvent) {
    e.stopPropagation();
    if (!habit.is_active) return;
    setToggling(true);
    try {
      let occ = occurrence;
      if (!occ) {
        await generateOccs({
          params: { path: { habit_id: habit.id } },
          body: { from_date: today, to_date: today },
        });
        const fresh = await refetch();
        occ = fresh.data?.items[0] ?? null;
      }
      if (occ) {
        await updateOcc({
          params: { path: { habit_id: habit.id, occurrence_id: occ.id } },
          body: { status: occ.status === "completed" ? "pending" : "completed" },
        });
        refetch();
      }
    } finally {
      setToggling(false);
    }
  }

  return (
    <div
      className={cn(
        "flex items-center gap-2 px-2 py-2 rounded-md hover:bg-muted/50 cursor-pointer group",
        !habit.is_active && "opacity-50"
      )}
      onClick={() => onEdit(habit)}
    >
      <button
        type="button"
        onClick={handleToggle}
        disabled={toggling || !habit.is_active}
        className="shrink-0 text-muted-foreground hover:text-foreground cursor-pointer disabled:cursor-default"
        aria-label={isCompleted ? "Mark incomplete" : "Mark complete"}
      >
        {toggling ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : isCompleted ? (
          <CheckCircle2 className="h-4 w-4 text-primary" />
        ) : (
          <Circle className="h-4 w-4" />
        )}
      </button>

      <span className="flex-1 min-w-0 text-sm truncate">{habit.name}</span>

      <div className="flex items-center gap-2 shrink-0 text-xs text-muted-foreground">
        {!habit.is_active && <span>Inactive</span>}
        {habit.preferred_time && (
          <span className="capitalize">{habit.preferred_time}</span>
        )}
        <span>{frequencyLabel(habit)}</span>
      </div>
    </div>
  );
}
