"use client";

import { $api } from "@/lib/api/query";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { Loader2, Dumbbell } from "lucide-react";
import type { components } from "@/lib/api/schema";

type SessionExercise = components["schemas"]["SessionExerciseResponse"];
type WorkoutSet = components["schemas"]["WorkoutSetResponse"];

/**
 * The API serializes UTC datetimes without a timezone indicator (no Z / offset).
 * Without a suffix, browsers interpret the string as *local* time — wrong.
 * Appending "Z" forces correct UTC interpretation.
 */
function normalizeIso(iso: string): string {
  if (!iso.endsWith("Z") && !/[+-]\d\d:\d\d$/.test(iso)) return iso + "Z";
  return iso;
}

function formatDateTime(iso: string): string {
  return new Date(normalizeIso(iso)).toLocaleString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Render a single logged set as a compact human-readable summary. */
function setSummary(set: WorkoutSet): string {
  const parts: string[] = [];
  if (set.reps != null) {
    parts.push(`${set.reps} rep${set.reps === 1 ? "" : "s"}`);
  } else if (set.target_reps != null) {
    parts.push(`${set.target_reps} target`);
  }
  if (set.weight != null) parts.push(`${set.weight}${set.weight_unit ?? ""}`);
  if (set.distance_meters != null) {
    parts.push(`${set.distance_meters}${set.distance_unit ?? "m"}`);
  }
  if (set.duration_seconds != null) parts.push(`${set.duration_seconds}s`);
  if (set.rpe != null) parts.push(`RPE ${set.rpe}`);
  return parts.length ? parts.join(" · ") : "—";
}

function ExerciseBlock({ se }: { se: SessionExercise }) {
  const name = se.exercise?.name ?? "Exercise";
  return (
    <div className="rounded-lg border bg-card px-4 py-3">
      <p className="text-sm font-semibold">{name}</p>
      {se.notes && (
        <p className="text-xs text-muted-foreground mt-0.5">{se.notes}</p>
      )}
      {se.sets.length > 0 ? (
        <ul className="mt-2 space-y-1">
          {se.sets.map((set, i) => (
            <li
              key={set.id}
              className="flex items-center gap-2 text-xs text-muted-foreground"
            >
              <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-muted text-[10px] font-medium text-foreground">
                {set.set_number || i + 1}
              </span>
              <span>{setSummary(set)}</span>
              {set.is_warmup && (
                <span className="badge badge-neutral badge-faded">Warm-up</span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">No sets logged.</p>
      )}
    </div>
  );
}

interface SessionSheetProps {
  open: boolean;
  sessionId: string | null;
  onClose: () => void;
}

/**
 * Read-only view of a logged workout session (workouts-005). Sessions are
 * personal — the backing endpoint scopes to the current user server-side, so
 * this never renders another member's log.
 */
export function SessionSheet({ open, sessionId, onClose }: SessionSheetProps) {
  const { data, isLoading } = $api.useQuery(
    "get",
    "/workouts/sessions/{session_id}",
    { params: { path: { session_id: sessionId ?? "" } } },
    { enabled: open && sessionId != null },
  );

  const title = data?.name?.trim() || "Workout";

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-md overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <Dumbbell className="h-4 w-4 shrink-0" />
            {title}
          </SheetTitle>
          <SheetDescription>
            {data ? formatDateTime(data.started_at) : "Logged workout"}
          </SheetDescription>
        </SheetHeader>

        <div className="mt-6 space-y-3 px-4 pb-6">
          {isLoading || !data ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : data.exercises.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No exercises were logged in this session.
            </p>
          ) : (
            data.exercises.map((se) => <ExerciseBlock key={se.id} se={se} />)
          )}

          {data?.notes && (
            <div className="rounded-lg border bg-muted/30 px-4 py-3">
              <p className="text-xs font-medium text-muted-foreground">Notes</p>
              <p className="mt-1 text-sm whitespace-pre-wrap">{data.notes}</p>
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
