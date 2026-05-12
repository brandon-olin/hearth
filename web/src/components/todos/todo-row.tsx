"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import { cn } from "@/lib/utils";
import { Circle, CheckCircle2, Loader2 } from "lucide-react";
import type { components } from "@/lib/api/schema";

type Todo = components["schemas"]["TodoResponse"];

// ── date helpers ──────────────────────────────────────────────────────────────

function toLocalDateString(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function dueDateDisplay(dateStr: string): { label: string; className: string } {
  const today = toLocalDateString(new Date());
  const d = new Date(dateStr + "T00:00:00");
  const todayD = new Date(today + "T00:00:00");
  const diffDays = Math.round((d.getTime() - todayD.getTime()) / 86400000);
  const numeric = `${d.getMonth() + 1}/${d.getDate()}`;

  if (diffDays < 0)
    return { label: numeric, className: "text-destructive" };
  if (diffDays === 0)
    return { label: "Today", className: "text-amber-600 dark:text-amber-400" };
  if (diffDays === 1)
    return { label: `Tomorrow, ${numeric}`, className: "text-muted-foreground" };
  if (diffDays <= 7) {
    const day = d.toLocaleDateString("en-US", { weekday: "long" });
    return { label: `${day}, ${numeric}`, className: "text-muted-foreground" };
  }
  return { label: numeric, className: "text-muted-foreground" };
}

// ── priority chip ─────────────────────────────────────────────────────────────

const PRIORITY: Record<string, { label: string; className: string }> = {
  high: { label: "High", className: "text-orange-500 dark:text-orange-400" },
  medium: { label: "Medium", className: "text-yellow-600 dark:text-yellow-500" },
  low: { label: "Low", className: "text-muted-foreground" },
};

function PriorityChip({ priority }: { priority: string | null }) {
  if (!priority || priority === "medium") return null;
  const cfg = PRIORITY[priority];
  if (!cfg) return null;
  return (
    <span className={cn("text-xs font-medium shrink-0", cfg.className)}>
      {cfg.label}
    </span>
  );
}

// ── main todo row ─────────────────────────────────────────────────────────────

interface TodoRowProps {
  todo: Todo;
  onEdit: (todo: Todo) => void;
  /** Called after a successful status toggle — use to invalidate derived queries (e.g. project progress). */
  onToggled?: () => void;
}

export function TodoRow({ todo, onEdit, onToggled }: TodoRowProps) {
  const qc = useQueryClient();
  const [toggling, setToggling] = useState(false);

  const { mutateAsync: updateTodo } = $api.useMutation("patch", "/todos/{todo_id}");

  const isDone = todo.status === "done" || todo.status === "cancelled";
  const dueInfo = todo.due_date ? dueDateDisplay(todo.due_date) : null;

  async function handleToggle(e: React.MouseEvent) {
    e.stopPropagation();
    setToggling(true);
    try {
      await updateTodo({
        params: { path: { todo_id: todo.id } },
        body: { status: isDone ? "pending" : "done" },
      });
      qc.invalidateQueries({ queryKey: ["get", "/todos"] });
      onToggled?.();
    } finally {
      setToggling(false);
    }
  }

  return (
    <div className={cn("rounded-md", isDone && "opacity-60")}>
      <div
        className="flex items-center gap-2 px-2 py-2 rounded-md hover:bg-muted/50 cursor-pointer group"
        onClick={() => onEdit(todo)}
      >
        {/* Status toggle */}
        <button
          type="button"
          onClick={handleToggle}
          disabled={toggling}
          className="shrink-0 text-muted-foreground hover:text-foreground cursor-pointer disabled:cursor-wait"
          aria-label={isDone ? "Mark incomplete" : "Mark complete"}
        >
          {toggling ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : isDone ? (
            <CheckCircle2 className="h-4 w-4 text-primary" />
          ) : (
            <Circle className="h-4 w-4" />
          )}
        </button>

        {/* Title */}
        <span
          className={cn(
            "flex-1 min-w-0 text-sm truncate",
            isDone && "line-through text-muted-foreground"
          )}
        >
          {todo.title}
        </span>

        {/* Meta chips */}
        <div className="flex items-center gap-3 shrink-0">
          {todo.status === "in_progress" && (
            <span className="text-xs font-medium text-blue-500 dark:text-blue-400">
              In progress
            </span>
          )}
          {todo.status === "cancelled" && (
            <span className="text-xs text-muted-foreground">Cancelled</span>
          )}
          <PriorityChip priority={todo.priority} />
          {dueInfo && !isDone && (
            <span className={cn("text-xs", dueInfo.className)}>{dueInfo.label}</span>
          )}
        </div>
      </div>
    </div>
  );
}
