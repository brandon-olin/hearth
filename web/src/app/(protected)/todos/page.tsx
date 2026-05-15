"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { $api } from "@/lib/api/query";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { TodoRow } from "@/components/todos/todo-row";
import { TodoSheet } from "@/components/todos/todo-sheet";
import { QuickAdd } from "@/components/todos/quick-add";
import { cn } from "@/lib/utils";
import { Plus, Loader2 } from "lucide-react";
import { usePermissions } from "@/lib/hooks/use-permissions";
import type { components } from "@/lib/api/schema";

type Todo = components["schemas"]["TodoResponse"];
type Filter = "active" | "all" | "done";
type Sort = "due_date" | "priority" | "created";

const PRIORITY_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2 };

function sortTodos(todos: Todo[], sort: Sort): Todo[] {
  if (sort === "priority") {
    return [...todos].sort((a, b) => {
      const pa = PRIORITY_ORDER[a.priority ?? ""] ?? 3;
      const pb = PRIORITY_ORDER[b.priority ?? ""] ?? 3;
      if (pa !== pb) return pa - pb;
      // Secondary: due date ascending
      if (a.due_date && b.due_date) return a.due_date.localeCompare(b.due_date);
      if (a.due_date) return -1;
      if (b.due_date) return 1;
      return 0;
    });
  }
  if (sort === "created") {
    return [...todos].sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    );
  }
  // "due_date" — keep server order (already sorted by due_date asc, nulls last)
  return todos;
}

const FILTERS: { key: Filter; label: string }[] = [
  { key: "active", label: "Active" },
  { key: "all", label: "All" },
  { key: "done", label: "Done" },
];

// ── date helpers ──────────────────────────────────────────────────────────────

