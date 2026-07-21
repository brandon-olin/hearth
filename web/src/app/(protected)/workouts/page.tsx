"use client";

import { useState, useEffect, useRef } from "react";
import { $api } from "@/lib/api/query";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { Plus, X, Loader2, Dumbbell, Trash2, Check, AlertCircle } from "lucide-react";
import type { components } from "@/lib/api/schema";

type SessionSummary  = components["schemas"]["WorkoutSessionResponse"];
type SessionDetail   = components["schemas"]["WorkoutSessionDetailResponse"];
type SessionExercise = components["schemas"]["SessionExerciseResponse"];
type SetResponse     = components["schemas"]["WorkoutSetResponse"];

// The exercise catalog's tracking_type drives which set fields we collect.
type TrackingType = "reps" | "duration" | "distance";

const TRACKING_LABELS: Record<TrackingType, string> = {
  reps: "Strength",
  distance: "Cardio",
  duration: "Timed",
};

const SAVE_DELAY = 700; // ms
type SaveStatus = "idle" | "saving" | "saved" | "error";

// ── date helpers ────────────────────────────────────────────────────────────────
// Sessions store a full `started_at` timestamp; the workout log is date-oriented.
// New sessions are anchored at NOON UTC of the chosen day (matching migrations
// 0048/0049) so the calendar day is stable across US timezones — which also means
// the UTC date slice equals the intended calendar day.

