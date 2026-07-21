"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft, ChevronRight, Dumbbell, Flag, Loader2, Plus, Timer,
} from "lucide-react";
import { $api } from "@/lib/api/query";
import { useSegmentId } from "@/lib/hooks/use-segment-id";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ExercisePicker } from "@/components/workouts/exercise-picker";
import { RestTimerBar } from "@/components/workouts/rest-timer-bar";
import { SessionSetRow, type SetPatch } from "@/components/workouts/session-set-row";
import { FinishSummary } from "@/components/workouts/finish-summary";
import { SessionDetailsPanel } from "@/components/workouts/session-details-panel";
import { useToasts, ToastViewport } from "@/components/workouts/toasts";
import {
  buildDisplayItems,
  displayItemId,
  supersetLabel,
  type DisplayItem,
} from "@/lib/workouts/template-order";
import {
  buildRounds,
  completionOf,
  formatDuration,
  ghostForSet,
  orderedSets,
  restSecondsFor,
  sessionTargetSummary,
  sumCompletion,
  warmupSets,
  workingSets,
  type ExercisePrefill,
  type SessionExercise,
  type TrackingType,
  type WorkoutSet,
} from "@/lib/workouts/session-logging";
import {
  clearRestTimerForOtherSession,
  startRestTimer,
} from "@/lib/workouts/rest-timer";
import type { components } from "@/lib/api/schema";

type Summary = components["schemas"]["WorkoutSessionSummary"];

