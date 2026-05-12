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

type WorkoutSummary   = components["schemas"]["WorkoutResponse"];
type WorkoutDetail    = components["schemas"]["WorkoutWithEntriesResponse"];
type EntryResponse    = components["schemas"]["ExerciseEntryResponse"];
type ExerciseType     = "strength" | "cardio" | "hiit" | "flexibility" | "other";

const TYPE_LABELS: Record<ExerciseType, string> = {
  strength: "Strength",
  cardio: "Cardio",
  hiit: "HIIT",
  flexibility: "Flexibility",
  other: "Other",
};

const SAVE_DELAY = 700; // ms

// ── helpers ───────────────────────────────────────────────────────────────────

function toLocalDateString(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
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

// A single set: weight (lbs) + reps
interface SetData {
  weight_lbs: string;
  reps: string;
}

function metricsLabel(entry: EntryResponse): string {
  const m = (entry.metrics ?? {}) as Record<string, unknown>;
  const parts: string[] = [];

  // New format: sets is an array of {weight_lbs, reps}
  if (Array.isArray(m.sets)) {
    const labels = (m.sets as Array<{ weight_lbs?: number; reps?: number }>)
      .map((s) => {
        if (s.weight_lbs && s.reps) return `${s.weight_lbs}×${s.reps}`;
        if (s.reps) return `${s.reps} reps`;
        return "";
      })
      .filter(Boolean);
    if (labels.length) parts.push(labels.join(", "));
  } else {
    // Legacy flat format — still renderable
    if (m.sets && m.reps) parts.push(`${m.sets}×${m.reps}`);
    else if (m.reps) parts.push(`${m.reps} reps`);
    if (m.weight_lbs) parts.push(`${m.weight_lbs} lbs`);
    else if (m.weight_kg) parts.push(`${m.weight_kg} lbs`); // old data stored as lbs despite key name
  }

  if (m.duration_minutes) parts.push(`${m.duration_minutes} min`);
  if (m.distance_km) parts.push(`${m.distance_km} km`);
  return parts.join(" · ");
}

// ── entry state ───────────────────────────────────────────────────────────────

interface EntryState {
  localId: string;
  dbId: string;
  name: string;
  type: ExerciseType;
  setData: SetData[];       // per-set weight+reps (strength)
  duration_minutes: string; // cardio / hiit / flexibility
  distance_km: string;      // cardio
  notes: string;
  saveStatus: "idle" | "saving" | "saved" | "error";
}

function entryResponseToState(e: EntryResponse): EntryState {
  const m = (e.metrics ?? {}) as Record<string, unknown>;
  let setData: SetData[] = [];

  if (Array.isArray(m.sets)) {
    // New format
    setData = (m.sets as Array<{ weight_lbs?: number; reps?: number }>).map((s) => ({
      weight_lbs: s.weight_lbs != null ? String(s.weight_lbs) : "",
      reps:       s.reps       != null ? String(s.reps)       : "",
    }));
  } else if (m.sets != null || m.reps != null || m.weight_kg != null || m.weight_lbs != null) {
    // Legacy flat format — convert to single-element array
    // Note: old weight_kg field actually contained lbs values
    const w = m.weight_lbs ?? m.weight_kg;
    setData = [{
      weight_lbs: w    != null ? String(w)    : "",
      reps:       m.reps != null ? String(m.reps) : "",
    }];
  }

  return {
    localId:          e.id,
    dbId:             e.id,
    name:             e.name,
    type:             e.type as ExerciseType,
    setData,
    duration_minutes: m.duration_minutes != null ? String(m.duration_minutes) : "",
    distance_km:      m.distance_km      != null ? String(m.distance_km)      : "",
    notes:            e.notes ?? "",
    saveStatus:       "saved",
  };
}

function entryStateToMetrics(e: EntryState): Record<string, unknown> {
  const m: Record<string, unknown> = {};
  if (e.type === "strength" || e.setData.length > 0) {
    const sets = e.setData
      .filter((s) => s.weight_lbs || s.reps)
      .map((s) => ({
        ...(s.weight_lbs ? { weight_lbs: Number(s.weight_lbs) } : {}),
        ...(s.reps       ? { reps:       Number(s.reps)       } : {}),
      }));
    if (sets.length) m.sets = sets;
  }
  if (e.duration_minutes) m.duration_minutes = Number(e.duration_minutes);
  if (e.distance_km)      m.distance_km      = Number(e.distance_km);
  return m;
}

// ── save badge ────────────────────────────────────────────────────────────────

function SaveBadge({ status }: { status: "idle" | "saving" | "saved" | "error" }) {
  if (status === "idle") return null;
  if (status === "saving") return (
    <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
      <Loader2 className="h-2.5 w-2.5 animate-spin" /> Saving
    </span>
  );
  if (status === "saved") return (
    <span className="flex items-center gap-1 text-[10px] text-green-600 dark:text-green-400">
      <Check className="h-2.5 w-2.5" /> Saved
    </span>
  );
  return (
    <span className="flex items-center gap-1 text-[10px] text-destructive">
      <AlertCircle className="h-2.5 w-2.5" /> Error
    </span>
  );
}

// ── EntryRow ──────────────────────────────────────────────────────────────────

function EntryRow({
  entry,
  onChange,
  onDelete,
  exerciseNameListId,
}: {
  entry: EntryState;
  onChange: (updates: Partial<EntryState>) => void;
  onDelete: () => void;
  exerciseNameListId?: string;
}) {
  const isStrength = entry.type === "strength";
  const isCardio   = entry.type === "cardio" || entry.type === "hiit";

  function updateSet(idx: number, patch: Partial<SetData>) {
    onChange({ setData: entry.setData.map((s, i) => i === idx ? { ...s, ...patch } : s) });
  }
  function removeSet(idx: number) {
    onChange({ setData: entry.setData.filter((_, i) => i !== idx) });
  }
  function addSet() {
    // Default new set to same weight as previous set for convenience
    const prev = entry.setData[entry.setData.length - 1];
    onChange({ setData: [...entry.setData, { weight_lbs: prev?.weight_lbs ?? "", reps: "" }] });
  }

  return (
    <div className="border rounded-lg p-3 space-y-2 bg-muted/20">
      {/* Name + type + delete */}
      <div className="flex gap-2 items-center">
        <Input
          value={entry.name}
          onChange={(e) => onChange({ name: e.target.value })}
          placeholder="Exercise name"
          className="h-8 text-sm flex-1"
          list={exerciseNameListId}
          autoComplete="off"
        />
        <select
          value={entry.type}
          onChange={(e) => onChange({ type: e.target.value as ExerciseType })}
          className="h-8 rounded-md border border-input bg-background px-2 text-sm shrink-0"
        >
          {Object.entries(TYPE_LABELS).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
        <div className="flex items-center gap-1.5 shrink-0">
          <SaveBadge status={entry.saveStatus} />
          <button
            type="button"
            onClick={onDelete}
            className="text-muted-foreground hover:text-destructive transition-colors p-0.5"
            aria-label="Remove exercise"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Metrics */}
      {isStrength && (
        <div className="space-y-1">
          {/* Column headers */}
          {entry.setData.length > 0 && (
            <div className="flex gap-2 items-center pl-1">
              <span className="text-[10px] text-muted-foreground w-5 text-center">#</span>
              <span className="text-[10px] text-muted-foreground w-20 text-center">lbs</span>
              <span className="text-[10px] text-muted-foreground w-16 text-center">reps</span>
            </div>
          )}
          {entry.setData.map((set, idx) => (
            <div key={idx} className="flex gap-2 items-center">
              <span className="text-[10px] text-muted-foreground w-5 text-center shrink-0">{idx + 1}</span>
              <Input
                type="number" min="0" step="2.5"
                placeholder="0"
                value={set.weight_lbs}
                onChange={(e) => updateSet(idx, { weight_lbs: e.target.value })}
                className="h-7 text-xs w-20 text-center"
              />
              <span className="text-xs text-muted-foreground shrink-0">×</span>
              <Input
                type="number" min="1"
                placeholder="0"
                value={set.reps}
                onChange={(e) => updateSet(idx, { reps: e.target.value })}
                className="h-7 text-xs w-16 text-center"
              />
              <button
                type="button"
                onClick={() => removeSet(idx)}
                className="text-muted-foreground hover:text-destructive transition-colors p-0.5 ml-auto shrink-0"
                aria-label="Remove set"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={addSet}
            className="text-xs text-primary hover:underline flex items-center gap-0.5 pt-0.5 pl-1"
          >
            <Plus className="h-3 w-3" /> Add set
          </button>
        </div>
      )}

      {isCardio && (
        <div className="flex gap-2 flex-wrap items-center">
          <div className="flex items-center gap-1">
            <Input
              type="number" min="1"
              placeholder="0"
              value={entry.duration_minutes}
              onChange={(e) => onChange({ duration_minutes: e.target.value })}
              className="h-7 text-xs w-20 text-center"
            />
            <span className="text-xs text-muted-foreground">min</span>
          </div>
          <div className="flex items-center gap-1">
            <Input
              type="number" min="0" step="0.1"
              placeholder="0.0"
              value={entry.distance_km}
              onChange={(e) => onChange({ distance_km: e.target.value })}
              className="h-7 text-xs w-20 text-center"
            />
            <span className="text-xs text-muted-foreground">km</span>
          </div>
        </div>
      )}

      {!isStrength && !isCardio && (
        <div className="flex items-center gap-1">
          <Input
            type="number" min="1"
            placeholder="0"
            value={entry.duration_minutes}
            onChange={(e) => onChange({ duration_minutes: e.target.value })}
            className="h-7 text-xs w-20 text-center"
          />
          <span className="text-xs text-muted-foreground">min</span>
        </div>
      )}

      {/* Notes */}
      <Input
        value={entry.notes}
        onChange={(e) => onChange({ notes: e.target.value })}
        placeholder="Notes (optional)"
        className="h-7 text-xs"
      />
    </div>
  );
}

// ── WorkoutEditor ─────────────────────────────────────────────────────────────
// Manages a single workout session — always in edit mode, everything auto-saves.

function WorkoutEditor({
  workoutId,
  onClose,
  onDeleted,
}: {
  workoutId: string;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const qc = useQueryClient();

  // Load once; staleTime: Infinity prevents re-fetching while open.
  const { data: initial, isLoading } = $api.useQuery(
    "get",
    "/workouts/{workout_id}",
    { params: { path: { workout_id: workoutId } } },
    { staleTime: Infinity },
  );

  // Fetch distinct exercise names for autocomplete — stale for 5 min is fine.
  const { data: exerciseNames } = $api.useQuery(
    "get",
    "/workouts/exercise-names",
    {},
    { staleTime: 5 * 60 * 1000 },
  );
  const nameListId = `exercise-names-${workoutId}`;

  // Local edit state
  const [date,  setDate]  = useState("");
  const [name,  setName]  = useState("");
  const [notes, setNotes] = useState("");
  const [entries, setEntries] = useState<EntryState[]>([]);
  const [headerStatus, setHeaderStatus] = useState<EntryState["saveStatus"]>("idle");
  const [addingEntry, setAddingEntry] = useState(false);

  // Mutations
  const { mutateAsync: patchWorkout }  = $api.useMutation("patch", "/workouts/{workout_id}");
  const { mutateAsync: deleteWorkout } = $api.useMutation("delete", "/workouts/{workout_id}");
  const { mutateAsync: createEntry }   = $api.useMutation("post",   "/workouts/{workout_id}/entries");
  const { mutateAsync: patchEntry }    = $api.useMutation("patch",  "/workouts/{workout_id}/entries/{entry_id}");
  const { mutateAsync: deleteEntry }   = $api.useMutation("delete", "/workouts/{workout_id}/entries/{entry_id}");

  // Populate local state when workout loads (only once per workoutId).
  useEffect(() => {
    if (!initial) return;
    setDate(initial.workout_date);
    setName(initial.name ?? "");
    setNotes(initial.notes ?? "");
    setEntries((initial as WorkoutDetail).entries?.map(entryResponseToState) ?? []);
  }, [initial?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── header auto-save ───────────────────────────────────────────────────────

  const headerTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  function scheduleHeaderSave(vals: { date: string; name: string; notes: string }) {
    if (headerTimer.current) clearTimeout(headerTimer.current);
    if (!vals.date) return;
    headerTimer.current = setTimeout(async () => {
      setHeaderStatus("saving");
      try {
        await patchWorkout({
          params: { path: { workout_id: workoutId } },
          body: {
            workout_date: vals.date,
            name:  vals.name.trim()  || null,
            notes: vals.notes.trim() || null,
          },
        });
        setHeaderStatus("saved");
        qc.invalidateQueries({ queryKey: ["get", "/workouts"] });
        setTimeout(() => setHeaderStatus("idle"), 2000);
      } catch {
        setHeaderStatus("error");
      }
    }, SAVE_DELAY);
  }

  function handleDateChange(value: string)  { setDate(value);  scheduleHeaderSave({ date: value, name, notes }); }
  function handleNameChange(value: string)  { setName(value);  scheduleHeaderSave({ date, name: value, notes }); }
  function handleNotesChange(value: string) { setNotes(value); scheduleHeaderSave({ date, name, notes: value }); }

  // ── entry auto-save ────────────────────────────────────────────────────────

  const entryTimers = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  function scheduleEntrySave(entry: EntryState) {
    const existing = entryTimers.current.get(entry.localId);
    if (existing) clearTimeout(existing);

    const timer = setTimeout(async () => {
      entryTimers.current.delete(entry.localId);
      setEntries((prev) =>
        prev.map((e) => e.localId === entry.localId ? { ...e, saveStatus: "saving" } : e),
      );
      try {
        await patchEntry({
          params: { path: { workout_id: workoutId, entry_id: entry.dbId } },
          body: {
            name:    entry.name    || undefined,
            type:    entry.type    || undefined,
            metrics: entryStateToMetrics(entry),
            notes:   entry.notes.trim() || null,
          },
        });
        setEntries((prev) =>
          prev.map((e) => e.localId === entry.localId ? { ...e, saveStatus: "saved" } : e),
        );
      } catch {
        setEntries((prev) =>
          prev.map((e) => e.localId === entry.localId ? { ...e, saveStatus: "error" } : e),
        );
      }
    }, SAVE_DELAY);

    entryTimers.current.set(entry.localId, timer);
  }

  function handleEntryChange(localId: string, updates: Partial<EntryState>) {
    setEntries((prev) => {
      const next = prev.map((e) => e.localId === localId ? { ...e, ...updates } : e);
      const entry = next.find((e) => e.localId === localId);
      if (entry && entry.name.trim()) scheduleEntrySave(entry);
      return next;
    });
  }

  // ── add / delete entry ─────────────────────────────────────────────────────

  async function handleAddEntry() {
    setAddingEntry(true);
    try {
      const created = await createEntry({
        params: { path: { workout_id: workoutId } },
        body: {
          name: "Exercise",
          type: "strength",
          sort_order: entries.length,
          // Start with one empty set so the UI immediately shows the set row
          metrics: { sets: [{ weight_lbs: null, reps: null }] },
          notes: null,
        },
      });
      setEntries((prev) => [...prev, {
        ...entryResponseToState(created),
        // Ensure one empty set row shows up even if API strips nulls
        setData: created.metrics && Array.isArray((created.metrics as Record<string,unknown>).sets)
          ? entryResponseToState(created).setData
          : [{ weight_lbs: "", reps: "" }],
      }]);
    } catch { /* TODO: toast */ }
    finally { setAddingEntry(false); }
  }

  async function handleDeleteEntry(localId: string, dbId: string) {
    // Optimistic remove — cancel any pending save first.
    const t = entryTimers.current.get(localId);
    if (t) { clearTimeout(t); entryTimers.current.delete(localId); }
    setEntries((prev) => prev.filter((e) => e.localId !== localId));
    try {
      await deleteEntry({ params: { path: { workout_id: workoutId, entry_id: dbId } } });
    } catch {
      // Re-add on failure? For now just log.
      console.error("Failed to delete exercise entry");
    }
  }

  // ── delete workout ─────────────────────────────────────────────────────────

  async function handleDeleteWorkout() {
    try {
      await deleteWorkout({ params: { path: { workout_id: workoutId } } });
      qc.invalidateQueries({ queryKey: ["get", "/workouts"] });
      onDeleted();
    } catch { /* TODO: toast */ }
  }

  // ── cleanup timers on unmount ──────────────────────────────────────────────

  useEffect(() => {
    return () => {
      if (headerTimer.current) clearTimeout(headerTimer.current);
      entryTimers.current.forEach((t) => clearTimeout(t));
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── render ─────────────────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <>
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
        {/* Date + Name */}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="w-date" className="text-xs">Date</Label>
            <Input
              id="w-date"
              type="date"
              value={date}
              onChange={(e) => handleDateChange(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="w-name" className="text-xs">Name (optional)</Label>
            <Input
              id="w-name"
              value={name}
              onChange={(e) => handleNameChange(e.target.value)}
              placeholder="Leg day"
            />
          </div>
        </div>

        {/* Exercises */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label className="text-xs">Exercises</Label>
            <button
              type="button"
              onClick={handleAddEntry}
              disabled={addingEntry}
              className="text-xs text-primary hover:underline flex items-center gap-0.5 disabled:opacity-50"
            >
              {addingEntry
                ? <Loader2 className="h-3 w-3 animate-spin" />
                : <Plus className="h-3 w-3" />}
              Add exercise
            </button>
          </div>

          {entries.length === 0 && (
            <p className="text-xs text-muted-foreground py-4 text-center">
              No exercises yet — tap "Add exercise" to start.
            </p>
          )}

          {/* Hidden datalist — powers exercise name autocomplete on all EntryRows */}
          <datalist id={nameListId}>
            {(exerciseNames ?? []).map((n) => (
              <option key={n} value={n} />
            ))}
          </datalist>

          {entries.map((entry) => (
            <EntryRow
              key={entry.localId}
              entry={entry}
              onChange={(updates) => handleEntryChange(entry.localId, updates)}
              onDelete={() => handleDeleteEntry(entry.localId, entry.dbId)}
              exerciseNameListId={nameListId}
            />
          ))}
        </div>

        {/* Session notes */}
        <div className="space-y-1.5">
          <Label htmlFor="w-notes" className="text-xs">Session notes</Label>
          <Textarea
            id="w-notes"
            value={notes}
            rows={2}
            onChange={(e) => handleNotesChange(e.target.value)}
            placeholder="How it felt, PRs, anything notable…"
          />
        </div>
      </div>

      {/* Footer */}
      <div className="shrink-0 px-6 py-4 border-t flex items-center gap-2">
        <SaveBadge status={headerStatus} />
        <span className="flex-1" />
        <Button
          variant="ghost"
          size="sm"
          className="text-destructive hover:text-destructive hover:bg-destructive/10"
          onClick={handleDeleteWorkout}
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

// ── WorkoutSheet ──────────────────────────────────────────────────────────────

function WorkoutSheet({
  open,
  workoutId,
  onClose,
  onDeleted,
}: {
  open: boolean;
  workoutId: string | null;
  onClose: () => void;
  onDeleted: () => void;
}) {
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-md overflow-hidden flex flex-col gap-0 p-0">
        <SheetHeader className="px-6 pt-6 pb-4 border-b shrink-0">
          <SheetTitle>Workout</SheetTitle>
          <SheetDescription className="sr-only">Edit workout session</SheetDescription>
        </SheetHeader>
        {workoutId && (
          <WorkoutEditor
            workoutId={workoutId}
            onClose={onClose}
            onDeleted={onDeleted}
          />
        )}
      </SheetContent>
    </Sheet>
  );
}

// ── WorkoutsPage ──────────────────────────────────────────────────────────────

export default function WorkoutsPage() {
  const qc = useQueryClient();
  const [sheetOpen,    setSheetOpen]    = useState(false);
  const [selectedId,   setSelectedId]   = useState<string | null>(null);
  const [creating,     setCreating]     = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing,     setClearing]     = useState(false);

  const { data, isLoading, isError } = $api.useQuery("get", "/workouts", {
    params: { query: { limit: 50 } },
  });

  const { mutateAsync: createWorkout } = $api.useMutation("post", "/workouts");

  async function handleDeleteAll() {
    setClearing(true);
    try {
      const token = (await import("@/lib/auth/token")).getAccessToken();
      await fetch("/api/workouts", {
        method: "DELETE",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      qc.invalidateQueries({ queryKey: ["get", "/workouts"] });
    } finally {
      setClearing(false);
      setConfirmClear(false);
    }
  }

  const workouts    = data?.items ?? [];
  const grouped     = workouts.reduce<Record<string, WorkoutSummary[]>>((acc, w) => {
    (acc[w.workout_date] ??= []).push(w);
    return acc;
  }, {});
  const sortedDates = Object.keys(grouped).sort((a, b) => b.localeCompare(a));

  // Create the workout in the DB immediately so nothing is lost if the app closes.
  async function handleStartWorkout() {
    setCreating(true);
    try {
      const workout = await createWorkout({
        body: { workout_date: toLocalDateString(new Date()), entries: [] },
      });
      qc.invalidateQueries({ queryKey: ["get", "/workouts"] });
      setSelectedId(workout.id);
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
    qc.invalidateQueries({ queryKey: ["get", "/workouts"] });
    setTimeout(() => setSelectedId(null), 300);
  }

  function handleDeleted() {
    setSheetOpen(false);
    setTimeout(() => setSelectedId(null), 300);
  }

  return (
    <div className="p-6 max-w-2xl">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <Dumbbell className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-xl font-semibold">Workouts</h1>
        </div>
        <div className="flex items-center gap-2">
          {workouts.length > 0 && (
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

      {!isLoading && !isError && workouts.length === 0 && (
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
                {grouped[date].map((w) => (
                  <button
                    key={w.id}
                    type="button"
                    onClick={() => openExisting(w.id)}
                    className={cn(
                      "w-full text-left border rounded-lg px-4 py-3 bg-card",
                      "hover:bg-muted/30 transition-colors flex items-center gap-3",
                    )}
                  >
                    <Dumbbell className="h-4 w-4 text-muted-foreground shrink-0" />
                    <div className="flex-1 min-w-0">
                      <span className="text-sm font-medium block truncate">
                        {w.name ?? "Workout"}
                      </span>
                      {w.exercise_names && w.exercise_names.length > 0 && (
                        <span className="text-xs text-muted-foreground truncate block">
                          {w.exercise_names.join(" · ")}
                        </span>
                      )}
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
        workoutId={selectedId}
        onClose={handleClose}
        onDeleted={handleDeleted}
      />
    </div>
  );
}
