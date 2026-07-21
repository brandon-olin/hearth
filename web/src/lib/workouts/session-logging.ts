/**
 * Pure helpers for the live session logger (workouts-003).
 *
 * Everything here is arithmetic over the session tree the API already returns —
 * no fetching, no React — so the completion indicator, the ghost-value
 * resolution, and the superset round layout can be reasoned about (and reused
 * by the overview, the exercise detail, and the superset detail) in one place.
 */
import type { components } from "@/lib/api/schema";

export type SessionExercise = components["schemas"]["SessionExerciseResponse"];
export type WorkoutSet = components["schemas"]["WorkoutSetResponse"];
export type ExercisePrefill = components["schemas"]["SessionExercisePrefill"];
export type PrefillSet = components["schemas"]["PrefillSet"];

export type TrackingType = "reps" | "duration" | "distance";

/** Sets in the order they are logged: by set_number, warmups first at equal numbers. */
export function orderedSets(se: SessionExercise): WorkoutSet[] {
  return [...se.sets].sort(
    (a, b) => a.set_number - b.set_number || Number(a.is_warmup) - Number(b.is_warmup),
  );
}

export function warmupSets(se: SessionExercise): WorkoutSet[] {
  return orderedSets(se).filter((s) => s.is_warmup);
}

/**
 * Working sets — the only ones the completion indicator counts. Warmup sets are
 * deliberately excluded: "✓ 2/3 sets" means two of three WORKING sets are done,
 * so adding a warmup can never make an exercise look further from finished.
 */
export function workingSets(se: SessionExercise): WorkoutSet[] {
  return orderedSets(se).filter((s) => !s.is_warmup);
}

export interface Completion {
  done: number;
  total: number;
}

export function completionOf(se: SessionExercise): Completion {
  const working = workingSets(se);
  return {
    done: working.filter((s) => s.completed_at != null).length,
    total: working.length,
  };
}

/** Roll several exercises' completion into one (used for collapsed supersets). */
export function sumCompletion(list: Completion[]): Completion {
  return list.reduce(
    (acc, c) => ({ done: acc.done + c.done, total: acc.total + c.total }),
    { done: 0, total: 0 },
  );
}

/** "3×8" / "3 sets" from a session exercise's planned targets. */
export function sessionTargetSummary(se: SessionExercise): string {
  const working = workingSets(se);
  const target = working.find((s) => s.target_reps != null)?.target_reps;
  if (working.length && target != null) return `${working.length}×${target}`;
  if (working.length) return `${working.length} ${working.length === 1 ? "set" : "sets"}`;
  return "No sets yet";
}

// ── Ghost values ────────────────────────────────────────────────────────────
//
// The API resolves WHERE a suggestion comes from (this member's history, then
// the template's defaults, then nothing) and never returns another member's
// numbers. This side only decides which suggestion lines up with which set.

/**
 * The suggestion for one set. Matched by set_number so set 3 is compared with
 * last time's set 3; sets beyond what was logged last time reuse the final
 * suggestion, which is what "just keep going at that weight" means in practice.
 */
export function ghostForSet(
  prefill: ExercisePrefill | undefined,
  set: WorkoutSet,
): PrefillSet | null {
  if (!prefill || prefill.sets.length === 0) return null;
  const pool = prefill.sets.filter((p) => p.is_warmup === set.is_warmup);
  const candidates = pool.length > 0 ? pool : prefill.sets;
  return (
    candidates.find((p) => p.set_number === set.set_number) ??
    candidates[candidates.length - 1] ??
    null
  );
}

/** The rest countdown for an exercise: the set's own value, else the slot's. */
export function restSecondsFor(
  prefill: ExercisePrefill | undefined,
  set: WorkoutSet | null,
): number | null {
  return set?.rest_seconds ?? prefill?.rest_seconds ?? null;
}

// ── Superset rounds ─────────────────────────────────────────────────────────

export interface RoundEntry {
  exercise: SessionExercise;
  set: WorkoutSet | null;
}

export interface Round {
  /** 1-based round number, as displayed ("ROUND 2"). */
  number: number;
  entries: RoundEntry[];
}

/**
 * Interleave a superset's members by round: round 1 is every member's first
 * working set, round 2 their second, and so on. A member with fewer sets than
 * the round count contributes an empty slot rather than shifting the others up.
 */
export function buildRounds(members: SessionExercise[]): Round[] {
  const perMember = members.map((m) => workingSets(m));
  const count = perMember.reduce((max, sets) => Math.max(max, sets.length), 0);
  return Array.from({ length: count }, (_, i) => ({
    number: i + 1,
    entries: members.map((exercise, m) => ({
      exercise,
      set: perMember[m][i] ?? null,
    })),
  }));
}

/** True once every set present in the round has been checked off. */
export function roundIsComplete(round: Round): boolean {
  const present = round.entries.filter((e) => e.set != null);
  return present.length > 0 && present.every((e) => e.set!.completed_at != null);
}

// ── Formatting ──────────────────────────────────────────────────────────────

export function formatDuration(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function formatVolume(volume: number, unit: string | null): string {
  if (volume <= 0) return "—";
  return `${Math.round(volume).toLocaleString()} ${unit ?? "lbs"}`;
}