function toLocalDateString(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function startedAtToDate(iso: string): string {
  return iso.slice(0, 10);
}

function dateToStartedAt(dateStr: string): string {
  return `${dateStr}T12:00:00Z`;
}

function formatDate(s: string): string {
  const [y, m, d] = s.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  const today = toLocalDateString(new Date());
  const yesterday = toLocalDateString(new Date(Date.now() - 86_400_000));
  if (s === today) return "Today";
  if (s === yesterday) return "Yesterday";
  return date.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
}

// ── value conversions (storage unit ↔ display unit) ─────────────────────────────

const metersToKm  = (m: number | null) => (m == null ? "" : String(m / 1000));
const secsToMin    = (s: number | null) => (s == null ? "" : String(s / 60));
const numOrNull    = (v: string) => (v.trim() === "" ? null : Number(v));

// ── save badge ──────────────────────────────────────────────────────────────────

function SaveBadge({ status }: { status: SaveStatus }) {
  if (status === "idle") return null;
  if (status === "saving") return (
    <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
      <Loader2 className="h-2.5 w-2.5 animate-spin" /> Saving
    </span>
  );
  if (status === "saved") return (
    <span className="flex items-center gap-1 text-[10px] text-primary">
      <Check className="h-2.5 w-2.5" /> Saved
    </span>
  );
  return (
    <span className="flex items-center gap-1 text-[10px] text-destructive">
      <AlertCircle className="h-2.5 w-2.5" /> Error
    </span>
  );
}

// ── set state ────────────────────────────────────────────────────────────────────
// One editable set. Fields are kept as strings; only those relevant to the parent
// exercise's tracking_type are rendered and saved.

interface SetState {
  id: string;
  weight: string;       // reps tracking (lbs)
  reps: string;         // reps tracking
  distance_km: string;  // distance tracking
  duration_min: string; // distance / duration tracking
  is_warmup: boolean;
  saveStatus: SaveStatus;
}

function setResponseToState(s: SetResponse): SetState {
  return {
    id: s.id,
    weight: s.weight != null ? String(s.weight) : "",
    reps: s.reps != null ? String(s.reps) : "",
    distance_km: metersToKm(s.distance_meters),
    duration_min: secsToMin(s.duration_seconds),
    is_warmup: s.is_warmup,
    saveStatus: "saved",
  };
}

function setStateToBody(s: SetState, tracking: TrackingType) {
  if (tracking === "reps") {
    const weight = numOrNull(s.weight);
    return {
      reps: numOrNull(s.reps),
      weight,
      weight_unit: weight != null ? ("lbs" as const) : null,
      is_warmup: s.is_warmup,
    };
  }
  if (tracking === "distance") {
    const km = numOrNull(s.distance_km);
    const min = numOrNull(s.duration_min);
    return {
      distance_meters: km != null ? km * 1000 : null,
      distance_unit: km != null ? ("km" as const) : null,
      duration_seconds: min != null ? Math.round(min * 60) : null,
    };
  }
  // duration
  const min = numOrNull(s.duration_min);
  return { duration_seconds: min != null ? Math.round(min * 60) : null };
}

// ── SetRow ───────────────────────────────────────────────────────────────────────

function SetRow({
  index,
  set,
  tracking,
  onChange,
  onDelete,
}: {
  index: number;
  set: SetState;
  tracking: TrackingType;
  onChange: (patch: Partial<SetState>) => void;
  onDelete: () => void;
}) {
  return (
    <div className="flex gap-2 items-center">
      <span className="text-[10px] text-muted-foreground w-5 text-center shrink-0">{index + 1}</span>

      {tracking === "reps" && (
        <>
          <Input
            type="number" min="0" step="2.5" placeholder="0"
            value={set.weight}
            onChange={(e) => onChange({ weight: e.target.value })}
            className="h-7 text-xs w-20 text-center"
          />
          <span className="text-xs text-muted-foreground shrink-0">×</span>
          <Input
            type="number" min="1" placeholder="0"
            value={set.reps}
            onChange={(e) => onChange({ reps: e.target.value })}
            className="h-7 text-xs w-16 text-center"
          />
        </>
      )}

      {tracking === "distance" && (
        <>
          <Input
            type="number" min="0" step="0.1" placeholder="km"
            value={set.distance_km}
            onChange={(e) => onChange({ distance_km: e.target.value })}
            className="h-7 text-xs w-20 text-center"
          />
          <span className="text-xs text-muted-foreground shrink-0">km ·</span>
          <Input
            type="number" min="0" placeholder="min"
            value={set.duration_min}
            onChange={(e) => onChange({ duration_min: e.target.value })}
            className="h-7 text-xs w-16 text-center"
          />
        </>
      )}

      {tracking === "duration" && (
        <>
          <Input
            type="number" min="0" placeholder="min"
            value={set.duration_min}
            onChange={(e) => onChange({ duration_min: e.target.value })}
            className="h-7 text-xs w-20 text-center"
          />
          <span className="text-xs text-muted-foreground shrink-0">min</span>
        </>
      )}

      <SaveBadge status={set.saveStatus} />
      <button
        type="button"
        onClick={onDelete}
        className="text-muted-foreground hover:text-destructive transition-colors p-0.5 ml-auto shrink-0"
        aria-label="Remove set"
      >
        <X className="h-3 w-3" />
      </button>
    </div>
  );
}

// ── ExerciseCard ─────────────────────────────────────────────────────────────────
// One session_exercise: its catalog name + sets. The exercise itself is a shared
// catalog entity, so its name is not edited here — remove and re-add to change it.

function ExerciseCard({
  sessionId,
  se,
  onRemoved,
}: {
  sessionId: string;
  se: SessionExercise;
  onRemoved: () => void;
}) {
  const tracking = (se.exercise?.tracking_type ?? "reps") as TrackingType;
  const [sets, setSets] = useState<SetState[]>(() => se.sets.map(setResponseToState));

  const addSet    = $api.useMutation("post",   "/workouts/sessions/{session_id}/exercises/{se_id}/sets");
  const patchSet  = $api.useMutation("patch",  "/workouts/sessions/{session_id}/exercises/{se_id}/sets/{set_id}");
  const deleteSet = $api.useMutation("delete", "/workouts/sessions/{session_id}/exercises/{se_id}/sets/{set_id}");
  const removeExercise = $api.useMutation("delete", "/workouts/sessions/{session_id}/exercises/{se_id}");

  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  function scheduleSave(next: SetState) {
    const existing = timers.current.get(next.id);
    if (existing) clearTimeout(existing);
    const t = setTimeout(async () => {
      timers.current.delete(next.id);
      setSets((prev) => prev.map((s) => (s.id === next.id ? { ...s, saveStatus: "saving" } : s)));
      try {
        await patchSet.mutateAsync({
          params: { path: { session_id: sessionId, se_id: se.id, set_id: next.id } },
          body: setStateToBody(next, tracking),
        });
        setSets((prev) => prev.map((s) => (s.id === next.id ? { ...s, saveStatus: "saved" } : s)));
      } catch {
        setSets((prev) => prev.map((s) => (s.id === next.id ? { ...s, saveStatus: "error" } : s)));
      }
    }, SAVE_DELAY);
    timers.current.set(next.id, t);
  }

  function handleSetChange(id: string, patch: Partial<SetState>) {
    setSets((prev) => {
      const next = prev.map((s) => (s.id === id ? { ...s, ...patch } : s));
      const changed = next.find((s) => s.id === id);
      if (changed) scheduleSave(changed);
      return next;
    });
  }

  async function handleAddSet() {
    // Carry the previous set's weight forward for convenience (strength).
    const prev = sets[sets.length - 1];
    const body = tracking === "reps" && prev?.weight
      ? { weight: Number(prev.weight), weight_unit: "lbs" as const, is_warmup: false }
      : { is_warmup: false };
    try {
      const created = await addSet.mutateAsync({
        params: { path: { session_id: sessionId, se_id: se.id } },
        body,
      });
      setSets((prev2) => [...prev2, setResponseToState(created)]);
    } catch { /* TODO: toast */ }
  }

  async function handleDeleteSet(id: string) {
    const t = timers.current.get(id);
    if (t) { clearTimeout(t); timers.current.delete(id); }
    setSets((prev) => prev.filter((s) => s.id !== id));
    try {
      await deleteSet.mutateAsync({
        params: { path: { session_id: sessionId, se_id: se.id, set_id: id } },
      });
    } catch { console.error("Failed to delete set"); }
  }

  async function handleRemoveExercise() {
    try {
      await removeExercise.mutateAsync({
        params: { path: { session_id: sessionId, se_id: se.id } },
      });
      onRemoved();
    } catch { /* TODO: toast */ }
  }

  return (
    <div className="border rounded-lg p-3 space-y-2 bg-muted/20">
      <div className="flex gap-2 items-center">
        <span className="text-sm font-medium flex-1 truncate">{se.exercise?.name ?? "Exercise"}</span>
        <span className="text-[10px] text-muted-foreground shrink-0">
          {TRACKING_LABELS[tracking]}
        </span>
        <button
          type="button"
          onClick={handleRemoveExercise}
          className="text-muted-foreground hover:text-destructive transition-colors p-0.5 shrink-0"
          aria-label="Remove exercise"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="space-y-1">
        {tracking === "reps" && sets.length > 0 && (
          <div className="flex gap-2 items-center pl-1">
            <span className="text-[10px] text-muted-foreground w-5 text-center">#</span>
            <span className="text-[10px] text-muted-foreground w-20 text-center">lbs</span>
            <span className="text-[10px] text-muted-foreground w-16 text-center">reps</span>
          </div>
        )}
        {sets.map((s, idx) => (
          <SetRow
            key={s.id}
            index={idx}
            set={s}
            tracking={tracking}
            onChange={(patch) => handleSetChange(s.id, patch)}
            onDelete={() => handleDeleteSet(s.id)}
          />
        ))}
        <button
          type="button"
          onClick={handleAddSet}
          disabled={addSet.isPending}
          className="text-xs text-primary hover:underline flex items-center gap-0.5 pt-0.5 pl-1 disabled:opacity-50"
        >
          <Plus className="h-3 w-3" /> Add set
        </button>
      </div>
    </div>
  );
}

// ── AddExerciseComposer ──────────────────────────────────────────────────────────
// Resolve a typed name to a catalog exercise (get-or-create), then attach it to
// the session with one empty set.

function AddExerciseComposer({
  sessionId,
  catalogListId,
  onAdded,
}: {
  sessionId: string;
  catalogListId: string;
  onAdded: () => void;
}) {
  const [name, setName] = useState("");
  const [tracking, setTracking] = useState<TrackingType>("reps");
  const [busy, setBusy] = useState(false);

  const createExercise = $api.useMutation("post", "/workouts/exercises");
  const addSessionExercise = $api.useMutation("post", "/workouts/sessions/{session_id}/exercises");

  async function handleAdd() {
    if (!name.trim()) return;
    setBusy(true);
    try {
      // POST /exercises is get-or-create by normalized name; tracking_type is
      // only applied when a new custom exercise is minted.
      const exercise = await createExercise.mutateAsync({
        body: { name: name.trim(), tracking_type: tracking },
      });
      await addSessionExercise.mutateAsync({
        params: { path: { session_id: sessionId } },
        body: { exercise_id: exercise.id, sets: [{ is_warmup: false }] },
      });
      setName("");
      setTracking("reps");
      onAdded();
    } catch { /* TODO: toast */ }
    finally { setBusy(false); }
  }

  return (
    <div className="flex gap-2 items-center">
      <Input
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); handleAdd(); } }}
        placeholder="Add exercise…"
        className="h-8 text-sm flex-1"
        list={catalogListId}
        autoComplete="off"
      />
      <select
        value={tracking}
        onChange={(e) => setTracking(e.target.value as TrackingType)}
        className="h-8 rounded-md border border-input bg-background px-2 text-sm shrink-0"
      >
        {Object.entries(TRACKING_LABELS).map(([k, v]) => (
          <option key={k} value={k}>{v}</option>
        ))}
      </select>
      <Button size="sm" onClick={handleAdd} disabled={busy || !name.trim()} className="h-8 shrink-0">
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
      </Button>
    </div>
  );
}

