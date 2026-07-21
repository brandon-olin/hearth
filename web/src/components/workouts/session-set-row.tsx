"use client";

import { useEffect, useRef, useState } from "react";
import { Check, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type {
  PrefillSet,
  TrackingType,
  WorkoutSet,
} from "@/lib/workouts/session-logging";

const SAVE_DELAY = 700; // ms — matches the auto-save cadence used elsewhere

/** What a set row can write back. All fields optional; only changes are sent. */
export interface SetPatch {
  weight?: number | null;
  weight_unit?: "lbs" | "kg" | null;
  reps?: number | null;
  duration_seconds?: number | null;
  distance_meters?: number | null;
  distance_unit?: "km" | "mi" | null;
  rpe?: number | null;
  completed_at?: string | null;
}

const numOrNull = (v: string) => (v.trim() === "" ? null : Number(v));
const str = (v: number | null | undefined) => (v == null ? "" : String(v));

interface FieldState {
  weight: string;
  reps: string;
  rpe: string;
  durationMin: string;
  distanceKm: string;
}

function fieldsFromSet(set: WorkoutSet): FieldState {
  return {
    weight: str(set.weight),
    reps: str(set.reps),
    rpe: str(set.rpe),
    durationMin: set.duration_seconds == null ? "" : String(set.duration_seconds / 60),
    distanceKm: set.distance_meters == null ? "" : String(set.distance_meters / 1000),
  };
}

/**
 * One loggable set.
 *
 * GHOST VALUES: a set that has not been checked off and that the member has not
 * touched yet renders its suggestion — the API's prefill if there is one, else
 * whatever the template materialized — in a muted style. Focusing a field
 * "activates" it: the ghost styling clears for THAT field only and the input
 * empties, with the suggestion demoted to a placeholder so it is still visible.
 * Nothing is lost by focusing: checking the set off with a field left empty
 * logs the suggestion, which is what makes "same as last time" one tap.
 */
export function SessionSetRow({
  set,
  ghost,
  tracking,
  index,
  highlighted,
  showRpe,
  prefixLabel,
  onSave,
  onToggleComplete,
  onDelete,
}: {
  set: WorkoutSet;
  ghost: PrefillSet | null;
  tracking: TrackingType;
  /** 1-based display number within its group (working sets are numbered; warmups get a W). */
  index: number;
  highlighted: boolean;
  showRpe: boolean;
  /** Exercise name, shown inside superset rounds where rows interleave. */
  prefixLabel?: string;
  onSave: (patch: SetPatch) => void;
  onToggleComplete: (patch: SetPatch, nowCompleted: boolean) => void;
  onDelete: () => void;
}) {
  const [fields, setFields] = useState<FieldState>(() => fieldsFromSet(set));
  const [touched, setTouched] = useState<Set<keyof FieldState>>(new Set());
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // The field state is seeded once, on mount. Every call site keys this row by
  // `set.id`, so a different set remounts and re-seeds — while a refetch of the
  // SAME set leaves the inputs alone rather than clobbering half-typed numbers.
  // `completed_at`, `target_reps`, and `is_warmup` are read from props directly,
  // so server updates to those still land immediately.
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  const completed = set.completed_at != null;

  function suggestion(key: keyof FieldState): string {
    if (key === "weight") return str(ghost?.weight);
    if (key === "reps") return str(ghost?.reps);
    return "";
  }

  /**
   * The value this field would log right now.
   *
   * The suggestion OUTRANKS the stored value on a set that hasn't been logged.
   * That ordering matters: starting from a template materializes each set with
   * the slot's `default_weight` already stored, so preferring the stored value
   * would pin every row to the template default and the member's own history
   * would never show. The API has already resolved which suggestion wins
   * (their history, else the template default), so deferring to it here is what
   * makes "your last numbers" actually appear.
   */
  function effective(key: keyof FieldState): string {
    if (touched.has(key)) return fields[key];
    if (!completed) {
      const ghosted = suggestion(key);
      if (ghosted !== "") return ghosted;
    }
    return fields[key];
  }

  /** Ghost styling applies until the set is logged or the field is activated. */
  function isGhost(key: keyof FieldState): boolean {
    return !completed && !touched.has(key) && effective(key) !== "";
  }

  function activate(key: keyof FieldState) {
    if (touched.has(key)) return;
    setTouched((prev) => new Set(prev).add(key));
    // Activating clears the field; the suggestion survives as the placeholder
    // and is still what gets logged if the member checks the set off empty.
    setFields((prev) => ({ ...prev, [key]: "" }));
  }

  function buildPatch(source: FieldState | "effective"): SetPatch {
    const read = (k: keyof FieldState) =>
      source === "effective" ? effective(k) : source[k];
    if (tracking === "distance") {
      const km = numOrNull(read("distanceKm"));
      const min = numOrNull(read("durationMin"));
      return {
        distance_meters: km != null ? km * 1000 : null,
        distance_unit: km != null ? "km" : null,
        duration_seconds: min != null ? Math.round(min * 60) : null,
      };
    }
    if (tracking === "duration") {
      const min = numOrNull(read("durationMin"));
      return { duration_seconds: min != null ? Math.round(min * 60) : null };
    }
    const weight = numOrNull(read("weight"));
    return {
      weight,
      weight_unit: weight != null ? (ghost?.weight_unit as "lbs" | "kg" | null) ?? "lbs" : null,
      reps: numOrNull(read("reps")),
      ...(showRpe ? { rpe: numOrNull(read("rpe")) } : {}),
    };
  }

  function change(key: keyof FieldState, value: string) {
    const next = { ...fields, [key]: value };
    setFields(next);
    if (!touched.has(key)) setTouched((prev) => new Set(prev).add(key));
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => onSave(buildPatch(next)), SAVE_DELAY);
  }

  function toggleComplete() {
    if (timer.current) clearTimeout(timer.current);
    if (completed) {
      onToggleComplete({ completed_at: null }, false);
      return;
    }
    // Log the effective values, so an untouched ghost row commits its suggestion.
    const patch = buildPatch("effective");
    // Those suggestions are now real logged numbers, not ghosts — promote them
    // into local state so the row keeps showing what it just wrote (the inputs
    // are seeded on mount and deliberately not re-seeded from refetches).
    const logged: FieldState = {
      weight: effective("weight"),
      reps: effective("reps"),
      rpe: effective("rpe"),
      durationMin: effective("durationMin"),
      distanceKm: effective("distanceKm"),
    };
    setFields(logged);
    setTouched(new Set(Object.keys(logged) as (keyof FieldState)[]));
    onToggleComplete({ ...patch, completed_at: new Date().toISOString() }, true);
  }

  const ghostClass = "text-muted-foreground/60 italic";
  const numberInput = "h-8 text-sm text-center";

  return (
    <div
      className={cn(
        "flex gap-2 items-center rounded-md px-1.5 py-1 transition-colors",
        highlighted && !completed && "bg-primary/5 ring-1 ring-primary/30",
        completed && "opacity-80",
        set.is_warmup && "scale-[0.97] origin-left",
      )}
    >
      {set.is_warmup ? (
        <span className="badge badge-neutral shrink-0 w-6 justify-center" aria-label="Warmup set">
          W
        </span>
      ) : (
        <span className="text-xs text-muted-foreground w-6 text-center shrink-0 tabular-nums">
          {index}
        </span>
      )}

      {prefixLabel && (
        <span className="text-xs text-muted-foreground truncate w-24 shrink-0">
          {prefixLabel}
        </span>
      )}

      {tracking === "reps" && (
        <>
          <Input
            type="number" min="0" step="2.5" inputMode="decimal"
            aria-label="Weight"
            placeholder={str(ghost?.weight) || "0"}
            value={effective("weight")}
            onFocus={() => activate("weight")}
            onChange={(e) => change("weight", e.target.value)}
            className={cn(numberInput, "w-20", isGhost("weight") && ghostClass)}
          />
          <span className="text-xs text-muted-foreground shrink-0">×</span>
          <Input
            type="number" min="0" inputMode="numeric"
            aria-label="Reps"
            placeholder={str(ghost?.reps) || "0"}
            value={effective("reps")}
            onFocus={() => activate("reps")}
            onChange={(e) => change("reps", e.target.value)}
            className={cn(numberInput, "w-16", isGhost("reps") && ghostClass)}
          />
          {set.target_reps != null && (
            <span className="text-[11px] text-muted-foreground shrink-0 hidden sm:inline">
              — target: {set.target_reps}
            </span>
          )}
          {showRpe && (
            <Input
              type="number" min="1" max="10" inputMode="numeric"
              aria-label="RPE"
              placeholder="RPE"
              value={effective("rpe")}
              onFocus={() => activate("rpe")}
              onChange={(e) => change("rpe", e.target.value)}
              className={cn(numberInput, "w-14")}
            />
          )}
        </>
      )}

      {tracking === "distance" && (
        <>
          <Input
            type="number" min="0" step="0.1" inputMode="decimal"
            aria-label="Distance in kilometres"
            placeholder="km"
            value={fields.distanceKm}
            onChange={(e) => change("distanceKm", e.target.value)}
            className={cn(numberInput, "w-20")}
          />
          <span className="text-xs text-muted-foreground shrink-0">km ·</span>
          <Input
            type="number" min="0" inputMode="numeric"
            aria-label="Duration in minutes"
            placeholder="min"
            value={fields.durationMin}
            onChange={(e) => change("durationMin", e.target.value)}
            className={cn(numberInput, "w-16")}
          />
        </>
      )}

      {tracking === "duration" && (
        <>
          <Input
            type="number" min="0" inputMode="numeric"
            aria-label="Duration in minutes"
            placeholder="min"
            value={fields.durationMin}
            onChange={(e) => change("durationMin", e.target.value)}
            className={cn(numberInput, "w-20")}
          />
          <span className="text-xs text-muted-foreground shrink-0">min</span>
        </>
      )}

      <button
        type="button"
        onClick={toggleComplete}
        aria-label={completed ? "Mark set not done" : "Mark set done"}
        aria-pressed={completed}
        className={cn(
          "h-7 w-7 rounded-md border flex items-center justify-center shrink-0 ml-auto transition-colors",
          completed
            ? "bg-primary border-primary text-primary-foreground"
            : "border-input text-muted-foreground hover:border-primary hover:text-primary",
        )}
      >
        <Check className="h-4 w-4" />
      </button>

      <button
        type="button"
        onClick={onDelete}
        aria-label="Remove set"
        className="text-muted-foreground hover:text-destructive transition-colors p-0.5 shrink-0"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
