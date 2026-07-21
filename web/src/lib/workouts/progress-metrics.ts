/**
 * Derived numbers for the workouts Progress tab (workouts-004).
 *
 * The API returns raw working sets and nothing else — every figure here is
 * computed on the client and NEVER stored. Warmup sets are already excluded
 * server-side (`progress_service`), so nothing in this file needs to re-filter
 * them; `is_warmup` on the payload is always false.
 */

import type { components } from "@/lib/api/schema";

export type ProgressSet = components["schemas"]["ProgressSet"];
export type ProgressSession = components["schemas"]["ProgressSession"];

/**
 * Epley estimates give unreliable numbers past ~10 reps, so a high-rep set is
 * excluded from the 1RM chart rather than plotted as a bad guess.
 */
export const EPLEY_MAX_REPS = 10;

/** Epley: 1RM ≈ weight × (1 + reps / 30). */
export function epley1RM(weight: number, reps: number): number {
  return weight * (1 + reps / 30);
}

function max(values: number[]): number | null {
  return values.length ? Math.max(...values) : null;
}

/** Heaviest working set of the session. */
export function maxWeight(session: ProgressSession): number | null {
  return max(session.sets.filter((s) => s.weight != null).map((s) => s.weight as number));
}

/**
 * Best estimated 1RM of the session, over sets of {@link EPLEY_MAX_REPS} reps
 * or fewer. Returns null when no set qualifies — that session becomes a gap in
 * the chart rather than a fabricated point.
 */
export function estimated1RM(session: ProgressSession): number | null {
  return max(
    session.sets
      .filter(
        (s) =>
          s.weight != null &&
          s.reps != null &&
          s.reps >= 1 &&
          s.reps <= EPLEY_MAX_REPS,
      )
      .map((s) => epley1RM(s.weight as number, s.reps as number)),
  );
}

/** Total working volume: sum of weight × reps. Null when nothing is weighted. */
export function volume(session: ProgressSession): number | null {
  const weighted = session.sets.filter((s) => s.weight != null && s.reps != null);
  if (!weighted.length) return null;
  return weighted.reduce((sum, s) => sum + (s.weight as number) * (s.reps as number), 0);
}

/** Most reps in a single working set — the bodyweight stand-in for max weight. */
export function maxReps(session: ProgressSession): number | null {
  return max(session.sets.filter((s) => s.reps != null).map((s) => s.reps as number));
}

/** Total reps across the session — the bodyweight stand-in for volume. */
export function totalReps(session: ProgressSession): number | null {
  const withReps = session.sets.filter((s) => s.reps != null);
  if (!withReps.length) return null;
  return withReps.reduce((sum, s) => sum + (s.reps as number), 0);
}

/**
 * True when any working set fell short of its planned reps. A NULL
 * `target_reps` means no target was set — that is not a failure.
 */
export function hasFailedSet(session: ProgressSession): boolean {
  return session.sets.some(
    (s) => s.target_reps != null && s.reps != null && s.reps < s.target_reps,
  );
}

/**
 * Bodyweight = no logged working set ever carried a weight. Such exercises get
 * the reps charts only; an empty weight chart is never rendered.
 */
export function isBodyweight(sessions: ProgressSession[]): boolean {
  return sessions.every((session) => session.sets.every((s) => s.weight == null));
}

/** "2026-07-10" → "Jul 10", without going through a timezone-shifting Date. */
export function formatSessionDate(iso: string): string {
  const [, month, day] = iso.split("-").map(Number);
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${MONTHS[month - 1]} ${day}`;
}

/** Trim trailing zeros: 135 → "135", 137.5 → "137.5", 174.16 → "174.2". */
export function formatNumber(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
}