// ── SessionEditor ────────────────────────────────────────────────────────────────

function SessionEditor({
  sessionId,
  onClose,
  onDeleted,
}: {
  sessionId: string;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const qc = useQueryClient();

  const { data: session, isLoading, refetch } = $api.useQuery(
    "get",
    "/workouts/sessions/{session_id}",
    { params: { path: { session_id: sessionId } } },
    { staleTime: Infinity },
  );

  // Catalog for the add-exercise autocomplete.
  const { data: catalog } = $api.useQuery(
    "get",
    "/workouts/exercises",
    { params: { query: { limit: 500 } } },
    { staleTime: 5 * 60 * 1000 },
  );
  const catalogListId = `exercise-catalog-${sessionId}`;

  const [date, setDate]   = useState("");
  const [name, setName]   = useState("");
  const [notes, setNotes] = useState("");
  const [headerStatus, setHeaderStatus] = useState<SaveStatus>("idle");

  const patchSession  = $api.useMutation("patch",  "/workouts/sessions/{session_id}");
  const deleteSession = $api.useMutation("delete", "/workouts/sessions/{session_id}");

  useEffect(() => {
    if (!session) return;
    // Populate the edit fields once per loaded session — the established
    // form-from-entity pattern in this codebase (cf. habit-sheet.tsx).
    /* eslint-disable react-hooks/set-state-in-effect */
    setDate(startedAtToDate(session.started_at));
    setName(session.name ?? "");
    setNotes(session.notes ?? "");
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [session?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const headerTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  function scheduleHeaderSave(vals: { date: string; name: string; notes: string }) {
    if (headerTimer.current) clearTimeout(headerTimer.current);
    if (!vals.date) return;
    headerTimer.current = setTimeout(async () => {
      setHeaderStatus("saving");
      try {
        await patchSession.mutateAsync({
          params: { path: { session_id: sessionId } },
          body: {
            started_at: dateToStartedAt(vals.date),
            name: vals.name.trim() || null,
            notes: vals.notes.trim() || null,
          },
        });
        setHeaderStatus("saved");
        qc.invalidateQueries({ queryKey: ["get", "/workouts/sessions"] });
        setTimeout(() => setHeaderStatus("idle"), 2000);
      } catch {
        setHeaderStatus("error");
      }
    }, SAVE_DELAY);
  }

  function handleDateChange(v: string)  { setDate(v);  scheduleHeaderSave({ date: v, name, notes }); }
  function handleNameChange(v: string)  { setName(v);  scheduleHeaderSave({ date, name: v, notes }); }
  function handleNotesChange(v: string) { setNotes(v); scheduleHeaderSave({ date, name, notes: v }); }

  useEffect(() => {
    return () => { if (headerTimer.current) clearTimeout(headerTimer.current); };
  }, []);

  async function handleDeleteSession() {
    try {
      await deleteSession.mutateAsync({ params: { path: { session_id: sessionId } } });
      qc.invalidateQueries({ queryKey: ["get", "/workouts/sessions"] });
      onDeleted();
    } catch { /* TODO: toast */ }
  }

  // Re-fetch the detail after an exercise is added/removed so the tree stays true.
  function refreshExercises() {
    refetch();
    qc.invalidateQueries({ queryKey: ["get", "/workouts/sessions"] });
  }

  if (isLoading || !session) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const exercises = (session as SessionDetail).exercises ?? [];

  return (
    <>
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="s-date" className="text-xs">Date</Label>
            <Input id="s-date" type="date" value={date} onChange={(e) => handleDateChange(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="s-name" className="text-xs">Name (optional)</Label>
            <Input
              id="s-name"
              value={name}
              onChange={(e) => handleNameChange(e.target.value)}
              placeholder="Leg day"
            />
          </div>
        </div>

        <div className="space-y-2">
          <Label className="text-xs">Exercises</Label>

          <datalist id={catalogListId}>
            {(catalog?.items ?? []).map((e) => (
              <option key={e.id} value={e.name} />
            ))}
          </datalist>

          {exercises.length === 0 && (
            <p className="text-xs text-muted-foreground py-2 text-center">
              No exercises yet — add one below to start.
            </p>
          )}

          {exercises.map((se) => (
            <ExerciseCard
              key={se.id}
              sessionId={sessionId}
              se={se}
              onRemoved={refreshExercises}
            />
          ))}

          <AddExerciseComposer
            sessionId={sessionId}
            catalogListId={catalogListId}
            onAdded={refreshExercises}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="s-notes" className="text-xs">Session notes</Label>
          <Textarea
            id="s-notes"
            value={notes}
            rows={2}
            onChange={(e) => handleNotesChange(e.target.value)}
            placeholder="How it felt, PRs, anything notable…"
          />
        </div>
      </div>

      <div className="shrink-0 px-6 py-4 border-t flex items-center gap-2">
        <SaveBadge status={headerStatus} />
        <span className="flex-1" />
        <Button
          variant="ghost"
          size="sm"
          className="text-destructive hover:text-destructive hover:bg-destructive/10"
          onClick={handleDeleteSession}
          disabled={deleteSession.isPending}
        >
          <Trash2 className="h-3.5 w-3.5 mr-1.5" />
          Delete workout
        </Button>
        <Button variant="outline" size="sm" onClick={onClose}>
          Done
        </Button>
      </div>
    </>
  );
}

// ── WorkoutSheet ──────────────────────────────────────────────────────────────────

function WorkoutSheet({
  open,
  sessionId,
  onClose,
  onDeleted,
}: {
  open: boolean;
  sessionId: string | null;
  onClose: () => void;
  onDeleted: () => void;
}) {
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-md overflow-hidden flex flex-col gap-0 p-0">
        <SheetHeader className="px-6 py-4 border-b shrink-0">
          <SheetTitle>Workout</SheetTitle>
          <SheetDescription className="sr-only">Edit workout session</SheetDescription>
        </SheetHeader>
        {sessionId && (
          <SessionEditor sessionId={sessionId} onClose={onClose} onDeleted={onDeleted} />
        )}
      </SheetContent>
    </Sheet>
  );
}

// ── WorkoutsPage ──────────────────────────────────────────────────────────────────

export default function WorkoutsPage() {
  const qc = useQueryClient();
  const [sheetOpen,    setSheetOpen]    = useState(false);
  const [selectedId,   setSelectedId]   = useState<string | null>(null);
  const [creating,     setCreating]     = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing,     setClearing]     = useState(false);

  const { data, isLoading, isError } = $api.useQuery("get", "/workouts/sessions", {
    params: { query: { limit: 50 } },
  });

  const createSession = $api.useMutation("post", "/workouts/sessions");
  const deleteSession = $api.useMutation("delete", "/workouts/sessions/{session_id}");

  const sessions = data?.items ?? [];

  async function handleDeleteAll() {
    // The session API has no bulk-delete; remove each loaded session in turn.
    setClearing(true);
    try {
      await Promise.all(
        sessions.map((s) =>
          deleteSession.mutateAsync({ params: { path: { session_id: s.id } } }),
        ),
      );
      qc.invalidateQueries({ queryKey: ["get", "/workouts/sessions"] });
    } finally {
      setClearing(false);
      setConfirmClear(false);
    }
  }

  const grouped = sessions.reduce<Record<string, SessionSummary[]>>((acc, s) => {
    (acc[startedAtToDate(s.started_at)] ??= []).push(s);
    return acc;
  }, {});
  const sortedDates = Object.keys(grouped).sort((a, b) => b.localeCompare(a));

  async function handleStartWorkout() {
    setCreating(true);
    try {
      const session = await createSession.mutateAsync({
        body: { started_at: dateToStartedAt(toLocalDateString(new Date())) },
      });
      qc.invalidateQueries({ queryKey: ["get", "/workouts/sessions"] });
      setSelectedId(session.id);
      setSheetOpen(true);
    } catch { /* TODO: toast */ }
    finally { setCreating(false); }
  }

  function openExisting(id: string) {
    setSelectedId(id);
    setSheetOpen(true);
  }

  function handleClose() {
    setSheetOpen(false);
    qc.invalidateQueries({ queryKey: ["get", "/workouts/sessions"] });
    setTimeout(() => setSelectedId(null), 300);
  }

  function handleDeleted() {
    setSheetOpen(false);
    qc.invalidateQueries({ queryKey: ["get", "/workouts/sessions"] });
    setTimeout(() => setSelectedId(null), 300);
  }

  return (
    <div className="page-content">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <Dumbbell className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-xl font-semibold">Workouts</h1>
        </div>
        <div className="flex items-center gap-2">
          {sessions.length > 0 && (
            confirmClear ? (
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-muted-foreground">Delete all?</span>
                <Button
                  size="sm" variant="destructive"
                  onClick={handleDeleteAll}
                  disabled={clearing}
                  className="h-7 text-xs px-2"
                >
                  {clearing ? <Loader2 className="h-3 w-3 animate-spin" /> : "Yes, delete all"}
                </Button>
                <Button
                  size="sm" variant="ghost"
                  onClick={() => setConfirmClear(false)}
                  className="h-7 text-xs px-2"
                >
                  Cancel
                </Button>
              </div>
            ) : (
              <Button
                size="sm" variant="ghost"
                onClick={() => setConfirmClear(true)}
                className="h-7 text-xs text-muted-foreground hover:text-destructive px-2"
              >
                <Trash2 className="h-3.5 w-3.5 mr-1" />
                Delete all
              </Button>
            )
          )}
          <Button size="sm" onClick={handleStartWorkout} disabled={creating}>
            {creating
              ? <Loader2 className="h-4 w-4 mr-1 animate-spin" />
              : <Plus className="h-4 w-4 mr-1" />}
            Start workout
          </Button>
        </div>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </div>
      )}
      {isError && (
        <p className="py-8 text-sm text-destructive">Failed to load workouts.</p>
      )}

      {!isLoading && !isError && sessions.length === 0 && (
        <div className="py-12 text-center">
          <Dumbbell className="h-8 w-8 text-muted-foreground/30 mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">No workouts logged yet.</p>
          <Button variant="outline" size="sm" className="mt-4" onClick={handleStartWorkout} disabled={creating}>
            <Plus className="h-4 w-4 mr-1" /> Start your first workout
          </Button>
        </div>
      )}

      {sortedDates.length > 0 && (
        <div className="space-y-6">
          {sortedDates.map((date) => (
            <div key={date}>
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
                {formatDate(date)}
              </p>
              <div className="space-y-2">
                {grouped[date].map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => openExisting(s.id)}
                    className={cn(
                      "w-full text-left border rounded-lg px-4 py-3 bg-card",
                      "hover:bg-muted/30 transition-colors flex items-center gap-3",
                    )}
                  >
                    <Dumbbell className="h-4 w-4 text-muted-foreground shrink-0" />
                    <div className="flex-1 min-w-0">
                      <span className="text-sm font-medium block truncate">
                        {s.name ?? "Workout"}
                      </span>
                      <span className="text-xs text-muted-foreground truncate block">
                        {s.exercise_count === 1 ? "1 exercise" : `${s.exercise_count} exercises`}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      <WorkoutSheet
        open={sheetOpen}
        sessionId={selectedId}
        onClose={handleClose}
        onDeleted={handleDeleted}
      />
    </div>
  );
}
