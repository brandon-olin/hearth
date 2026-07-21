"use client";

import { useEffect, useState } from "react";
import { $api } from "@/lib/api/query";
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
import { Textarea } from "@/components/ui/textarea";
import {
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  useSortable,
  arrayMove,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Loader2 } from "lucide-react";
import type { DisplayItem, TemplateExercise } from "@/lib/workouts/template-order";
import { reorderWithinGroup, type SlotPatch } from "@/lib/workouts/template-order";

/**
 * The "detail page" for a template row, rendered as a Sheet (the app's detail
 * pattern). A standalone slot shows its default-set settings; a superset shows
 * its members with drag handles to reorder them (order lives here, never in the
 * collapsed main-list row) plus each member's settings.
 */
export function TemplateExerciseSheet({
  open,
  onClose,
  templateId,
  item,
  applyPatches,
  onChanged,
}: {
  open: boolean;
  onClose: () => void;
  templateId: string;
  item: DisplayItem | null;
  applyPatches: (patches: SlotPatch[]) => Promise<void>;
  onChanged: () => void;
}) {
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-md overflow-hidden flex flex-col gap-0 p-0">
        <SheetHeader className="px-6 py-4 border-b shrink-0">
          <SheetTitle>{item?.kind === "group" ? "Superset" : "Exercise settings"}</SheetTitle>
          <SheetDescription className="sr-only">Edit target sets and reorder superset members</SheetDescription>
        </SheetHeader>
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          {item?.kind === "single" && (
            <ExerciseSettingsForm templateId={templateId} te={item.te} onSaved={onChanged} />
          )}
          {item?.kind === "group" && (
            <SupersetMembers
              templateId={templateId}
              item={item}
              applyPatches={applyPatches}
              onChanged={onChanged}
            />
          )}
        </div>
        <div className="shrink-0 px-6 py-4 border-t flex justify-end">
          <Button variant="outline" size="sm" onClick={onClose}>Done</Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

// ── Superset member reorder ─────────────────────────────────────────────────────

function SupersetMembers({
  templateId,
  item,
  applyPatches,
  onChanged,
}: {
  templateId: string;
  item: Extract<DisplayItem, { kind: "group" }>;
  applyPatches: (patches: SlotPatch[]) => Promise<void>;
  onChanged: () => void;
}) {
  const [members, setMembers] = useState<TemplateExercise[]>(item.members);
  useEffect(() => {
    // Resync the optimistic member order when the group's slots change upstream.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMembers(item.members);
  }, [item.members]);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  async function handleDragEnd(e: DragEndEvent) {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    const from = members.findIndex((m) => m.id === active.id);
    const to = members.findIndex((m) => m.id === over.id);
    if (from < 0 || to < 0) return;
    const next = arrayMove(members, from, to);
    setMembers(next); // optimistic
    const patches = reorderWithinGroup(item.members, item.groupId, next.map((m) => m.id));
    await applyPatches(patches);
    onChanged();
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Drag to reorder — this is the order the exercises run within the superset.
      </p>
      <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
        <SortableContext items={members.map((m) => m.id)} strategy={verticalListSortingStrategy}>
          <div className="space-y-2">
            {members.map((m) => (
              <SortableMemberRow key={m.id} templateId={templateId} te={m} onSaved={onChanged} />
            ))}
          </div>
        </SortableContext>
      </DndContext>
    </div>
  );
}

function SortableMemberRow({
  templateId,
  te,
  onSaved,
}: {
  templateId: string;
  te: TemplateExercise;
  onSaved: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: te.id });
  const [expanded, setExpanded] = useState(false);
  const style = { transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.5 : 1 };

  return (
    <div ref={setNodeRef} style={style} className="border rounded-lg bg-card">
      <div className="flex items-center gap-2 px-2 py-2">
        <button
          type="button"
          className="text-muted-foreground hover:text-foreground cursor-grab active:cursor-grabbing touch-none shrink-0"
          aria-label="Drag to reorder"
          {...attributes}
          {...listeners}
        >
          <GripVertical className="h-4 w-4" />
        </button>
        <span className="text-sm flex-1 truncate">{te.exercise?.name ?? "Exercise"}</span>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="text-xs text-primary hover:underline shrink-0"
        >
          {expanded ? "Hide" : "Settings"}
        </button>
      </div>
      {expanded && (
        <div className="px-3 pb-3">
          <ExerciseSettingsForm templateId={templateId} te={te} onSaved={onSaved} compact />
        </div>
      )}
    </div>
  );
}

// ── Default-set settings form (reused for standalone + per-member) ──────────────

function ExerciseSettingsForm({
  templateId,
  te,
  onSaved,
  compact = false,
}: {
  templateId: string;
  te: TemplateExercise;
  onSaved: () => void;
  compact?: boolean;
}) {
  const [sets, setSets]   = useState(te.default_sets != null ? String(te.default_sets) : "");
  const [reps, setReps]   = useState(te.default_reps != null ? String(te.default_reps) : "");
  const [weight, setWeight] = useState(te.default_weight != null ? String(te.default_weight) : "");
  const [rest, setRest]   = useState(te.default_rest_seconds != null ? String(te.default_rest_seconds) : "");
  const [notes, setNotes] = useState(te.notes ?? "");
  const patch = $api.useMutation("patch", "/workouts/templates/{template_id}/exercises/{te_id}");

  const num = (v: string) => (v.trim() === "" ? null : Number(v));

  async function handleSave() {
    try {
      await patch.mutateAsync({
        params: { path: { template_id: templateId, te_id: te.id } },
        body: {
          default_sets: num(sets),
          default_reps: num(reps),
          default_weight: num(weight),
          default_rest_seconds: num(rest),
          notes: notes.trim() || null,
        },
      });
      onSaved();
    } catch { /* ignore — parent surfaces errors */ }
  }

  return (
    <div className="space-y-3">
      {!compact && (
        <p className="text-sm font-medium">{te.exercise?.name ?? "Exercise"}</p>
      )}
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <Label className="text-xs">Sets</Label>
          <Input type="number" min="1" value={sets} onChange={(e) => setSets(e.target.value)} className="h-8" placeholder="3" />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Reps</Label>
          <Input type="number" min="0" value={reps} onChange={(e) => setReps(e.target.value)} className="h-8" placeholder="8" />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Weight (lbs)</Label>
          <Input type="number" min="0" step="2.5" value={weight} onChange={(e) => setWeight(e.target.value)} className="h-8" placeholder="—" />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Rest (sec)</Label>
          <Input type="number" min="0" value={rest} onChange={(e) => setRest(e.target.value)} className="h-8" placeholder="90" />
        </div>
      </div>
      <div className="space-y-1">
        <Label className="text-xs">Notes</Label>
        <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} placeholder="Cues, tempo, etc." />
      </div>
      <div className="flex justify-end">
        <Button size="sm" onClick={handleSave} disabled={patch.isPending} className="h-8 text-xs">
          {patch.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Save"}
        </Button>
      </div>
    </div>
  );
}
