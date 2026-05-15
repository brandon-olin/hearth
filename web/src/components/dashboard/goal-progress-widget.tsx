"use client";

import { useRouter } from "next/navigation";
import { $api } from "@/lib/api/query";
import { cn } from "@/lib/utils";
import { Target, ArrowRight, Loader2 } from "lucide-react";
import type { GoalProgressConfig } from "@/lib/dashboard/types";
import type { components } from "@/lib/api/schema";

type Goal = components["schemas"]["GoalResponse"];

function progressPct(goal: Goal): number | null {
  if (!goal.target_value || !goal.current_value) return null;
  const t = Number(goal.target_value);
  const c = Number(goal.current_value);
  if (isNaN(t) || isNaN(c) || t <= 0) return null;
  return Math.min(100, Math.round((c / t) * 100));
}

const PRIORITY_COLORS: Record<string, string> = {
  high: "text-red-500",
  medium: "text-amber-500",
  low: "text-blue-400",
};

export function GoalProgressWidget({ config }: { config: GoalProgressConfig }) {
  const router = useRouter();

  const { data, isLoading, isError } = $api.useQuery("get", "/goals", {
    params: { query: { limit: 100 } },
  });

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Loading…
      </div>
    );
  }

  if (isError) {
    return <p className="text-sm text-destructive py-2">Failed to load goals.</p>;
  }

  const goal = (data?.items ?? []).find((g) => g.id === config.goal_id);

  if (!goal) {
    return (
      <div className="flex flex-col items-center justify-center py-6 text-center gap-2">
        <Target className="h-6 w-6 text-muted-foreground/30" />
        <p className="text-xs text-muted-foreground">Goal not found.</p>
      </div>
    );
  }

  const pct = progressPct(goal);
  const isDone = goal.status === "completed";

  return (
    <button
      type="button"
      onClick={() => router.push("/goals")}
      className="w-full text-left group"
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <Target className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <span
            className={cn(
              "text-sm font-medium truncate",
              isDone && "line-through text-muted-foreground"
            )}
          >
            {goal.title}
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {goal.priority && (
            <span
              className={cn(
                "text-[10px] font-semibold uppercase tracking-wide",
                PRIORITY_COLORS[goal.priority]
              )}
            >
              {goal.priority}
            </span>
          )}
          <ArrowRight className="h-3.5 w-3.5 text-muted-foreground/40 group-hover:text-muted-foreground transition-colors" />
        </div>
      </div>

      {goal.description && (
        <p className="text-xs text-muted-foreground line-clamp-1 mb-2">
          {goal.description}
        </p>
      )}

      {pct !== null ? (
        <div className="space-y-1">
          <div className="flex justify-between text-[10px] text-muted-foreground">
            <span>{pct}% complete</span>
            <span>
              {goal.current_value} / {goal.target_value}
              {goal.unit ? ` ${goal.unit}` : ""}
            </span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
            <div
              className="h-full bg-primary rounded-full transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-1.5">
          <span
            className={cn(
              "text-xs",
              isDone ? "text-primary" : "text-muted-foreground"
            )}
          >
            {isDone ? "Completed" : goal.status === "paused" ? "Paused" : "In progress"}
          </span>
          {goal.due_date && !isDone && (
            <span className="text-xs text-muted-foreground">· Due {goal.due_date}</span>
          )}
        </div>
      )}
    </button>
  );
}