export default function SessionLogger() {
  const id = useSegmentId(2); // /workouts/sessions/<id>
  const router = useRouter();
  const qc = useQueryClient();
  const { toasts, show } = useToasts();

  const { data: session, isLoading, isError, refetch } = $api.useQuery(
    "get",
    "/workouts/sessions/{session_id}",
    { params: { path: { session_id: id } } },
    { enabled: !!id, staleTime: 10_000 },
  );

  // Ghost values. Fetched once per session: they describe what happened BEFORE
  // this workout, so nothing logged today can change them.
  const { data: prefill } = $api.useQuery(
    "get",
    "/workouts/sessions/{session_id}/prefill",
    { params: { path: { session_id: id } } },
    { enabled: !!id, staleTime: Infinity },
  );

  const patchSet = $api.useMutation("patch", "/workouts/sessions/{session_id}/exercises/{se_id}/sets/{set_id}");
  const addSet = $api.useMutation("post", "/workouts/sessions/{session_id}/exercises/{se_id}/sets");
  const deleteSet = $api.useMutation("delete", "/workouts/sessions/{session_id}/exercises/{se_id}/sets/{set_id}");
  const addExercise = $api.useMutation("post", "/workouts/sessions/{session_id}/exercises");
  const finishSession = $api.useMutation("post", "/workouts/sessions/{session_id}/finish");

  const [openItemId, setOpenItemId] = useState<string | null>(null);
  const [showRpe, setShowRpe] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerBusy, setPickerBusy] = useState<string | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const exercises = useMemo<SessionExercise[]>(
    () => (session?.exercises ?? []) as SessionExercise[],
    [session],
  );
  const items = useMemo(() => buildDisplayItems(exercises), [exercises]);
  const prefillById = useMemo(() => {
    const map = new Map<string, ExercisePrefill>();
    for (const p of prefill?.items ?? []) map.set(p.session_exercise_id, p);
    return map;
  }, [prefill]);

  // A rest timer belongs to one workout; opening a different session retires it.
  useEffect(() => {
    if (id) clearRestTimerForOtherSession(id);
  }, [id]);

  // Live session duration in the header.
  useEffect(() => {
    if (session?.ended_at) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [session?.ended_at]);

  const openItem = items.find((it) => displayItemId(it) === openItemId) ?? null;

  function invalidate() {
    refetch();
    qc.invalidateQueries({ queryKey: ["get", "/workouts/sessions"] });
  }

  // ── Set mutations ─────────────────────────────────────────────────────────

  async function saveSet(se: SessionExercise, set: WorkoutSet, patch: SetPatch) {
    try {
      await patchSet.mutateAsync({
        params: { path: { session_id: id, se_id: se.id, set_id: set.id } },
        body: patch,
      });
    } catch {
      show("Couldn't save that set.", "error");
    }
  }

  /**
   * Checking a set off is the pivot of the whole screen: it writes the values,
   * stamps completed_at, and starts the rest countdown. `restsAfter` is what
   * separates a plain exercise (rest after every set) from a superset (rest only
   * once the round is done).
   */
  async function toggleComplete(
    se: SessionExercise,
    set: WorkoutSet,
    patch: SetPatch,
    nowCompleted: boolean,
    restsAfter: boolean,
    restLabel: string,
  ) {
    try {
      await patchSet.mutateAsync({
        params: { path: { session_id: id, se_id: se.id, set_id: set.id } },
        body: patch,
      });
      if (nowCompleted && restsAfter && !set.is_warmup) {
        startRestTimer(id, restLabel, restSecondsFor(prefillById.get(se.id), set));
      }
      invalidate();
    } catch {
      show("Couldn't update that set.", "error");
    }
  }

  /** Add a set, carrying the previous one's numbers forward as a starting point. */
  async function appendSet(se: SessionExercise, isWarmup: boolean) {
    const siblings = orderedSets(se).filter((s) => s.is_warmup === isWarmup);
    const previous = siblings[siblings.length - 1] ?? workingSets(se).slice(-1)[0];
    try {
      await addSet.mutateAsync({
        params: { path: { session_id: id, se_id: se.id } },
        body: {
          is_warmup: isWarmup,
          weight: previous?.weight ?? null,
          weight_unit: (previous?.weight_unit as "lbs" | "kg" | null) ?? null,
          reps: previous?.reps ?? null,
          target_reps: previous?.target_reps ?? null,
          rest_seconds: previous?.rest_seconds ?? null,
        },
      });
      invalidate();
    } catch {
      show("Couldn't add a set.", "error");
    }
  }

  /** "+ Add round" — one new set on every member of the superset, at once. */
  async function addRound(members: SessionExercise[]) {
    try {
      for (const member of members) {
        const previous = workingSets(member).slice(-1)[0];
        await addSet.mutateAsync({
          params: { path: { session_id: id, se_id: member.id } },
          body: {
            is_warmup: false,
            weight: previous?.weight ?? null,
            weight_unit: (previous?.weight_unit as "lbs" | "kg" | null) ?? null,
            reps: previous?.reps ?? null,
            target_reps: previous?.target_reps ?? null,
            rest_seconds: previous?.rest_seconds ?? null,
          },
        });
      }
      invalidate();
    } catch {
      show("Couldn't add a round.", "error");
    }
  }

  async function removeSet(se: SessionExercise, set: WorkoutSet) {
    try {
      await deleteSet.mutateAsync({
        params: { path: { session_id: id, se_id: se.id, set_id: set.id } },
      });
      invalidate();
    } catch {
      show("Couldn't remove that set.", "error");
    }
  }

  async function handlePickExercise(exerciseId: string) {
    setPickerBusy(exerciseId);
    try {
      await addExercise.mutateAsync({
        params: { path: { session_id: id } },
        body: { exercise_id: exerciseId, sets: [{ is_warmup: false }] },
      });
      setPickerOpen(false);
      invalidate();
    } catch {
      show("Couldn't add that exercise.", "error");
    } finally {
      setPickerBusy(null);
    }
  }

  async function handleFinish() {
    try {
      const result = await finishSession.mutateAsync({
        params: { path: { session_id: id } },
      });
      setSummary(result);
      setOpenItemId(null);
      invalidate();
    } catch {
      show("Couldn't finish the workout.", "error");
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className="page-content flex items-center gap-2 py-12 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading…
      </div>
    );
  }
  if (isError || !session) {
    return (
      <div className="page-content py-12">
        <p className="text-sm text-destructive">Workout not found.</p>
        <Link href="/workouts" className={cn(buttonVariants({ variant: "outline", size: "sm" }), "mt-4")}>
          <ChevronLeft className="h-4 w-4 mr-1" /> Back to workouts
        </Link>
      </div>
    );
  }

  if (summary) {
    return (
      <FinishSummary
        sessionId={id}
        summary={summary}
        onDone={() => router.push("/workouts")}
        onError={(m) => show(m, "error")}
      />
    );
  }

  const endedAt = session.ended_at ? new Date(session.ended_at).getTime() : now;
  const elapsed = Math.max(
    0,
    Math.floor((endedAt - new Date(session.started_at).getTime()) / 1000),
  );

  return (
    <div className="page-content pb-28">
      {/* Persistent session header — duration and Finish are always reachable. */}
      <div className="flex items-center gap-2 mb-4">
        {openItem ? (
          <button
            type="button"
            onClick={() => setOpenItemId(null)}
            className={cn(buttonVariants({ size: "sm", variant: "ghost" }), "text-muted-foreground -ml-2")}
          >
            <ChevronLeft className="h-4 w-4 mr-1" /> Overview
          </button>
        ) : (
          <Link
            href="/workouts"
            className={cn(buttonVariants({ size: "sm", variant: "ghost" }), "text-muted-foreground -ml-2")}
          >
            <ChevronLeft className="h-4 w-4 mr-1" /> Workouts
          </Link>
        )}
        <span className="flex-1" />
        <span className="flex items-center gap-1.5 text-sm text-muted-foreground tabular-nums">
          <Timer className="h-3.5 w-3.5" />
          {formatDuration(elapsed)}
        </span>
        <Button size="sm" onClick={handleFinish} disabled={finishSession.isPending}>
          {finishSession.isPending
            ? <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            : <Flag className="h-4 w-4 mr-1" />}
          Finish workout
        </Button>
      </div>

      <div className="flex items-center gap-2 mb-5">
        <Dumbbell className="h-5 w-5 text-muted-foreground shrink-0" />
        <h1 className="text-xl font-semibold truncate">
          {openItem ? itemTitle(openItem) : session.name ?? "Workout"}
        </h1>
      </div>

      {openItem ? (
        <ExerciseDetail
          item={openItem}
          prefillById={prefillById}
          showRpe={showRpe}
          onToggleRpe={() => setShowRpe((v) => !v)}
          onSaveSet={saveSet}
          onToggleComplete={toggleComplete}
          onAppendSet={appendSet}
          onAddRound={addRound}
          onRemoveSet={removeSet}
          busy={addSet.isPending}
        />
      ) : (
        <>
          <Overview
            items={items}
            onOpen={(itemId) => setOpenItemId(itemId)}
            onAddExercise={() => setPickerOpen(true)}
          />
          <SessionDetailsPanel
            session={session}
            onDeleted={() => router.push("/workouts")}
            onError={(m) => show(m, "error")}
          />
        </>
      )}

      <ExercisePicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onPick={handlePickExercise}
        busyId={pickerBusy}
      />
      <RestTimerBar sessionId={id} />
      <ToastViewport toasts={toasts} />
    </div>
  );
}

