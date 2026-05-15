"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import { cn } from "@/lib/utils";
import { CheckCircle2, Circle, Link2, Loader2 } from "lucide-react";
import { TodoSheet } from "@/components/todos/todo-sheet";
import type { components } from "@/lib/api/schema";
import type { TodoFilter } from "@/lib/dashboard/types";

type Todo = components["schemas"]["TodoResponse"];

// ── Filter helpers ─────────────────────────────────────────────────────────────

const FILTER_LABELS: Record<TodoFilter, string> = {
  overdue: "Overdue",
  today_overdue: "Today",
  this_week: "This week",
  all: "All",
};

function isoToday(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function isoInDays(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() + n);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function applyFilter(items: Todo[], filter: TodoFilter): Todo[] {
  const active = items.filter(
    (t) => t.status === "pending" || t.status === "in_progress"
  );
  const today = isoToday();
  const weekEnd = isoInDays(7);

  switch (filter) {
    case "overdue":
      return active.filter((t) => t.due_date && t.due_date < today);
    case "today_overdue":
      return active.filter((t) => t.due_date && t.due_date <= today);
    case "this_week":
      return active.filter((t) => !t.due_date || t.due_date <= weekEnd);
    case "all":
      return active;
  }
}

// ── Todo row ──────────────────────────────────────────────────────────────────

function TodoRow({
  todo,
  onToggle,
  onEdit,
  isToggling,
  today,
}: {
  todo: Todo;
  onToggle: (id: string, currentStatus: string) => void;
  onEdit: (todo: Todo) => void;
  isToggling: boolean;
  today: string;
}) {
  const router = useRouter();
  const isDone = todo.status === "done";
  const isOverdue = todo.due_date && todo.due_date < today && !isDone;
  const linkUrl = todo.link_url ?? null;
  const isExternal = linkUrl ? /^https?:\/\//.test(linkUrl) : false;

  function handleTextClick() {
    if (!linkUrl) {
      onEdit(todo);
      return;
    }
    if (isExternal) {
      window.open(linkUrl, "_blank", "noopener,noreferrer");
    } else {
      router.push(linkUrl);
    }
  }

  return (
    <div
      className={cn(
        "flex items-start gap-2 w-full rounded-md px-2 py-2 hover:bg-muted/60 transition-colors group",
        isDone && "opacity-50"
      )}
    >
      {/* Completion toggle — circle only */}
      <button
        type="button"
        onClick={() => onToggle(todo.id, todo.status)}
        disabled={isToggling}
        className="mt-0.5 shrink-0 cursor-pointer disabled:cursor-wait text-muted-foreground hover:text-foreground transition-colors"
        aria-label={isDone ? "Mark incomplete" : "Mark complete"}
      >
        {isToggling ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : isDone ? (
          <CheckCircle2 className="h-4 w-4 text-primary" />
        ) : (
          <Circle className="h-4 w-4" />
        )}
      </button>

      {/* Text — navigates to link_url if set, otherwise opens edit sheet */}
      <button
        type="button"
        onClick={handleTextClick}
        className="flex-1 min-w-0 flex items-center gap-2 text-left cursor-pointer"
      >
        <span
          className={cn(
            "text-sm leading-5 hover:underline underline-offset-2 truncate",
            isDone && "line-through text-muted-foreground"
          )}
        >
          {todo.title}
        </span>
        {linkUrl && (
          <Link2 className="h-3 w-3 shrink-0 text-muted-foreground/50 group-hover:text-muted-foreground transition-colors" />
        )}
        {todo.due_date && !isDone && (
          <span className={cn("text-xs shrink-0 ml-auto", isOverdue ? "text-destructive" : "text-muted-foreground")}>
            {isOverdue ? "Overdue" : todo.due_date}
          </span>
        )}
      </button>
    </div>
  );
}

// ── Widget ────────────────────────────────────────────────────────────────────

export function TodosWidget({
  today,
  filter: filterProp,
  onFilterChange,
}: {
  today: string;
  filter?: TodoFilter;
  onFilterChange?: (f: TodoFilter) => void;
}) {
  const qc = useQueryClient();
  const [localFilter, setLocalFilter] = useState<TodoFilter>(filterProp ?? "today_overdue");
  const [togglingIds, setTogglingIds] = useState<Set<string>>(new Set());
  const [editingTodo, setEditingTodo] = useState<Todo | null>(null);

  // If filter is controlled externally (from widget config), use it; else use local state
  const filter = filterProp ?? localFilter;

  function handleFilterChange(f: TodoFilter) {
    setLocalFilter(f);
    onFilterChange?.(f);
  }

  const { data, isLoading, isError } = $api.useQuery("get", "/todos", {
    params: { query: { limit: 200 } },
  });

  const { mutateAsync: updateTodo } = $api.useMutation("patch", "/todos/{todo_id}");

  async function handleToggle(id: string, currentStatus: string) {
    const newStatus = currentStatus === "done" ? "pending" : "done";
    setTogglingIds((prev) => new Set(prev).add(id));
    try {
      await updateTodo({
        params: { path: { todo_id: id } },
        body: { status: newStatus },
      });
      qc.invalidateQueries({ queryKey: ["get", "/todos"] });
    } finally {
      setTogglingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  }

  const allItems = data?.items ?? [];
  const filtered = applyFilter(allItems, filter);
  const totalActive = allItems.filter(
    (t) => t.status === "pending" || t.status === "in_progress"
  ).length;

  return (
    <div>
      {/* Header with filter tabs */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-baseline gap-2">
          <h2 className="text-sm font-semibold">To-dos</h2>
          {!isLoading && !isError && (
            <span className="text-xs text-muted-foreground">
              {totalActive === 0 ? "all done" : `${totalActive} remaining`}
            </span>
          )}
        </div>
      </div>

      {/* Filter selector */}
      <div className="flex gap-1 mb-3">
        {(Object.keys(FILTER_LABELS) as TodoFilter[]).map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => handleFilterChange(f)}
            className={cn(
              "px-2 py-0.5 rounded text-xs transition-colors cursor-pointer",
              filter === f
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground hover:bg-muted"
            )}
          >
            {FILTER_LABELS[f]}
          </button>
        ))}
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Loading…
        </div>
      )}

      {isError && (
        <p className="text-sm text-destructive py-2">Failed to load todos.</p>
      )}

      {!isLoading && !isError && filtered.length === 0 && (
        <p className="text-sm text-muted-foreground py-2">
          {filter === "overdue"
            ? "Nothing overdue."
            : filter === "today_overdue"
            ? "Nothing due today."
            : filter === "this_week"
            ? "Nothing due this week."
            : "No active todos."}
        </p>
      )}

      {filtered.length > 0 && (
        <div className="space-y-0.5">
          {filtered.map((todo) => (
            <TodoRow
              key={todo.id}
              todo={todo}
              today={today}
              onToggle={handleToggle}
              onEdit={setEditingTodo}
              isToggling={togglingIds.has(todo.id)}
            />
          ))}
        </div>
      )}

      <TodoSheet
        open={editingTodo !== null}
        todo={editingTodo}
        onClose={() => setEditingTodo(null)}
      />
    </div>
  );
}

export function todosRemainingFromData(
  data: components["schemas"]["TodoListResponse"] | undefined
): number {
  if (!data) return 0;
  return data.items.filter(
    (t) => t.status === "pending" || t.status === "in_progress"
  ).length;
}
