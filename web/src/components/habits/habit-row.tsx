"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { $api } from "@/lib/api/query";
import { cn } from "@/lib/utils";
import { Circle, CheckCircle2, Loader2, Link2 } from "lucide-react";
import type { components } from "@/lib/api/schema";

type Habit = components["schemas"]["HabitWithStats"];
type Occurrence = components["schemas"]["OccurrenceResponse"];

// ── frequency label ───────────────────────────────────────────────────────────

const DOW_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const WEEKDAY_SET = new Set([0, 1, 2, 3, 4]);

export function frequencyLabel(habit: Habit): string {
  const c = (habit.cadence ?? {}) as Record<string, unknown>;
  const n = c.times_per_period as number | null | undefined;
  const dow = c.days_of_week as number[] | null | undefined;

  if (dow && dow.length > 0) {
    const sorted = [...dow].sort((a, b) => a - b);
    // Check if it's exactly Mon–Fri
    if (
      sorted.length === 5 &&
      sorted.every((d) => WEEKDAY_SET.has(d))
    ) {
      return "Weekdays";
    }
    return sorted.map((d) => DOW_SHORT[d]).join(", ");
  }

  switch (habit.frequency) {
    case "daily":    return "Daily";
    case "weekdays": return "Weekdays";
    case "weekly":   return n && n > 1 ? `${n}× / week` : "Weekly";
    case "monthly":  return n && n > 1 ? `${n}× / month` : "Monthly";
    case "custom":   return n && c.period_unit ? `${n}× / ${c.period_unit}` : "Custom";
    default:         return habit.frequency;
  }
}

// ── completion rate chip ──────────────────────────────────────────────────────

function RateChip({ value }: { value: number | null }) {
  if (value === null) {
    return <span className="text-muted-foreground/40 tabular-nums">—</span>;
  }
  const pct = Math.round(value);
  const cls =
    pct >= 90 ? "text-green-500 dark:text-green-400" :
    pct >= 70 ? "text-amber-500 dark:text-amber-400" :
    pct >= 50 ? "text-orange-500 dark:text-orange-400" :
                "text-red-500 dark:text-red-400";
  return (
    <span className={cn("tabular-nums font-medium", cls)}>
      {pct}%
    </span>
  );
}

// ── table row ─────────────────────────────────────────────────────────────────

interface HabitRowProps {
  habit: Habit;
  today: string;
  onEdit: (habit: Habit) => void;
}

export function HabitRow({ habit, today, onEdit }: HabitRowProps) {
  const router = useRouter();
  const [toggling, setToggling] = useState(false);
  const isActive = habit.status === "active";

  // Read link from cadence JSONB
  const cadence = (habit.cadence ?? {}) as Record<string, unknown>;
  const linkRaw = cadence.link as { path: string; label: string } | null | undefined;
  const habitLink = linkRaw?.path && linkRaw?.label ? linkRaw : null;

  const { data: occData, refetch } = $api.useQuery(
    "get",
    "/habits/{habit_id}/occurrences",
    {
      params: {
        path: { habit_id: habit.id },
        query: { from_date: today, to_date: today, limit: 5 },
      },
    }
  );

  const { mutateAsync: createOcc } = $api.useMutation(
    "post",
    "/habits/{habit_id}/occurrences"
  );
  const { mutateAsync: updateOcc } = $api.useMutation(
    "patch",
    "/habits/{habit_id}/occurrences/{occurrence_id}"
  );

  const occurrence: Occurrence | null = occData?.items[0] ?? null;
  const isCompleted = occurrence?.status === "completed";

  async function handleToggle(e: React.MouseEvent) {
    e.stopPropagation();
    if (!isActive) return;
    setToggling(true);
    try {
      if (!occurrence) {
        await createOcc({
          params: { path: { habit_id: habit.id } },
          body: { scheduled_date: today, status: "completed" },
        });
      } else {
        await updateOcc({
          params: { path: { habit_id: habit.id, occurrence_id: occurrence.id } },
          body: { status: occurrence.status === "completed" ? "pending" : "completed" },
        });
      }
      refetch();
    } finally {
      setToggling(false);
    }
  }

  return (
    <tr
      className={cn(
        "border-b border-border/50 hover:bg-muted/30 transition-colors cursor-pointer",
        !isActive && "opacity-50"
      )}
      onClick={() => onEdit(habit)}
    >
      {/* Name — two affordances when a link is set:
            • clicking the name/icon navigates to the linked page
            • clicking anywhere else on the row opens the edit sheet  */}
      <td className="py-2.5 pl-4 pr-3">
        <div className="flex items-center gap-2 min-w-0">
          {habitLink ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                const isExternal =
                  habitLink.path.startsWith("http://") ||
                  habitLink.path.startsWith("https://");
                if (isExternal) {
                  window.open(habitLink.path, "_blank", "noopener,noreferrer");
                } else {
                  router.push(habitLink.path);
                }
              }}
              className="flex items-center gap-1.5 min-w-0 text-left group"
              title={`Go to ${habitLink.label}`}
            >
              <span className="text-sm truncate group-hover:text-primary transition-colors">
                {habit.name}
              </span>
              <Link2 className="h-3 w-3 shrink-0 text-muted-foreground/50 group-hover:text-primary transition-colors" />
            </button>
          ) : (
            <span className="text-sm truncate cursor-pointer">{habit.name}</span>
          )}
          {habit.status === "paused" && (
            <span className="badge badge-neutral shrink-0">Paused</span>
          )}
          {habit.status === "archived" && (
            <span className="badge badge-neutral badge-faded shrink-0">Archived</span>
          )}
        </div>
      </td>

      {/* Frequency */}
      <td className="py-2.5 px-3 text-xs text-muted-foreground whitespace-nowrap">
        {frequencyLabel(habit)}
      </td>

      {/* Streak */}
      <td className="py-2.5 px-3 text-xs whitespace-nowrap">
        {isActive && habit.current_streak > 0 ? (
          <span className="font-medium text-orange-500 dark:text-orange-400 tabular-nums">
            {habit.current_streak}🔥
          </span>
        ) : (
          <span className="text-muted-foreground/40">—</span>
        )}
      </td>

      {/* 7-day rate */}
      <td className="py-2.5 px-3 text-xs">
        <RateChip value={habit.completion_rate_7d ?? null} />
      </td>

      {/* 30-day rate */}
      <td className="py-2.5 px-3 text-xs">
        <RateChip value={habit.completion_rate_30d ?? null} />
      </td>

      {/* Today toggle */}
      <td className="py-2.5 pl-3 pr-4">
        <button
          type="button"
          onClick={handleToggle}
          disabled={toggling || !isActive}
          className="block mx-auto text-muted-foreground hover:text-foreground disabled:cursor-default transition-colors"
          aria-label={isCompleted ? "Mark incomplete" : "Mark complete for today"}
        >
          {toggling ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : isCompleted ? (
            <CheckCircle2 className="h-4 w-4 text-primary" />
          ) : (
            <Circle className="h-4 w-4" />
          )}
        </button>
      </td>
    </tr>
  );
}
