"use client";

/**
 * Workouts → Progress (workouts-004).
 *
 * Two views in one route: the per-exercise list (name + sparkline) and the
 * full-screen detail with the three charts behind a segmented control. Kept in
 * a single page rather than a `[id]` route because dynamic routes need the
 * `useSegmentId` / static-export dance for Tauri, and this view has no reason
 * to be linkable on its own.
 *
 * Everything shown is the CURRENT member's history — the API filters
 * created_by_user_id server-side, so another member's numbers never arrive
 * here to be filtered out.
 */

import { useState } from "react";
import Link from "next/link";
import { $api } from "@/lib/api/query";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ChevronLeft, ChevronRight, Dumbbell, Loader2, TrendingUp } from "lucide-react";
import { LineChart, Sparkline, type ChartPoint } from "@/components/workouts/progress-charts";
import {
  EPLEY_MAX_REPS,
  estimated1RM,
  formatNumber,
  formatSessionDate,
  hasFailedSet,
  isBodyweight,
  maxReps,
  maxWeight,
  totalReps,
  volume,
  type ProgressSession,
} from "@/lib/workouts/progress-metrics";

type ChartKind = "weight" | "orm" | "volume";

interface ChartSpec {
  key: ChartKind;
  label: string;
  unit?: string;
  hint: string;
  value: (session: ProgressSession) => number | null;
}

const WEIGHTED_CHARTS: ChartSpec[] = [
  {
    key: "weight",
    label: "Max weight",
    unit: "lbs",
    hint: "Heaviest working set per session.",
    value: maxWeight,
  },
  {
    key: "orm",
    label: "Est. 1RM",
    unit: "lbs",
    hint: `Epley estimate — weight × (1 + reps / 30). Sets over ${EPLEY_MAX_REPS} reps are left out; they estimate poorly.`,
    value: estimated1RM,
  },
  {
    key: "volume",
    label: "Volume",
    unit: "lbs",
    hint: "Total working volume — weight × reps, summed.",
    value: volume,
  },
];

// Bodyweight exercises have no weight to chart, so they get the reps pair only
// — never an empty weight or 1RM chart.
const BODYWEIGHT_CHARTS: ChartSpec[] = [
  {
    key: "weight",
    label: "Max reps",
    unit: "reps",
    hint: "Most reps in a single working set per session.",
    value: maxReps,
  },
  {
    key: "volume",
    label: "Volume",
    unit: "reps",
    hint: "Total reps across all working sets.",
    value: totalReps,
  },
];

function relativeDay(iso: string): string {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  if (days < 30) return `${Math.floor(days / 7)} wk ago`;
  return `${Math.floor(days / 30)} mo ago`;
}

export default function ProgressPage() {
  const [selected, setSelected] = useState<{ id: string; name: string } | null>(null);

  const { data, isLoading, isError } = $api.useQuery("get", "/workouts/progress");
  const rows = data?.items ?? [];

  return (
    <div className="page-content">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-xl font-semibold">Progress</h1>
        </div>
        <Link
          href="/workouts"
          className={cn(buttonVariants({ size: "sm", variant: "ghost" }), "text-muted-foreground")}
        >
          <Dumbbell className="h-4 w-4 mr-1" /> Workouts
        </Link>
      </div>

      {selected ? (
        <ExerciseDetail
          exerciseId={selected.id}
          name={selected.name}
          onBack={() => setSelected(null)}
        />
      ) : isLoading ? (
        <div className="flex justify-center py-16">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : isError ? (
        <p className="text-sm text-destructive py-8 text-center">
          Couldn&rsquo;t load your progress.
        </p>
      ) : rows.length === 0 ? (
        <div className="text-center py-16 text-sm text-muted-foreground space-y-1">
          <p>Nothing to chart yet.</p>
          <p>
            An exercise shows up here once you&rsquo;ve logged it in at least two
            workouts.
          </p>
        </div>
      ) : (
        <div className="border rounded-lg divide-y">
          {rows.map((row) => (
            <button
              key={row.exercise_id}
              onClick={() => setSelected({ id: row.exercise_id, name: row.name })}
              className="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-muted/50 transition-colors"
            >
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium truncate">{row.name}</div>
                <div className="text-xs text-muted-foreground">
                  {row.session_count} sessions · last {relativeDay(row.last_logged_at)}
                </div>
              </div>
              <Sparkline values={row.sparkline} />
              <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ExerciseDetail({
  exerciseId,
  name,
  onBack,
}: {
  exerciseId: string;
  name: string;
  onBack: () => void;
}) {
  const [kind, setKind] = useState<ChartKind>("weight");

  const { data, isLoading } = $api.useQuery(
    "get",
    "/workouts/progress/{exercise_id}",
    { params: { path: { exercise_id: exerciseId }, query: { limit: 20 } } },
    { enabled: !!exerciseId, staleTime: 10_000 },
  );

  const sessions = data?.sessions ?? [];
  const bodyweight = sessions.length > 0 && isBodyweight(sessions);
  const charts = bodyweight ? BODYWEIGHT_CHARTS : WEIGHTED_CHARTS;
  const spec = charts.find((c) => c.key === kind) ?? charts[0];

  const points: ChartPoint[] = sessions.map((session) => ({
    label: formatSessionDate(session.session_date),
    value: spec.value(session),
    failed: hasFailedSet(session),
  }));
  const failedCount = points.filter((p) => p.failed).length;

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <Button size="sm" variant="ghost" onClick={onBack} className="text-muted-foreground -ml-2">
          <ChevronLeft className="h-4 w-4 mr-1" /> All exercises
        </Button>
      </div>

      <h2 className="text-lg font-semibold mb-1">{name}</h2>
      <p className="text-xs text-muted-foreground mb-4">
        Last {sessions.length} {sessions.length === 1 ? "session" : "sessions"}
        {bodyweight && " · bodyweight"}
        {failedCount > 0 && (
          <>
            {" · "}
            <span className="text-destructive">
              ✗ {failedCount} {failedCount === 1 ? "session" : "sessions"} under target
            </span>
          </>
        )}
      </p>

      {/* Segmented control */}
      <div className="inline-flex items-center gap-1 rounded-md border p-0.5 mb-4">
        {charts.map((c) => (
          <button
            key={c.key}
            onClick={() => setKind(c.key)}
            className={cn(
              "px-2.5 py-1 text-xs rounded transition-colors",
              spec.key === c.key
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {c.label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="flex justify-center py-16">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : sessions.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-10">
          No logged sets for this exercise yet.
        </p>
      ) : (
        <div className="border rounded-lg p-4">
          <LineChart points={points} formatValue={formatNumber} unit={spec.unit} />
          <p className="text-xs text-muted-foreground mt-3">{spec.hint}</p>
        </div>
      )}
    </div>
  );
}
