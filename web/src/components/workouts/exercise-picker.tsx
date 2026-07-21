"use client";

import { useState } from "react";
import { $api } from "@/lib/api/query";
import { useDebounce } from "@/lib/hooks/use-debounce";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Plus, Loader2, Dumbbell, Search } from "lucide-react";
import type { components } from "@/lib/api/schema";

type Exercise = components["schemas"]["ExerciseResponse"];
type TrackingType = "reps" | "duration" | "distance";

const TRACKING_LABELS: Record<TrackingType, string> = {
  reps: "Strength (reps)",
  distance: "Cardio (distance)",
  duration: "Timed (duration)",
};

/**
 * Adds an exercise to a template. Lists the shared catalog ordered by the
 * current user's recency (sort=recent), split into "My exercises" and "Exercise
 * library", with a name search and an inline create form.
 */
export function ExercisePicker({
  open,
  onClose,
  onPick,
  busyId,
}: {
  open: boolean;
  onClose: () => void;
  onPick: (exerciseId: string) => void | Promise<void>;
  busyId?: string | null;
}) {
  const [search, setSearch] = useState("");
  const debounced = useDebounce(search, 300);
  const [creating, setCreating] = useState(false);

  const { data, isLoading } = $api.useQuery(
    "get",
    "/workouts/exercises",
    { params: { query: { sort: "recent", search: debounced || undefined, limit: 500 } } },
    { staleTime: 60_000 },
  );

  const items = data?.items ?? [];
  const mine = items.filter((e) => !e.is_global);
  const library = items.filter((e) => e.is_global);

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-md overflow-hidden flex flex-col gap-0 p-0">
        <SheetHeader className="px-6 py-4 border-b shrink-0">
          <SheetTitle>Add exercise</SheetTitle>
          <SheetDescription className="sr-only">Pick an exercise from the catalog or create a new one</SheetDescription>
        </SheetHeader>

        <div className="px-6 py-3 border-b shrink-0 space-y-3">
          <div className="relative">
            <Search className="h-4 w-4 text-muted-foreground absolute left-2.5 top-1/2 -translate-y-1/2" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search exercises…"
              className="pl-8"
            />
          </div>
          {!creating && (
            <button
              type="button"
              onClick={() => setCreating(true)}
              className="text-xs text-primary hover:underline flex items-center gap-0.5"
            >
              <Plus className="h-3 w-3" /> New exercise
            </button>
          )}
          {creating && (
            <InlineCreate
              onCancel={() => setCreating(false)}
              onCreated={async (id) => { setCreating(false); await onPick(id); }}
            />
          )}
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
          {isLoading && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading…
            </div>
          )}
          {!isLoading && items.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-4">No exercises match.</p>
          )}
          {mine.length > 0 && (
            <ExerciseSection title="My exercises" exercises={mine} onPick={onPick} busyId={busyId} />
          )}
          {library.length > 0 && (
            <ExerciseSection title="Exercise library" exercises={library} onPick={onPick} busyId={busyId} />
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function ExerciseSection({
  title,
  exercises,
  onPick,
  busyId,
}: {
  title: string;
  exercises: Exercise[];
  onPick: (id: string) => void | Promise<void>;
  busyId?: string | null;
}) {
  return (
    <div className="space-y-1.5">
      <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">{title}</p>
      {exercises.map((e) => (
        <button
          key={e.id}
          type="button"
          onClick={() => onPick(e.id)}
          disabled={busyId === e.id}
          className="w-full text-left border rounded-lg px-3 py-2 bg-card hover:bg-muted/30 transition-colors flex items-center gap-2.5 disabled:opacity-50"
        >
          <Dumbbell className="h-4 w-4 text-muted-foreground shrink-0" />
          <span className="text-sm flex-1 truncate">{e.name}</span>
          {busyId === e.id
            ? <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" />
            : <Plus className="h-3.5 w-3.5 text-muted-foreground shrink-0" />}
        </button>
      ))}
    </div>
  );
}

function InlineCreate({
  onCancel,
  onCreated,
}: {
  onCancel: () => void;
  onCreated: (id: string) => void | Promise<void>;
}) {
  const [name, setName] = useState("");
  const [muscle, setMuscle] = useState("");
  const [tracking, setTracking] = useState<TrackingType>("reps");
  const createExercise = $api.useMutation("post", "/workouts/exercises");

  async function handleCreate() {
    if (!name.trim()) return;
    try {
      const ex = await createExercise.mutateAsync({
        body: {
          name: name.trim(),
          tracking_type: tracking,
          muscle_groups: muscle.trim() ? [muscle.trim().toLowerCase()] : [],
        },
      });
      await onCreated(ex.id);
    } catch { /* surfaced by the caller's error handling */ }
  }

  return (
    <div className="border rounded-lg p-3 space-y-2 bg-muted/20">
      <div className="space-y-1">
        <Label className="text-xs">Name</Label>
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Zercher Squat" className="h-8" />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <Label className="text-xs">Muscle group</Label>
          <Input value={muscle} onChange={(e) => setMuscle(e.target.value)} placeholder="e.g. legs" className="h-8" />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Type</Label>
          <Select value={tracking} onChange={(e) => setTracking(e.target.value as TrackingType)} className="h-8">
            {Object.entries(TRACKING_LABELS).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </Select>
        </div>
      </div>
      <div className="flex gap-2 justify-end pt-0.5">
        <Button size="sm" variant="ghost" onClick={onCancel} className="h-7 text-xs">Cancel</Button>
        <Button
          size="sm"
          onClick={handleCreate}
          disabled={!name.trim() || createExercise.isPending}
          className="h-7 text-xs"
        >
          {createExercise.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : "Create & add"}
        </Button>
      </div>
    </div>
  );
}
