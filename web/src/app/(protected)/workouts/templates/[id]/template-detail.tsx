"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { $api } from "@/lib/api/query";
import { useQueryClient } from "@tanstack/react-query";
import { useSegmentId } from "@/lib/hooks/use-segment-id";
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
import {
  ClipboardList, ChevronLeft, ChevronRight, Loader2, Plus, Trash2, Check, Link2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { RowMenu, type DragHandle } from "@/components/workouts/row-menu";
import { ExercisePicker } from "@/components/workouts/exercise-picker";
import { TemplateExerciseSheet } from "@/components/workouts/template-exercise-sheet";
import { useToasts, ToastViewport } from "@/components/workouts/toasts";
import {
  buildDisplayItems,
  displayItemId,
  linkSelection,
  unlinkGroup,
  reorderItems,
  supersetLabel as groupLabel,
  targetSummary,
  type DisplayItem,
  type SlotPatch,
  type TemplateExercise,
} from "@/lib/workouts/template-order";

const MAX_SUPERSET = 5;

export default function TemplateDetail() {
  const id = useSegmentId(2); // /workouts/templates/<id> → segment index 2
  const router = useRouter();
  const qc = useQueryClient();
  const { toasts, show } = useToasts();

  const { data: template, isLoading, isError, refetch } = $api.useQuery(
    "get",
    "/workouts/templates/{template_id}",
    { params: { path: { template_id: id } } },
    { enabled: !!id, staleTime: 10_000 },
  );

  const tes = useMemo<TemplateExercise[]>(
    () => (template?.exercises ?? []) as TemplateExercise[],
    [template],
  );

  // Optimistic display order for smooth drags; reconciled from the query. The
  // signature must include EVERY field the rows render (position/group drive
  // order + collapsing; notes + default_sets/reps drive the row's note line and
  // target summary) so an inline edit refreshes the list without a reload.
  const [items, setItems] = useState<DisplayItem[]>([]);
  const signature = tes
    .map((t) => `${t.id}:${t.position}:${t.superset_group_id ?? ""}:${t.notes ?? ""}:${t.default_sets ?? ""}:${t.default_reps ?? ""}`)
    .join("|");
  useEffect(() => {
    // Reconcile the optimistic display order with the server's slots whenever
    // the underlying rows change (add/remove/link/unlink/reorder settle here).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setItems(buildDisplayItems(tes));
  }, [signature]); // eslint-disable-line react-hooks/exhaustive-deps

  // Header (name) + mutations.
  const [name, setName] = useState("");
  const [nameDirty, setNameDirty] = useState(false);
  useEffect(() => {
    if (template && !nameDirty) setName(template.name); // eslint-disable-line
  }, [template?.name]); // eslint-disable-line react-hooks/exhaustive-deps

  const patchTemplate = $api.useMutation("patch", "/workouts/templates/{template_id}");
  const deleteTemplate = $api.useMutation("delete", "/workouts/templates/{template_id}");
  const addExercise = $api.useMutation("post", "/workouts/templates/{template_id}/exercises");
  const patchTe = $api.useMutation("patch", "/workouts/templates/{template_id}/exercises/{te_id}");
  const deleteTe = $api.useMutation("delete", "/workouts/templates/{template_id}/exercises/{te_id}");

  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerBusy, setPickerBusy] = useState<string | null>(null);
  const [sheetItem, setSheetItem] = useState<DisplayItem | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Link mode.
  const [linkMode, setLinkMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const sensors = useSensors(
    // delay activation: a quick tap on the 3-dot falls through to the menu;
    // press-and-hold starts a drag.
    useSensor(PointerSensor, { activationConstraint: { delay: 180, tolerance: 8 } }),
  );

  function invalidate() {
    refetch();
    qc.invalidateQueries({ queryKey: ["get", "/workouts/templates"] });
  }

  /** Apply position/group PATCHes sequentially; surface superset errors as a toast. */
  async function applyPatches(patches: SlotPatch[]) {
    for (const p of patches) {
      try {
        await patchTe.mutateAsync({
          params: { path: { template_id: id, te_id: p.id } },
          body: {
            ...(p.position !== undefined ? { position: p.position } : {}),
            ...("superset_group_id" in p ? { superset_group_id: p.superset_group_id } : {}),
          },
        });
      } catch (e) {
        show(errorMessage(e, "Couldn't update the superset."), "error");
        break;
      }
    }
  }

  // ── Header ──────────────────────────────────────────────────────────────────
  async function saveName() {
    if (!name.trim() || name === template?.name) { setNameDirty(false); return; }
    try {
      await patchTemplate.mutateAsync({ params: { path: { template_id: id } }, body: { name: name.trim() } });
      setNameDirty(false);
      invalidate();
    } catch { show("Couldn't rename the template.", "error"); }
  }

  async function handleDeleteTemplate() {
    try {
      await deleteTemplate.mutateAsync({ params: { path: { template_id: id } } });
      qc.invalidateQueries({ queryKey: ["get", "/workouts/templates"] });
      router.push("/workouts/templates");
    } catch { show("Couldn't delete the template.", "error"); }
  }

  // ── Add exercise ────────────────────────────────────────────────────────────
  async function handlePick(exerciseId: string) {
    setPickerBusy(exerciseId);
    try {
      await addExercise.mutateAsync({
        params: { path: { template_id: id } },
        body: { exercise_id: exerciseId },
      });
      invalidate();
    } catch { show("Couldn't add the exercise.", "error"); }
    finally { setPickerBusy(null); }
  }

  // ── Drag reorder (top-level items) ──────────────────────────────────────────
  async function handleDragEnd(e: DragEndEvent) {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    const from = items.findIndex((it) => displayItemId(it) === active.id);
    const to = items.findIndex((it) => displayItemId(it) === over.id);
    if (from < 0 || to < 0) return;
    const next = arrayMove(items, from, to);
    setItems(next); // optimistic
    await applyPatches(reorderItems(tes, next));
    invalidate();
  }

  // ── Superset link / unlink ──────────────────────────────────────────────────
  function memberIdsOf(item: DisplayItem): string[] {
    return item.kind === "single" ? [item.te.id] : item.members.map((m) => m.id);
  }

  function enterLinkMode(seed: DisplayItem) {
    setSelected(new Set(memberIdsOf(seed)));
    setLinkMode(true);
  }

  function toggleSelect(item: DisplayItem) {
    const ids = memberIdsOf(item);
    const allIn = ids.every((x) => selected.has(x));
    if (allIn) {
      const next = new Set(selected);
      ids.forEach((x) => next.delete(x));
      setSelected(next);
      return;
    }
    const additions = ids.filter((x) => !selected.has(x));
    // Keep the toast OUT of the state updater — updaters must be pure (React
    // StrictMode double-invokes them in dev, which would fire the toast twice).
    if (selected.size + additions.length > MAX_SUPERSET) {
      show(`A superset can hold at most ${MAX_SUPERSET} exercises.`, "error");
      return;
    }
    const next = new Set(selected);
    ids.forEach((x) => next.add(x));
    setSelected(next);
  }

  async function handleLink() {
    if (selected.size < 2) return;
    const newGroup = crypto.randomUUID();
    await applyPatches(linkSelection(tes, selected, newGroup));
    setLinkMode(false);
    setSelected(new Set());
    invalidate();
  }

  function cancelLink() {
    setLinkMode(false);
    setSelected(new Set());
  }

  async function handleUnlink(groupId: string) {
    await applyPatches(unlinkGroup(tes, groupId));
    invalidate();
  }

  async function handleRemove(item: DisplayItem) {
    const ids = memberIdsOf(item);
    try {
      for (const teId of ids) {
        await deleteTe.mutateAsync({ params: { path: { template_id: id, te_id: teId } } });
      }
      invalidate();
    } catch { show("Couldn't remove the exercise.", "error"); }
  }

  // ── Render ──────────────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="page-content flex items-center gap-2 py-12 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading…
      </div>
    );
  }
  if (isError || !template) {
    return (
      <div className="page-content py-12">
        <p className="text-sm text-destructive">Template not found.</p>
        <Link href="/workouts/templates" className={cn(buttonVariants({ variant: "outline", size: "sm" }), "mt-4")}>
          <ChevronLeft className="h-4 w-4 mr-1" /> Back to templates
        </Link>
      </div>
    );
  }

  return (
    <div className="page-content pb-24">
      <div className="flex items-center gap-2 mb-4">
        <Link
          href="/workouts/templates"
          className={cn(buttonVariants({ size: "sm", variant: "ghost" }), "text-muted-foreground -ml-2")}
        >
          <ChevronLeft className="h-4 w-4 mr-1" /> Templates
        </Link>
      </div>

      <div className="flex items-center gap-2 mb-6">
        <ClipboardList className="h-5 w-5 text-muted-foreground shrink-0" />
        <Input
          value={name}
          onChange={(e) => { setName(e.target.value); setNameDirty(true); }}
          onBlur={saveName}
          onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
          className="text-xl font-semibold h-10 border-transparent hover:border-input focus-visible:border-input px-2 -ml-1"
        />
      </div>

      {/* Exercise list */}
      <div className="space-y-2">
        {items.length === 0 && (
          <p className="text-sm text-muted-foreground py-4 text-center">
            No exercises yet — add one below.
          </p>
        )}

        <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
          <SortableContext items={items.map(displayItemId)} strategy={verticalListSortingStrategy}>
            <div className="space-y-2">
              {items.map((item) => (
                <TemplateRow
                  key={displayItemId(item)}
                  item={item}
                  linkMode={linkMode}
                  selected={selected}
                  onOpenDetail={() => setSheetItem(item)}
                  onToggleSelect={() => toggleSelect(item)}
                  actions={rowActions(item, {
                    onEdit: () => setSheetItem(item),
                    onLink: () => enterLinkMode(item),
                    onUnlink: (gid) => handleUnlink(gid),
                    onRemove: () => handleRemove(item),
                  })}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>

        {!linkMode && (
          <Button variant="outline" size="sm" className="mt-1" onClick={() => setPickerOpen(true)}>
            <Plus className="h-4 w-4 mr-1" /> Add exercise
          </Button>
        )}
      </div>

      {/* Delete template */}
      {!linkMode && (
        <div className="mt-10 border-t pt-4">
          {confirmDelete ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Delete this template?</span>
              <Button size="sm" variant="destructive" className="h-7 text-xs" onClick={handleDeleteTemplate} disabled={deleteTemplate.isPending}>
                {deleteTemplate.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : "Yes, delete"}
              </Button>
              <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setConfirmDelete(false)}>Cancel</Button>
            </div>
          ) : (
            <Button size="sm" variant="ghost" className="h-7 text-xs text-muted-foreground hover:text-destructive" onClick={() => setConfirmDelete(true)}>
              <Trash2 className="h-3.5 w-3.5 mr-1" /> Delete template
            </Button>
          )}
        </div>
      )}

      {/* Link-mode action bar */}
      {linkMode && (
        <div className="fixed bottom-0 left-0 right-0 border-t bg-background px-6 py-3 flex items-center gap-3 z-40">
          <span className="text-sm text-muted-foreground flex-1">
            {selected.size} selected — tap exercises to superset them.
          </span>
          <Button variant="outline" size="sm" onClick={cancelLink}>Cancel</Button>
          <Button size="sm" onClick={handleLink} disabled={selected.size < 2}>
            <Link2 className="h-4 w-4 mr-1" /> Link
          </Button>
        </div>
      )}

      <ExercisePicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onPick={handlePick}
        busyId={pickerBusy}
      />
      <TemplateExerciseSheet
        open={sheetItem !== null}
        onClose={() => setSheetItem(null)}
        templateId={id}
        item={sheetItem}
        applyPatches={applyPatches}
        onChanged={invalidate}
      />
      <ToastViewport toasts={toasts} />
    </div>
  );
}

