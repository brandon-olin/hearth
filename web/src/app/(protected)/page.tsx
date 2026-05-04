"use client";

import { useAuth } from "@/lib/auth/context";
import { TodosWidget } from "@/components/dashboard/todos-widget";
import { HabitsWidget } from "@/components/dashboard/habits-widget";

function toLocalDateString(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function greeting(hour: number): string {
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

function formatDate(dateStr: string): string {
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}

export default function DashboardPage() {
  const { user } = useAuth();
  const now = new Date();
  const today = toLocalDateString(now);
  const name = user?.display_name?.split(" ")[0] ?? user?.email ?? "there";

  return (
    <div className="flex flex-col min-h-full">
      {/* Summary strip */}
      <div className="border-b bg-muted/20 px-6 py-5 shrink-0">
        <p className="text-xs text-muted-foreground uppercase tracking-wide">
          {formatDate(today)}
        </p>
        <h1 className="text-xl font-semibold mt-1">
          {greeting(now.getHours())}, {name}.
        </h1>
      </div>

      {/* Two-column layout */}
      <div className="flex flex-col lg:flex-row gap-0 flex-1">
        {/* Todos — fills remaining width */}
        <div className="flex-1 min-w-0 p-6 lg:border-r">
          <TodosWidget today={today} />
        </div>

        {/* Habits + AI — fixed right column */}
        <div className="w-full lg:w-80 xl:w-96 shrink-0 p-6">
          <HabitsWidget today={today} />
        </div>
      </div>
    </div>
  );
}
