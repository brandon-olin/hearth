"use client";

import { useState } from "react";
import { $api } from "@/lib/api/query";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { HabitRow } from "@/components/habits/habit-row";
import { HabitSheet } from "@/components/habits/habit-sheet";
import { Plus, Loader2, Repeat } from "lucide-react";
import type { components } from "@/lib/api/schema";

type Habit = components["schemas"]["HabitWithStats"];
type StatusFilter = "active" | "all" | "paused";

function toLocalDateString(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function applyFilter(habits: Habit[], filter: StatusFilter): Habit[] {
  if (filter === "active") return habits.filter((h) => h.status === "active");
  if (filter === "paused") return habits.filter((h) => h.status !== "active");
  return habits;
}

export default function HabitsPage() {
  const today = toLocalDateString(new Date());
  const [filter, setFilter] = useState<StatusFilter>("active");
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
    <div className="page-content-wide">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <Repeat className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-xl font-semibold">Habits</h1>
        </div>
        <div className="flex items-center gap-2">
          <Select
            value={filter}
            onChange={(e) => setFilter(e.target.value as StatusFilter)}
            className="text-xs h-8 w-32"
          >
            <option value="active">Active</option>
            <option value="paused">Paused</option>
            <option value="all">All</option>
          </Select>
          <Button size="sm" onClick={openCreate}>
            <Plus className="h-4 w-4 mr-1" />
            New
          </Button>
        </div>
      </div>

      {/* Loading / error */}
      {isLoading && (
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading…
        </div>
      )}

      {isError && (
        <p className="py-8 text-sm text-destructive">Failed to load habits.</p>
      )}

      {/* Table */}
      {!isLoading && !isError && (
        <>
          {displayed.length === 0 ? (
            <div className="py-12 text-center">
              <p className="text-sm text-muted-foreground">
                {filter === "active"
                  ? "No active habits yet."
                  : filter === "paused"
                  ? "No paused habits."
                  : "No habits yet."}
              </p>
              {filter !== "paused" && (
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
          ) : (
            <div className="rounded-md border border-border overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/40">
                    <th className="py-2.5 pl-4 pr-3 text-left text-xs font-medium text-muted-foreground">
                      Habit
                    </th>
                    <th className="py-2.5 px-3 text-left text-xs font-medium text-muted-foreground whitespace-nowrap">
                      Frequency
                    </th>
                    <th className="py-2.5 px-3 text-left text-xs font-medium text-muted-foreground">
                      Streak
                    </th>
                    <th className="py-2.5 px-3 text-left text-xs font-medium text-muted-foreground">
                      7 days
                    </th>
                    <th className="py-2.5 px-3 text-left text-xs font-medium text-muted-foreground">
                      30 days
                    </th>
                    <th className="py-2.5 pl-3 pr-4 text-center text-xs font-medium text-muted-foreground">
                      Today
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {displayed.map((habit) => (
                    <HabitRow
                      key={habit.id}
                      habit={habit}
                      today={today}
                      onEdit={openEdit}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      <HabitSheet open={sheetOpen} habit={editingHabit} onClose={handleClose} />
    </div>
  );
}
