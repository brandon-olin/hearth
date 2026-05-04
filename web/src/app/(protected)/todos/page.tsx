"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { $api } from "@/lib/api/query";
import { Button } from "@/components/ui/button";
import { TodoRow } from "@/components/todos/todo-row";
import { TodoSheet } from "@/components/todos/todo-sheet";
import { cn } from "@/lib/utils";
import { Plus, Loader2, ArrowUpDown } from "lucide-react";
import type { components } from "@/lib/api/schema";

type Todo = components["schemas"]["TodoResponse"];
type Filter = "active" | "all" | "done";
type Sort = "default" | "due_asc" | "due_desc";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "active", label: "Active" },
  { key: "all", label: "All" },
  { key: "done", label: "Done" },
];

const SORT_LABELS: Record<Sort, string> = {
  default: "Default",
  due_asc: "Due: soonest",
  due_desc: "Due: latest",
};

const SORT_CYCLE: Sort[] = ["default", "due_asc", "due_desc"];

function applyFilter(todos: Todo[], filter: Filter): Todo[] {
  if (filter === "active")
    return todos.filter(
      (t) => t.status === "todo" || t.status === "in_progress"
    );
  if (filter === "done")
    return todos.filter(
      (t) => t.status === "done" || t.status === "cancelled"
    );
  return todos;
}

function applySort(todos: Todo[], sort: Sort): Todo[] {
  if (sort === "default") return todos;

  return [...todos].sort((a, b) => {
    // Todos without a due date sink to the bottom in both directions
    if (!a.due_date && !b.due_date) return 0;
    if (!a.due_date) return 1;
    if (!b.due_date) return -1;
    const cmp = a.due_date < b.due_date ? -1 : a.due_date > b.due_date ? 1 : 0;
    return sort === "due_asc" ? cmp : -cmp;
  });
}

export default function TodosPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [filter, setFilter] = useState<Filter>("active");
  const [sort, setSort] = useState<Sort>("default");
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editingTodo, setEditingTodo] = useState<Todo | null>(null);

  const { data, isLoading, isError } = $api.useQuery("get", "/todos", {
    params: { query: { root_only: true, limit: 100 } },
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

  const displayed = applySort(applyFilter(data?.items ?? [], filter), sort);

  function cycleSort() {
    setSort((prev) => SORT_CYCLE[(SORT_CYCLE.indexOf(prev) + 1) % SORT_CYCLE.length]);
  }

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
    <div className="p-6 max-w-3xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold">To-dos</h1>
        <Button size="sm" onClick={openCreate}>
          <Plus className="h-4 w-4 mr-1" />
          New
        </Button>
      </div>

      {/* Filter tabs + sort control */}
      <div className="flex items-center justify-between border-b mb-4">
        <div className="flex">
          {FILTERS.map(({ key, label }) => {
            const count =
              key === "active"
                ? (data?.items ?? []).filter(
                    (t) => t.status === "todo" || t.status === "in_progress"
                  ).length
                : key === "done"
                ? (data?.items ?? []).filter(
                    (t) => t.status === "done" || t.status === "cancelled"
                  ).length
                : (data?.items ?? []).length;

            return (
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
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* Sort toggle */}
        <button
          type="button"
          onClick={cycleSort}
          className={cn(
            "flex items-center gap-1.5 px-2 py-1.5 mb-1 rounded-md text-xs transition-colors cursor-pointer",
            sort !== "default"
              ? "text-foreground bg-muted"
              : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
          )}
          title="Cycle sort order"
        >
          <ArrowUpDown className="h-3 w-3" />
          {SORT_LABELS[sort]}
        </button>
      </div>

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

      {!isLoading && !isError && displayed.length === 0 && (
        <div className="py-12 text-center">
          <p className="text-sm text-muted-foreground">
            {filter === "active"
              ? "Nothing active — nice work."
              : filter === "done"
              ? "No completed todos yet."
              : "No todos yet."}
          </p>
          {filter !== "done" && (
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
        <div className="space-y-0.5">
          {displayed.map((todo) => (
            <TodoRow key={todo.id} todo={todo} onEdit={openEdit} />
          ))}
        </div>
      )}

      <TodoSheet open={sheetOpen} todo={editingTodo} onClose={handleClose} />
    </div>
  );
}
