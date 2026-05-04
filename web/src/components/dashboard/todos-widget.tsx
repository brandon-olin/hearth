"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import { cn } from "@/lib/utils";
import { CheckCircle2, Circle, Loader2 } from "lucide-react";
import type { components } from "@/lib/api/schema";

type Todo = components["schemas"]["TodoResponse"];

function TodoRow({
  todo,
  onToggle,
  isToggling,
}: {
  todo: Todo;
  onToggle: (id: string, currentStatus: string) => void;
  isToggling: boolean;
}) {
  const isDone = todo.status === "done";

  return (
    <button
      type="button"
      onClick={() => onToggle(todo.id, todo.status)}
      disabled={isToggling}
      className={cn(
        "flex items-start gap-3 w-full text-left rounded-md px-2 py-2 hover:bg-muted/60 transition-colors group cursor-pointer disabled:cursor-wait",
        isDone && "opacity-50"
      )}
    >
      {isToggling ? (
        <Loader2 className="h-4 w-4 mt-0.5 shrink-0 animate-spin text-muted-foreground" />
      ) : isDone ? (
        <CheckCircle2 className="h-4 w-4 mt-0.5 shrink-0 text-primary" />
      ) : (
        <Circle className="h-4 w-4 mt-0.5 shrink-0 text-muted-foreground group-hover:text-foreground transition-colors" />
      )}
      <div className="flex-1 min-w-0">
        <span
          className={cn(
            "text-sm leading-5",
            isDone && "line-through text-muted-foreground"
          )}
        >
          {todo.title}
        </span>
        {todo.due_date && !isDone && (
          <span className="ml-2 text-xs text-muted-foreground">
            {todo.due_date}
          </span>
        )}
      </div>
    </button>
  );
}

export function TodosWidget({ today }: { today: string }) {
  const qc = useQueryClient();
  const [togglingIds, setTogglingIds] = useState<Set<string>>(new Set());

  const { data, isLoading, isError } = $api.useQuery("get", "/todos", {
    params: { query: { root_only: true, limit: 50 } },
  });

  const { mutateAsync: updateTodo } = $api.useMutation(
    "patch",
    "/todos/{todo_id}"
  );

  async function handleToggle(id: string, currentStatus: string) {
    const newStatus = currentStatus === "done" ? "todo" : "done";
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

  const items = data?.items ?? [];
  const active = items.filter(
    (t) => t.status === "todo" || t.status === "in_progress"
  );
  const done = items.filter((t) => t.status === "done");
  const remaining = active.length;

  return (
    <div>
      <div className="flex items-baseline gap-2 mb-3">
        <h2 className="text-sm font-semibold">To-dos</h2>
        {!isLoading && !isError && (
          <span className="text-xs text-muted-foreground">
            {remaining === 0 ? "all done" : `${remaining} remaining`}
          </span>
        )}
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

      {!isLoading && !isError && items.length === 0 && (
        <p className="text-sm text-muted-foreground py-2">
          Nothing on your plate.
        </p>
      )}

      {active.length > 0 && (
        <div className="space-y-0.5">
          {active.map((todo) => (
            <TodoRow
              key={todo.id}
              todo={todo}
              onToggle={handleToggle}
              isToggling={togglingIds.has(todo.id)}
            />
          ))}
        </div>
      )}

      {done.length > 0 && (
        <>
          {active.length > 0 && <div className="my-3 border-t" />}
          <div className="space-y-0.5">
            {done.map((todo) => (
              <TodoRow
                key={todo.id}
                todo={todo}
                onToggle={handleToggle}
                isToggling={togglingIds.has(todo.id)}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export function todosRemainingFromData(
  data: components["schemas"]["TodoListResponse"] | undefined
): number {
  if (!data) return 0;
  return data.items.filter(
    (t) => t.status === "todo" || t.status === "in_progress"
  ).length;
}