// ── Overview ─────────────────────────────────────────────────────────────────

function itemTitle(item: DisplayItem<SessionExercise>): string {
  return item.kind === "single"
    ? item.te.exercise?.name ?? "Exercise"
    : supersetLabel(item.members.map((m) => m.exercise?.name ?? "Exercise"));
}

function Overview({
  items,
  onOpen,
  onAddExercise,
}: {
  items: DisplayItem<SessionExercise>[];
  onOpen: (itemId: string) => void;
  onAddExercise: () => void;
}) {
  return (
    <div className="space-y-2">
      {items.length === 0 && (
        <p className="text-sm text-muted-foreground py-4 text-center">
          No exercises yet — add one below to start logging.
        </p>
      )}

      {items.map((item) => {
        const members = item.kind === "single" ? [item.te] : item.members;
        const completion = sumCompletion(members.map(completionOf));
        const summary =
          item.kind === "single"
            ? sessionTargetSummary(item.te)
            : `${item.members.length} exercises`;
        const finished = completion.total > 0 && completion.done === completion.total;
        return (
          <button
            key={displayItemId(item)}
            type="button"
            onClick={() => onOpen(displayItemId(item))}
            className="w-full text-left border rounded-lg px-4 py-3 bg-card hover:bg-muted/30 transition-colors flex items-center gap-3"
          >
            <div className="flex-1 min-w-0">
              <span className="text-sm font-medium block truncate">{itemTitle(item)}</span>
              <span className="text-xs text-muted-foreground">{summary}</span>
            </div>
            <span
              className={cn(
                "badge shrink-0",
                finished ? "badge-success" : completion.done > 0 ? "badge-progress" : "badge-neutral",
              )}
            >
              {finished ? "✓ " : ""}
              {completion.done}/{completion.total} sets
            </span>
            <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
          </button>
        );
      })}

      <Button variant="outline" size="sm" className="mt-1" onClick={onAddExercise}>
        <Plus className="h-4 w-4 mr-1" /> Add exercise
      </Button>
    </div>
  );
}

