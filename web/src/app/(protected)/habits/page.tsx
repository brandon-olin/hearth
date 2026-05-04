"use client";

import { useState } from "react";
import { $api } from "@/lib/api/query";
import { Button } from "@/components/ui/button";
import { HabitRow } from "@/components/habits/habit-row";
import { HabitSheet } from "@/components/habits/habit-sheet";
import { cn } from "@/lib/utils";
import { Plus, Loader2 } from "lucide-react";
import type { components } from "@/lib/api/schema";

type Habit = components["schemas"]["HabitResponse"];
type Filter = "active" | "all" | "inactive";

function toLocalDateString(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const FILTERS: { key: Filter; label: string }[] = [
  { key: "active", label: "Active" },
  { key: "all", label: "All" },
  { key: "inactive", label: "Inactive" },
];

function applyFilter(habits: Habit[], filter: Filter): Habit[] {
  if (filter === "active") return habits.filter((h) => h.is_active);
  if (filter === "inactive") return habits.filter((h) => !h.is_active);
  return habits;
}

export default function HabitsPage() {
  const today = toLocalDateString(new Date());
  const [filter, setFilter] = useState<Filter>("active");
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editingHabit, setEditingHabit] = useState<Habit | null>(null);

  const { data, isLoading, isError } = $api.useQuery("get", "/habits", {
    params: { query: { limit: 100 } },
  });

  const displayed = applyFilter(data?.items ?? [], filter);

  function openCreate() {
    setEditingHabit(null);
    setSheetOpen(true);
  }

  function openEdit(habit: Habit) {
    setEditingHabit(habit);
    setSheetOpen(true);
  }

  function handleClose() {
    setSheetOpen(false);
    setTimeout(() => setEditingHabit(null), 300);
  }

  return (
    <div className="p-6 max-w-3xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold">Habits</h1>
        <Button size="sm" onClick={openCreate}>
          <Plus className="h-4 w-4 mr-1" />
          New
        </Button>
      </div>

      {/* Filter tabs */}
      <div className="flex border-b mb-4">
        {FILTERS.map(({ key, label }) => {
          const count =
            key === "active"
              ? (data?.items ?? []).filter((h) => h.is_active).length
              : key === "inactive"
              ? (data?.items ?? []).filter((h) => !h.is_active).length
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

      {/* Content */}
      {isLoading && (
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading…
        </div>
      )}

      {isError && (
        <p className="py-8 text-sm text-destructive">Failed to load habits.</p>
      )}

      {!isLoading && !isError && displayed.length === 0 && (
        <div className="py-12 text-center">
          <p className="text-sm text-muted-foreground">
            {filter === "active"
              ? "No active habits yet."
              : filter === "inactive"
              ? "No inactive habits."
              : "No habits yet."}
          </p>
          {filter !== "inactive" && (
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
          {displayed.map((habit) => (
            <HabitRow
              key={habit.id}
              habit={habit}
              today={today}
              onEdit={openEdit}
            />
          ))}
        </div>
      )}

      <HabitSheet open={sheetOpen} habit={editingHabit} onClose={handleClose} />
    </div>
  );
}
