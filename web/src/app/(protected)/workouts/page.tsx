"use client";

import { useState } from "react";
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
import {
  Plus,
  Loader2,
  Dumbbell,
  Trash2,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import type { components } from "@/lib/api/schema";

type WorkoutSummary = components["schemas"]["WorkoutResponse"];
type WorkoutDetail = components["schemas"]["WorkoutWithEntriesResponse"];
type ExerciseEntry = components["schemas"]["ExerciseEntryResponse"];
type ExerciseType = "strength" | "cardio" | "hiit" | "flexibility" | "other";

const TYPE_LABELS: Record<ExerciseType, string> = {
  strength: "Strength",
  cardio: "Cardio",
  hiit: "HIIT",
  flexibility: "Flexibility",
  other: "Other",
};

// ── helpers ───────────────────────────────────────────────────────────────────

function toLocalDateString(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function formatDate(dateStr: string): string {
  const [y, m, d] = dateStr.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  const today = toLocalDateString(new Date());
  const yesterday = toLocalDateString(new Date(Date.now() - 86400000));
  if (dateStr === today) return "Today";
  if (dateStr === yesterday) return "Yesterday";
  return date.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
}

function metricsLabel(entry: ExerciseEntry): string {
  const m = entry.metrics as Record<string, unknown> | null;
  if (!m) return "";
  const parts: string[] = [];
  if (m.sets && m.reps) parts.push(`${m.sets}×${m.reps}`);
  else if (m.reps) parts.push(`${m.reps} reps`);
  if (m.weight_kg) parts.push(`${m.weight_kg}kg`);
  if (m.weight_lbs) parts.push(`${m.weight_lbs}lb`);
  if (m.duration_minutes) parts.push(`${m.duration_minutes}min`);
  if (m.distance_km) parts.push(`${m.distance_km}km`);
  if (m.distance_miles) parts.push(`${m.distance_miles}mi`);
  return parts.join(" · ");
}

// ── entry form ────────────────────────────────────────────────────────────────

type EntryDraft = {
  name: string;
  type: ExerciseType;
  sets: string;
  reps: string;
  weight_kg: string;
  duration_minutes: string;
  distance_km: string;
  notes: string;
};

function blankEntry(): EntryDraft {
  return { name: "", type: "strength", sets: "", reps: "", weight_kg: "", duration_minutes: "", distance_km: "", notes: "" };
}

function EntryForm({
  draft,
  onChange,
  onRemove,
}: {
  draft: EntryDraft;
  onChange: (d: EntryDraft) => void;
  onRemove: () => void;
}) {
  function set<K extends keyof EntryDraft>(k: K, v: EntryDraft[K]) {
    onChange({ ...draft, [k]: v });
  }

  const isStrength = draft.type === "strength";
  const isCardio = draft.type === "cardio" || draft.type === "hiit";

  return (
    <div className="border rounded-lg p-3 space-y-2 bg-muted/20">
      <div className="flex gap-2">
        <Input
          value={draft.name}
          onChange={(e) => set("name", e.target.value)}
          placeholder="Exercise name"
          className="h-8 text-sm flex-1"
        />
        <select
          value={draft.type}
          onChange={(e) => set("type", e.target.value as ExerciseType)}
          className="h-8 rounded-md border border-input bg-transparent px-2 text-sm"
        >
          {Object.entries(TYPE_LABELS).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
        <button type="button" onClick={onRemove} className="text-muted-foreground hover:text-destructive">
          <Trash2 className="h-4 w-4" />
        </button>
      </div>

      <div className="flex gap-2 flex-wrap">
        {isStrength && (
          <>
            <Input type="number" min="1" placeholder="Sets" value={draft.sets}
              onChange={(e) => set("sets", e.target.value)}
              className="h-7 text-xs w-20" />
            <Input type="number" min="1" placeholder="Reps" value={draft.reps}
              onChange={(e) => set("reps", e.target.value)}
              className="h-7 text-xs w-20" />
            <Input type="number" min="0" step="0.5" placeholder="kg" value={draft.weight_kg}
              onChange={(e) => set("weight_kg", e.target.value)}
              className="h-7 text-xs w-20" />
          </>
        )}
        {isCardio && (
          <>
            <Input type="number" min="1" placeholder="Minutes" value={draft.duration_minutes}
              onChange={(e) => set("duration_minutes", e.target.value)}
              className="h-7 text-xs w-24" />
            <Input type="number" min="0" step="0.1" placeholder="km" value={draft.distance_km}
              onChange={(e) => set("distance_km", e.target.value)}
              className="h-7 text-xs w-20" />
          </>
        )}
        {!isStrength && !isCardio && (
          <Input type="number" min="1" placeholder="Minutes" value={draft.duration_minutes}
            onChange={(e) => set("duration_minutes", e.target.value)}
            className="h-7 text-xs w-24" />
        )}
      </div>

      <Input value={draft.notes} onChange={(e) => set("notes", e.target.value)}
        placeholder="Notes (optional)" className="h-7 text-xs" />
    </div>
  );
}

function draftToMetrics(d: EntryDraft): Record<string, unknown> {
  const m: Record<string, unknown> = {};
  if (d.sets) m.sets = Number(d.sets);
  if (d.reps) m.reps = Number(d.reps);
  if (d.weight_kg) m.weight_kg = Number(d.weight_kg);
  if (d.duration_minutes) m.duration_minutes = Number(d.duration_minutes);
  if (d.distance_km) m.distance_km = Number(d.distance_km);
  return m;
}

// ── workout detail sheet ──────────────────────────────────────────────────────

function WorkoutSheet({
  open,
  workoutId,
  onClose,
}: {
  open: boolean;
  workoutId: string | null;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const isNew = workoutId === null;
  const [date, setDate] = useState(toLocalDateString(new Date()));
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [entries, setEntries] = useState<EntryDraft[]>([blankEntry()]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [lastOpen, setLastOpen] = useState(false);
  if (open !== lastOpen) {
    setLastOpen(open);
    if (open && isNew) {
      setDate(toLocalDateString(new Date()));
      setName(""); setNotes("");
      setEntries([blankEntry()]);
      setError(null);
    }
  }

  const { data: detail, isLoading: loadingDetail } = $api.useQuery(
    "get",
    "/workouts/{workout_id}",
    { params: { path: { workout_id: workoutId ?? "" } } },
    { enabled: open && !isNew }
  );

  const { mutateAsync: createWorkout } = $api.useMutation("post", "/workouts");
  const { mutateAsync: deleteWorkout } = $api.useMutation("delete", "/workouts/{workout_id}");

  async function handleSave() {
    setSaving(true); setError(null);
    try {
      const validEntries = entries.filter((e) => e.name.trim());
      await createWorkout({
        body: {
          workout_date: date,
          name: name.trim() || null,
          notes: notes.trim() || null,
          entries: validEntries.map((e, i) => ({
            name: e.name.trim(),
            type: e.type,
            sort_order: i,
            metrics: draftToMetrics(e),
            notes: e.notes.trim() || null,
          })),
        },
      });
      qc.invalidateQueries({ queryKey: ["get", "/workouts"] });
      onClose();
    } catch { setError("Something went wrong."); }
    finally { setSaving(false); }
  }

  async function handleDelete() {
    if (!workoutId) return;
    setSaving(true);
    try {
      await deleteWorkout({ params: { path: { workout_id: workoutId } } });
      qc.invalidateQueries({ queryKey: ["get", "/workouts"] });
      onClose();
    } finally { setSaving(false); }
  }

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-md overflow-y-auto flex flex-col gap-0 p-0">
        <SheetHeader className="px-6 pt-6 pb-4 border-b">
          <SheetTitle>{isNew ? "Log workout" : "Workout"}</SheetTitle>
          <SheetDescription className="sr-only">
            {isNew ? "Log a new workout" : "Workout details"}
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {isNew ? (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="w-date">Date</Label>
                  <Input id="w-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="w-name">Name (optional)</Label>
                  <Input id="w-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Leg day" />
                </div>
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label>Exercises</Label>
                  <button type="button"
                    onClick={() => setEntries((prev) => [...prev, blankEntry()])}
                    className="text-xs text-primary hover:underline flex items-center gap-0.5"
                  >
                    <Plus className="h-3 w-3" />Add
                  </button>
                </div>
                {entries.map((e, i) => (
                  <EntryForm
                    key={i}
                    draft={e}
                    onChange={(d) => setEntries((prev) => prev.map((x, j) => j === i ? d : x))}
                    onRemove={() => setEntries((prev) => prev.filter((_, j) => j !== i))}
                  />
                ))}
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="w-notes">Notes</Label>
                <Textarea id="w-notes" value={notes} rows={2}
                  onChange={(e) => setNotes(e.target.value)} placeholder="How it felt…" />
              </div>
            </>
          ) : loadingDetail ? (
            <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />Loading…
            </div>
          ) : detail ? (
            <>
              <div>
                <p className="text-sm font-medium">{detail.name ?? formatDate(detail.workout_date)}</p>
                <p className="text-xs text-muted-foreground">{formatDate(detail.workout_date)}</p>
              </div>
              {detail.notes && <p className="text-sm text-muted-foreground">{detail.notes}</p>}
              {detail.entries.length === 0 && (
                <p className="text-sm text-muted-foreground">No exercises logged.</p>
              )}
              <div className="space-y-2">
                {detail.entries.map((entry) => (
                  <div key={entry.id} className="border rounded-lg px-3 py-2.5">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium">{entry.name}</span>
                      <span className="text-[10px] text-muted-foreground uppercase tracking-wide">
                        {TYPE_LABELS[entry.type as ExerciseType] ?? entry.type}
                      </span>
                    </div>
                    {metricsLabel(entry) && (
                      <p className="text-xs text-muted-foreground mt-0.5">{metricsLabel(entry)}</p>
                    )}
                    {entry.notes && <p className="text-xs text-muted-foreground italic mt-0.5">{entry.notes}</p>}
                  </div>
                ))}
              </div>
            </>
          ) : null}
        </div>

        <div className="px-6 py-4 border-t flex items-center gap-2">
          {error ? <p className="flex-1 text-sm text-destructive">{error}</p> : <span className="flex-1" />}
          {!isNew && (
            <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive"
              onClick={handleDelete} disabled={saving}>Delete</Button>
          )}
          <Button variant="outline" size="sm" onClick={onClose} disabled={saving}>
            {isNew ? "Cancel" : "Close"}
          </Button>
          {isNew && (
            <Button size="sm" onClick={handleSave} disabled={saving}>
              {saving && <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />}
              Log workout
            </Button>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

// ── page ──────────────────────────────────────────────────────────────────────

export default function WorkoutsPage() {
  const [sheetOpen, setSheetOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data, isLoading, isError } = $api.useQuery("get", "/workouts", {
    params: { query: { limit: 50 } },
  });

  const workouts = data?.items ?? [];

  // Group by date descending
  const grouped = workouts.reduce<Record<string, WorkoutSummary[]>>((acc, w) => {
    (acc[w.workout_date] ??= []).push(w);
    return acc;
  }, {});
  const sortedDates = Object.keys(grouped).sort((a, b) => b.localeCompare(a));

  function openNew() { setSelectedId(null); setSheetOpen(true); }
  function openDetail(id: string) { setSelectedId(id); setSheetOpen(true); }
  function handleClose() { setSheetOpen(false); setTimeout(() => setSelectedId(null), 300); }

  return (
    <div className="p-6 max-w-2xl">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <Dumbbell className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-xl font-semibold">Workouts</h1>
        </div>
        <Button size="sm" onClick={openNew}>
          <Plus className="h-4 w-4 mr-1" />Log
        </Button>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Loading…
        </div>
      )}
      {isError && <p className="py-8 text-sm text-destructive">Failed to load workouts.</p>}

      {!isLoading && !isError && workouts.length === 0 && (
        <div className="py-12 text-center">
          <Dumbbell className="h-8 w-8 text-muted-foreground/30 mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">No workouts logged yet.</p>
          <Button variant="outline" size="sm" className="mt-4" onClick={openNew}>
            <Plus className="h-4 w-4 mr-1" />Log your first workout
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
                    onClick={() => openDetail(w.id)}
                    className="w-full text-left border rounded-lg px-4 py-3 bg-card hover:bg-muted/30 transition-colors flex items-center gap-3"
                  >
                    <Dumbbell className="h-4 w-4 text-muted-foreground shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium">
                        {w.name ?? "Workout"}
                      </p>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      <WorkoutSheet open={sheetOpen} workoutId={selectedId} onClose={handleClose} />
    </div>
  );
}