// ── Row ───────────────────────────────────────────────────────────────────────

function TemplateRow({
  item,
  linkMode,
  selected,
  onOpenDetail,
  onToggleSelect,
  actions,
}: {
  item: DisplayItem;
  linkMode: boolean;
  selected: Set<string>;
  onOpenDetail: () => void;
  onToggleSelect: () => void;
  actions: Parameters<typeof RowMenu>[0]["actions"];
}) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } =
    useSortable({ id: displayItemId(item), disabled: linkMode });
  const style = { transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.5 : 1 };

  const memberIds = item.kind === "single" ? [item.te.id] : item.members.map((m) => m.id);
  const isChecked = memberIds.every((x) => selected.has(x));

  const title =
    item.kind === "single"
      ? (item.te.exercise?.name ?? "Exercise")
      : supersetLabel(item.members);
  const summary =
    item.kind === "single"
      ? targetSummary(item.te)
      : `${item.members.length} exercises`;
  const note = item.kind === "single" ? item.te.notes : null;

  const dragHandle: DragHandle = { attributes, listeners, setActivatorNodeRef };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "border rounded-lg bg-card flex items-center gap-2 pl-2 pr-3 py-2.5",
        isChecked && linkMode && "ring-2 ring-primary border-primary",
      )}
    >
      {linkMode ? (
        <button
          type="button"
          onClick={onToggleSelect}
          aria-label={isChecked ? "Deselect" : "Select"}
          className={cn(
            "h-5 w-5 rounded border flex items-center justify-center shrink-0 transition-colors",
            isChecked ? "bg-primary border-primary text-primary-foreground" : "border-input",
          )}
        >
          {isChecked && <Check className="h-3.5 w-3.5" />}
        </button>
      ) : (
        <RowMenu actions={actions} dragHandle={dragHandle} />
      )}

      <button
        type="button"
        onClick={linkMode ? onToggleSelect : onOpenDetail}
        className="flex-1 min-w-0 text-left"
      >
        <span className="text-sm font-medium block truncate">{title}</span>
        <span className="text-xs text-muted-foreground">{summary}</span>
        {note && <span className="text-xs text-muted-foreground italic block truncate">{note}</span>}
      </button>

      {!linkMode && <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />}
    </div>
  );
}