// ── Exercise / superset detail ───────────────────────────────────────────────

interface DetailProps {
  item: DisplayItem<SessionExercise>;
  prefillById: Map<string, ExercisePrefill>;
  showRpe: boolean;
  onToggleRpe: () => void;
  onSaveSet: (se: SessionExercise, set: WorkoutSet, patch: SetPatch) => void;
  onToggleComplete: (
    se: SessionExercise,
    set: WorkoutSet,
    patch: SetPatch,
    nowCompleted: boolean,
    restsAfter: boolean,
    restLabel: string,
  ) => void;
  onAppendSet: (se: SessionExercise, isWarmup: boolean) => void;
  onAddRound: (members: SessionExercise[]) => void;
  onRemoveSet: (se: SessionExercise, set: WorkoutSet) => void;
  busy: boolean;
}

function ExerciseDetail(props: DetailProps) {
  const { item } = props;
  return (
    <div className="space-y-4">
      {item.kind === "single"
        ? <SingleExercisePanel {...props} se={item.te} />
        : <SupersetPanel {...props} members={item.members} />}

      <label className="flex items-center gap-2 text-xs text-muted-foreground pt-2">
        <input
          type="checkbox"
          className="checkbox-themed"
          checked={props.showRpe}
          onChange={props.onToggleRpe}
        />
        Show RPE
      </label>
    </div>
  );
}

function trackingOf(se: SessionExercise): TrackingType {
  return (se.exercise?.tracking_type ?? "reps") as TrackingType;
}