function toLocalDateString(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function getDateBoundaries() {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const todayStr = toLocalDateString(today);
  const in7Days = new Date(today);
  in7Days.setDate(today.getDate() + 7);
  const in7DaysStr = toLocalDateString(in7Days);
  return { todayStr, in7DaysStr };
}

// ── grouping ──────────────────────────────────────────────────────────────────

type Group = { key: string; label: string; todos: Todo[] };

function groupByDueDate(todos: Todo[]): Group[] {
  const { todayStr, in7DaysStr } = getDateBoundaries();
  const overdue: Todo[] = [];
  const today: Todo[] = [];
  const thisWeek: Todo[] = [];
  const later: Todo[] = [];
  const noDate: Todo[] = [];

  for (const todo of todos) {
    if (!todo.due_date) noDate.push(todo);
    else if (todo.due_date < todayStr) overdue.push(todo);
    else if (todo.due_date === todayStr) today.push(todo);
    else if (todo.due_date <= in7DaysStr) thisWeek.push(todo);
    else later.push(todo);
  }

  return [
    { key: "overdue", label: "Overdue", todos: overdue },
    { key: "today", label: "Today", todos: today },
    { key: "this-week", label: "This week", todos: thisWeek },
    { key: "later", label: "Later", todos: later },
    { key: "no-date", label: "No due date", todos: noDate },
  ].filter((g) => g.todos.length > 0);
}

function buildGroups(items: Todo[], filter: Filter): Group[] {
  if (filter === "done") {
    const done = items.filter(
      (t) => t.status === "done" || t.status === "cancelled"
    );
    return done.length > 0 ? [{ key: "done", label: "Completed", todos: done }] : [];
  }

  if (filter === "all") {
    const active = items.filter(
      (t) => t.status === "pending" || t.status === "in_progress"
    );
    const done = items.filter(
      (t) => t.status === "done" || t.status === "cancelled"
    );
    const groups = groupByDueDate(active);
    if (done.length > 0) groups.push({ key: "done", label: "Completed", todos: done });
    return groups;
  }

  // "active" filter
  const active = items.filter(
    (t) => t.status === "pending" || t.status === "in_progress"
  );
  return groupByDueDate(active);
}

// ── group header ──────────────────────────────────────────────────────────────

function GroupHeader({
  label,
  count,
  overdue,
}: {
  label: string;
  count: number;
  overdue?: boolean;
}) {
  return (
    <div className="flex items-center gap-2.5 pt-5 pb-1 first:pt-0">
      <span
        className={cn(
          "text-xs font-semibold shrink-0",
          overdue ? "text-destructive" : "text-muted-foreground"
        )}
      >
        {label}
      </span>
      <span className="text-xs text-muted-foreground/50 shrink-0">{count}</span>
      <div className="flex-1 border-t border-border/40" />
    </div>
  );
}

// ── page ──────────────────────────────────────────────────────────────────────

export default function TodosPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { can } = usePermissions();
  const [filter, setFilter] = useState<Filter>("active");
  const [sort, setSort] = useState<Sort>("due_date");
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editingTodo, setEditingTodo] = useState<Todo | null>(null);

  const { data, isLoading, isError } = $api.useQuery("get", "/todos", {
    params: { query: { limit: 100 } },
  });

  // Auto-open sheet when navigated here with ?edit=<id> (e.g. from command palette)
  useEffect(() => {
    const editId = searchParams.get("edit");
    if (!editId || !data) return;
    const todo = data.items.find((t) => t.id === editId);
    if (todo) {
      setEditingTodo(todo);
      setSheetOpen(true);
      router.replace("/todos", { scroll: false });
    }
  }, [searchParams, data]); // eslint-disable-line react-hooks/exhaustive-deps

  const allItems = sortTodos(data?.items ?? [], sort);

  function countForFilter(f: Filter) {
    if (f === "active")
      return allItems.filter(
        (t) => t.status === "pending" || t.status === "in_progress"
      ).length;
    if (f === "done")
      return allItems.filter(
        (t) => t.status === "done" || t.status === "cancelled"
      ).length;
    return allItems.length;
  }

  const groups = buildGroups(allItems, filter);

  function openCreate() {
    setEditingTodo(null);
    setSheetOpen(true);
  }

  function openEdit(todo: Todo) {
    setEditingTodo(todo);
    setSheetOpen(true);
  }

  function handleClose() {
    setSheetOpen(false);
    // Keep editingTodo briefly so the sheet can animate out with content intact
    setTimeout(() => setEditingTodo(null), 300);
  }

  return (
    <div className="page-content">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold">To-dos</h1>
        <div className="flex items-center gap-2">
          <Select
            value={sort}
            onChange={(e) => setSort(e.target.value as Sort)}
            className="text-xs h-8 w-36"
          >
            <option value="due_date">Sort: Due date</option>
            <option value="priority">Sort: Priority</option>
            <option value="created">Sort: Recently added</option>
          </Select>
          {can("todos", "create") && (
            <Button size="sm" onClick={openCreate}>
              <Plus className="h-4 w-4 mr-1" />
              New
            </Button>
          )}
        </div>
      </div>

      {/* Filter tabs */}
      <div className="flex items-center border-b mb-4">
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
                  filter === key
                    ? "text-muted-foreground"
                    : "text-muted-foreground/60"
                )}
              >
                {countForFilter(key)}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Quick-add row — hidden on the Done tab, and hidden if user can't create */}
      {filter !== "done" && can("todos", "create") && (
        <QuickAdd className="mb-4" />
      )}

      {/* Content */}
      {isLoading && (
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading…
        </div>
      )}

      {isError && (
        <p className="py-8 text-sm text-destructive">Failed to load todos.</p>
      )}

      {!isLoading && !isError && groups.length === 0 && (
        <div className="py-12 text-center">
          <p className="text-sm text-muted-foreground">
            {filter === "active"
              ? "Nothing active — nice work."
              : filter === "done"
              ? "No completed todos yet."
              : "No todos yet."}
          </p>
          {filter !== "done" && can("todos", "create") && (
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

      {!isLoading && !isError && groups.length > 0 && (
        <div>
          {groups.map((group) => (
            <div key={group.key}>
              <GroupHeader
                label={group.label}
                count={group.todos.length}
                overdue={group.key === "overdue"}
              />
              <div className="space-y-0.5">
                {group.todos.map((todo) => (
                  <TodoRow key={todo.id} todo={todo} onEdit={openEdit} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      <TodoSheet open={sheetOpen} todo={editingTodo} onClose={handleClose} />
    </div>
  );
}
