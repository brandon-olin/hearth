"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import { cn } from "@/lib/utils";
import {
  Circle,
  CheckCircle2,
  Loader2,
  ChevronRight,
  ChevronDown,
} from "lucide-react";
import type { components } from "@/lib/api/schema";

type Todo = components["schemas"]["TodoResponse"];
type TodoSummary = components["schemas"]["TodoSummary"];

// ── date helpers ──────────────────────────────────────────────────────────────

function toLocalDateString(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function dueDateDisplay(dateStr: string): { label: string; className: string } {
  const today = toLocalDateString(new Date());
  const d = new Date(dateStr + "T00:00:00");
  const todayD = new Date(today + "T00:00:00");
  const diffDays = Math.round((d.getTime() - todayD.getTime()) / 86400000);
  // M/D with no leading zeros, no year
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

const PRIORITY: Record<
  string,
  { label: string; className: string }
> = {
  urgent: {
    label: "Urgent",
    className: "text-destructive",
  },
  high: {
    label: "High",
    className: "text-orange-500 dark:text-orange-400",
  },
  medium: {
    label: "Medium",
    className: "text-yellow-600 dark:text-yellow-500",
  },
  low: {
    label: "Low",
    className: "text-muted-foreground",
  },
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

// ── subtask row ───────────────────────────────────────────────────────────────

function SubtaskRow({ child }: { child: TodoSummary }) {
  const qc = useQueryClient();
  const [toggling, setToggling] = useState(false);
  const { mutateAsync: updateTodo } = $api.useMutation(
    "patch",
    "/todos/{todo_id}"
  );

  const isDone = child.status === "done" || child.status === "cancelled";

  async function handleToggle() {
    setToggling(true);
    try {
      await updateTodo({
        params: { path: { todo_id: child.id } },
        body: { status: isDone ? "todo" : "done" },
      });
      qc.invalidateQueries({ queryKey: ["get", "/todos"] });
    } finally {
      setToggling(false);
    }
  }

  return (
    <div className="flex items-center gap-2 pl-9 pr-2 py-1.5 group">
      <button
        type="button"
        onClick={handleToggle}
        disabled={toggling}
        className="shrink-0 text-muted-foreground hover:text-foreground cursor-pointer disabled:cursor-wait"
        aria-label={isDone ? "Mark incomplete" : "Mark complete"}
      >
        {toggling ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : isDone ? (
          <CheckCircle2 className="h-3.5 w-3.5 text-primary" />
        ) : (
          <Circle className="h-3.5 w-3.5" />
        )}
      </button>
      <span
        className={cn(
          "text-sm flex-1 min-w-0",
          isDone && "line-through text-muted-foreground"
        )}
      >
        {child.title}
      </span>
      {child.due_date && !isDone && (
        <span
          className={cn(
            "text-xs shrink-0",
            dueDateDisplay(child.due_date).className
          )}
        >
          {dueDateDisplay(child.due_date).label}
        </span>
      )}
    </div>
  );
}

// ── main todo row ─────────────────────────────────────────────────────────────

interface TodoRowProps {
  todo: Todo;
  onEdit: (todo: Todo) => void;
}

export function TodoRow({ todo, onEdit }: TodoRowProps) {
  const qc = useQueryClient();
  const [toggling, setToggling] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const { mutateAsync: updateTodo } = $api.useMutation(
    "patch",
    "/todos/{todo_id}"
  );

  const isDone = todo.status === "done" || todo.status === "cancelled";
  const hasChildren = todo.children.length > 0;
  const dueInfo = todo.due_date ? dueDateDisplay(todo.due_date) : null;

  async function handleToggle(e: React.MouseEvent) {
    e.stopPropagation();
    setToggling(true);
    try {
      await updateTodo({
        params: { path: { todo_id: todo.id } },
        body: { status: isDone ? "todo" : "done" },
      });
      qc.invalidateQueries({ queryKey: ["get", "/todos"] });
    } finally {
      setToggling(false);
    }
  }

  return (
    <div className={cn("rounded-md", isDone && "opacity-60")}>
      {/* Main row */}
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
            <span className={cn("text-xs", dueInfo.className)}>
              {dueInfo.label}
            </span>
          )}
          {/* Subtask count / expand button */}
          {hasChildren && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setExpanded((v) => !v);
              }}
              className="flex items-center gap-0.5 text-xs text-muted-foreground hover:text-foreground cursor-pointer"
            >
              {expanded ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              {todo.children.length}
            </button>
          )}
        </div>
      </div>

      {/* Subtasks */}
      {expanded && hasChildren && (
        <div className="pb-1">
          {todo.children.map((child) => (
            <SubtaskRow key={child.id} child={child} />
          ))}
        </div>
      )}
    </div>
  );
}