function SingleExercisePanel({
  se,
  prefillById,
  showRpe,
  onSaveSet,
  onToggleComplete,
  onAppendSet,
  onRemoveSet,
  busy,
}: DetailProps & { se: SessionExercise }) {
  const prefill = prefillById.get(se.id);
  const warmups = warmupSets(se);
  const working = workingSets(se);
  const tracking = trackingOf(se);
  // The next unfinished set is highlighted, so checking one off visibly hands
  // off to the next.
  const nextSetId = working.find((s) => s.completed_at == null)?.id;
  const label = se.exercise?.name ?? "Exercise";

  return (
    <div className="border rounded-lg bg-card p-3 space-y-3">
      {/* Warmups sit above the working sets, smaller and badged, and never
          count toward the completion indicator on the overview. */}
      <div className="space-y-1">
        {warmups.map((set) => (
          <SessionSetRow
            key={set.id}
            set={set}
            ghost={ghostForSet(prefill, set)}
            tracking={tracking}
            index={0}
            highlighted={false}
            showRpe={showRpe}
            onSave={(patch) => onSaveSet(se, set, patch)}
            onToggleComplete={(patch, done) =>
              onToggleComplete(se, set, patch, done, true, label)}
            onDelete={() => onRemoveSet(se, set)}
          />
        ))}
        <button
          type="button"
          onClick={() => onAppendSet(se, true)}
          disabled={busy}
          className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1 pl-1.5 disabled:opacity-50"
        >
          <span className="badge badge-neutral">W</span> + Add warmup set
        </button>
      </div>

      <div className="space-y-1 border-t pt-3">
        {working.map((set, i) => (
          <SessionSetRow
            key={set.id}
            set={set}
            ghost={ghostForSet(prefill, set)}
            tracking={tracking}
            index={i + 1}
            highlighted={set.id === nextSetId}
            showRpe={showRpe}
            onSave={(patch) => onSaveSet(se, set, patch)}
            onToggleComplete={(patch, done) =>
              onToggleComplete(se, set, patch, done, true, label)}
            onDelete={() => onRemoveSet(se, set)}
          />
        ))}
        <button
          type="button"
          onClick={() => onAppendSet(se, false)}
          disabled={busy}
          className="text-xs text-primary hover:underline flex items-center gap-0.5 pt-1 pl-1.5 disabled:opacity-50"
        >
          <Plus className="h-3 w-3" /> Add set
        </button>
      </div>

      {se.notes && <p className="text-xs text-muted-foreground italic">{se.notes}</p>}
    </div>
  );
}

/**
 * A superset is logged by round, not by exercise: A's set 1, B's set 1, then A's
 * set 2, B's set 2. The rest timer waits for the whole round — checking off the
 * last exercise in a round is what starts it.
 */
function SupersetPanel({
  members,
  prefillById,
  showRpe,
  onSaveSet,
  onToggleComplete,
  onAddRound,
  onRemoveSet,
  busy,
}: DetailProps & { members: SessionExercise[] }) {
  const rounds = buildRounds(members);
  const label = supersetLabel(members.map((m) => m.exercise?.name ?? "Exercise"));

  return (
    <div className="space-y-3">
      {rounds.map((round) => (
        <div key={round.number} className="border rounded-lg bg-card p-3 space-y-1">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1.5">
            Round {round.number}
          </p>
          {round.entries.map(({ exercise, set }) =>
            set ? (
              <SessionSetRow
                key={set.id}
                set={set}
                ghost={ghostForSet(prefillById.get(exercise.id), set)}
                tracking={trackingOf(exercise)}
                index={round.number}
                highlighted={set.completed_at == null}
                showRpe={showRpe}
                prefixLabel={exercise.exercise?.name ?? "Exercise"}
                onSave={(patch) => onSaveSet(exercise, set, patch)}
                onToggleComplete={(patch, done) => {
                  // Rest only once every set in this round is checked off — the
                  // others are already done, so this one closing it is the cue.
                  const closesRound =
                    done &&
                    round.entries
                      .filter((e) => e.set && e.set.id !== set.id)
                      .every((e) => e.set!.completed_at != null);
                  onToggleComplete(exercise, set, patch, done, closesRound, label);
                }}
                onDelete={() => onRemoveSet(exercise, set)}
              />
            ) : (
              <div
                key={`${exercise.id}-empty-${round.number}`}
                className="text-xs text-muted-foreground pl-8 py-1"
              >
                {exercise.exercise?.name ?? "Exercise"} — no set this round
              </div>
            ),
          )}
        </div>
      ))}

      <Button variant="outline" size="sm" onClick={() => onAddRound(members)} disabled={busy}>
        <Plus className="h-4 w-4 mr-1" /> Add round
      </Button>
    </div>
  );
}
