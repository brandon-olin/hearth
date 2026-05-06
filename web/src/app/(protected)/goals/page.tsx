"use client";

import { useState } from "react";
import { $api } from "@/lib/api/query";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { GoalSheet } from "@/components/goals/goal-sheet";
import { cn } from "@/lib/utils";
import {
  Plus,
  Loader2,
  Target,
  CheckCircle2,
  Circle,
  ChevronRight,
} from "lucide-react";
import type { components } from "@/lib/api/schema";

type Goal = components["schemas"]["GoalResponse"];
type Filter = "active" | "all" | "completed";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "active", label: "Active" },
  { key: "all", label: "All" },
  { key: "completed", label: "Completed" },
];

const PRIORITY_ORDER: Record<string, number> = {
  high: 0,
  medium: 1,
  low: 2,
  "": 3,
};

function applyFilter(goals: Goal[], filter: Filter): Goal[] {
  if (filter === "active")
    return goals.filter((g) => g.status === "active" || g.status === "paused");
  if (filter === "completed")
    return goals.filter((g) => g.status === "completed");
  return goals;
}

function applySort(goals: Goal[]): Goal[] {
  return [...goals].sort(
    (a, b) =>
      (PRIORITY_ORDER[a.priority ?? ""] ?? 3) -
      (PRIORITY_ORDER[b.priority ?? ""] ?? 3)
  );
}

const PRIORITY_COLORS: Record<string, string> = {
  high: "text-red-500",
  medium: "text-amber-500",
  low: "text-blue-400",
};

function progressPct(goal: Goal): number | null {
  if (!goal.target_value || !goal.current_value) return null;
  const t = Number(goal.target_value);
  const c = Number(goal.current_value);
  if (isNaN(t) || isNaN(c) || t <= 0) return null;
  return Math.min(100, Math.round((c / t) * 100));
}