// ── helpers ─────────────────────────────────────────────────────────────────

function supersetLabel(members: TemplateExercise[]): string {
  // The collapsed-superset label rule lives in template-order.ts so the live
  // session logger (workouts-003) renders group rows identically.
  return groupLabel(members.map((m) => m.exercise?.name ?? "Exercise"));
}

function rowActions(
  item: DisplayItem,
  h: { onEdit: () => void; onLink: () => void; onUnlink: (groupId: string) => void; onRemove: () => void },
) {
  if (item.kind === "group") {
    return [
      { label: "Open superset", onSelect: h.onEdit },
      { label: "Link as superset", onSelect: h.onLink },
      { label: "Unlink superset", onSelect: () => h.onUnlink(item.groupId) },
      { label: "Remove superset", onSelect: h.onRemove, danger: true },
    ];
  }
  return [
    { label: "Edit exercise settings", onSelect: h.onEdit },
    { label: "Link as superset", onSelect: h.onLink },
    { label: "Add note", onSelect: h.onEdit },
    { label: "Remove exercise", onSelect: h.onRemove, danger: true },
  ];
}

function errorMessage(e: unknown, fallback: string): string {
  if (e && typeof e === "object" && "detail" in e && typeof (e as { detail: unknown }).detail === "string") {
    return (e as { detail: string }).detail;
  }
  return fallback;
}
