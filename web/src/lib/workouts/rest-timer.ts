"use client";

/**
 * The rest timer for a live workout (workouts-003).
 *
 * WHY THIS IS A MODULE-LEVEL STORE, NOT COMPONENT STATE: the spec requires the
 * countdown to survive navigating from an exercise detail back to the session
 * overview and returning. Component state dies on unmount, so the timer lives
 * outside React entirely — the same escape hatch `page-tree.tsx` uses for its
 * collapse set. Components subscribe; they never own the clock.
 *
 * The stored value is an absolute `endsAt` epoch, never a decrementing counter,
 * so nothing has to keep ticking for the remaining time to stay correct — a
 * component that mounts 40s later computes the right number immediately. The
 * store is also mirrored into sessionStorage so a hard reload (or Tauri's
 * static-export hard navigation) doesn't silently drop a running rest.
 */

const STORAGE_KEY = "hearth.workout.rest-timer";

export interface RestTimer {
  sessionId: string;
  /** What the member is resting from — shown in the bar. */
  label: string;
  /** Absolute epoch ms when the rest is over. */
  endsAt: number;
  /** What the countdown started from, so the bar can render progress. */
  durationSeconds: number;
}

/** The countdown when neither the template slot nor the set specifies one. */
export const DEFAULT_REST_SECONDS = 90;

let current: RestTimer | null = null;
let hydrated = false;
const listeners = new Set<() => void>();

function hydrate() {
  if (hydrated || typeof window === "undefined") return;
  hydrated = true;
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw) as RestTimer;
    // Drop a rest that already expired while the app was closed.
    if (typeof parsed?.endsAt === "number" && parsed.endsAt > Date.now()) {
      current = parsed;
    }
  } catch {
    // A corrupt entry is not worth failing a workout over.
  }
}

function persist() {
  if (typeof window === "undefined") return;
  try {
    if (current) window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(current));
    else window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Private-mode quota errors are non-fatal — the in-memory store still works.
  }
}

function emit() {
  persist();
  listeners.forEach((fn) => fn());
}

export function getRestTimer(): RestTimer | null {
  hydrate();
  return current;
}

export function subscribeRestTimer(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Start (or restart) the rest countdown. Called when a set is checked off. */
export function startRestTimer(
  sessionId: string,
  label: string,
  seconds: number | null | undefined,
) {
  const duration = seconds && seconds > 0 ? seconds : DEFAULT_REST_SECONDS;
  current = {
    sessionId,
    label,
    endsAt: Date.now() + duration * 1000,
    durationSeconds: duration,
  };
  emit();
}

export function dismissRestTimer() {
  current = null;
  emit();
}

/** Nudge a running timer by ±N seconds; dismisses it if that takes it to zero. */
export function adjustRestTimer(deltaSeconds: number) {
  if (!current) return;
  const endsAt = current.endsAt + deltaSeconds * 1000;
  if (endsAt <= Date.now()) {
    dismissRestTimer();
    return;
  }
  current = {
    ...current,
    endsAt,
    durationSeconds: Math.max(1, current.durationSeconds + deltaSeconds),
  };
  emit();
}

/** Clear the timer if it belongs to a different session than the one shown. */
export function clearRestTimerForOtherSession(sessionId: string) {
  if (current && current.sessionId !== sessionId) dismissRestTimer();
}

export function secondsRemaining(timer: RestTimer, now = Date.now()): number {
  return Math.max(0, Math.ceil((timer.endsAt - now) / 1000));
}

export function formatClock(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}