function GoalRow({
  goal,
  onEdit,
  onToggle,
  isToggling,
}: {
  goal: Goal;
  onEdit: (g: Goal) => void;
  onToggle: (g: Goal) => void;
  isToggling: boolean;
}) {
  const isDone = goal.status === "completed";
  const pct = progressPct(goal);

  return (
    <div
      className={cn(
        "group flex items-start gap-3 px-3 py-3 rounded-lg border bg-card hover:bg-muted/30 transition-colors cursor-pointer",
        isDone && "opacity-60"
      )}
      onClick={() => onEdit(goal)}
    >
      {/* Complete toggle */}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onToggle(goal);
        }}
        disabled={isToggling}
        className="mt-0.5 shrink-0 text-muted-foreground hover:text-foreground disabled:cursor-wait"
        aria-label={isDone ? "Mark active" : "Mark completed"}
      >
        {isToggling ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : isDone ? (
          <CheckCircle2 className="h-4 w-4 text-primary" />
        ) : (
          <Circle className="h-4 w-4" />
        )}
      </button>

      <div className="flex-1 min-w-0 space-y-1.5">
        {/* Title row */}
        <div className="flex items-start gap-2">
          <span
            className={cn(
              "text-sm font-medium leading-5 flex-1 min-w-0",
              isDone && "line-through text-muted-foreground"
            )}
          >
            {goal.title}
          </span>

          <div className="flex items-center gap-2 shrink-0 mt-0.5">
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
            {goal.due_date && !isDone && (
              <span className="text-xs text-muted-foreground">
                {goal.due_date}
              </span>
            )}
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/40 group-hover:text-muted-foreground transition-colors" />
          </div>
        </div>

        {/* Description */}
        {goal.description && (
          <p className="text-xs text-muted-foreground line-clamp-2">
            {goal.description}
          </p>
        )}

        {/* Progress bar */}
        {pct !== null && (
          <div className="space-y-1">
            <div className="flex justify-between text-[10px] text-muted-foreground">
              <span>{pct}%</span>
              <span>
                {goal.current_value} / {goal.target_value}
                {goal.unit ? ` ${goal.unit}` : ""}
              </span>
            </div>
            <div className="h-1 w-full rounded-full bg-muted overflow-hidden">
              <div
                className="h-full bg-primary rounded-full transition-all"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function GoalsPage() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<Filter>("active");
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editingGoal, setEditingGoal] = useState<Goal | null>(null);
  const [togglingIds, setTogglingIds] = useState<Set<string>>(new Set());

  const { data, isLoading, isError } = $api.useQuery("get", "/goals", {
    params: { query: { limit: 100 } },
  });

  const { mutateAsync: updateGoal } = $api.useMutation(
    "patch",
    "/goals/{goal_id}"
  );

  const displayed = applySort(applyFilter(data?.items ?? [], filter));

  async function handleToggle(goal: Goal) {
    const newStatus = goal.status === "completed" ? "active" : "completed";
    setTogglingIds((prev) => new Set(prev).add(goal.id));
    try {
      await updateGoal({
        params: { path: { goal_id: goal.id } },
        body: { status: newStatus },
      });
      qc.invalidateQueries({ queryKey: ["get", "/goals"] });
    } finally {
      setTogglingIds((prev) => {
        const next = new Set(prev);
        next.delete(goal.id);
        return next;
      });
    }
  }

  function openCreate() {
    setEditingGoal(null);
    setSheetOpen(true);
  }

  function openEdit(goal: Goal) {
    setEditingGoal(goal);
    setSheetOpen(true);
  }

  function handleClose() {
    setSheetOpen(false);
    setTimeout(() => setEditingGoal(null), 300);
  }

  const counts = {
    active: (data?.items ?? []).filter(
      (g) => g.status === "active" || g.status === "paused"
    ).length,
    all: (data?.items ?? []).length,
    completed: (data?.items ?? []).filter((g) => g.status === "completed")
      .length,
  };

  return (
    <div className="p-6 max-w-3xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <Target className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-xl font-semibold">Goals</h1>
        </div>
        <Button size="sm" onClick={openCreate}>
          <Plus className="h-4 w-4 mr-1" />
          New
        </Button>
      </div>

      {/* Filter tabs */}
      <div className="flex border-b mb-5">
        {FILTERS.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            onClick={() => setFilter(key)}
            className={cn(
              "px-4 py-2 text-sm font-medium -mb-px border-b-2 transition-colors cursor-pointer",
              filter === key
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {label}
            {!isLoading && (
              <span
                className={cn(
                  "ml-1.5 text-xs",
                  filter === key ? "text-muted-foreground" : "text-muted-foreground/60"
                )}
              >
                {counts[key]}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Content */}
      {isLoading && (
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading…
        </div>
      )}

      {isError && (
        <p className="py-8 text-sm text-destructive">Failed to load goals.</p>
      )}

      {!isLoading && !isError && displayed.length === 0 && (
        <div className="py-12 text-center">
          <Target className="h-8 w-8 text-muted-foreground/30 mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">
            {filter === "active"
              ? "No active goals yet."
              : filter === "completed"
              ? "No completed goals."
              : "No goals yet."}
          </p>
          {filter !== "completed" && (
            <Button
              variant="outline"
              size="sm"
              className="mt-4"
              onClick={openCreate}
            >
              <Plus className="h-4 w-4 mr-1" />
              Add one
            </Button>
          )}
        </div>
      )}

      {!isLoading && !isError && displayed.length > 0 && (
        <div className="space-y-2">
          {displayed.map((goal) => (
            <GoalRow
              key={goal.id}
              goal={goal}
              onEdit={openEdit}
              onToggle={handleToggle}
              isToggling={togglingIds.has(goal.id)}
            />
          ))}
        </div>
      )}

      <GoalSheet open={sheetOpen} goal={editingGoal} onClose={handleClose} />
    </div>
  );
}
