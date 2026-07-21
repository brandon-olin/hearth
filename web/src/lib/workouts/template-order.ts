/**
 * Pure helpers for the workouts-002 template builder.
 *
 * The API stores each template slot as a row with an integer `position` and a
 * nullable `superset_group_id`. This module turns that flat list into the
 * display model (standalone rows + collapsed superset rows) and computes the
 * minimal set of PATCHes for the four structural operations — reorder, link,
 * unlink, and reorder-within-superset — by describing the *desired* flat order
 * and diffing it against the current rows.
 *
 * Invariant we maintain: superset members are always contiguous in position
 * order, and positions are renumbered 0..n-1 after any structural change. That
 * keeps "collapse consecutive same-group rows into one item" correct and avoids
 * fragile insert arithmetic. The 2–5 member cap and lone-member dissolve live in
 * the service layer (superset.py); this module never re-implements them.
 */
import type { components } from "@/lib/api/schema";

export type TemplateExercise = components["schemas"]["TemplateExerciseResponse"];

/**
 * The minimum a row needs to be foldable into display items. Session exercises
 * (workouts-003) carry the same three fields, so the live logger reuses
 * `sortByPosition` / `buildDisplayItems` rather than forking them — the
 * collapsed-superset visual rules stay defined in exactly one place.
 */
export interface OrderedRow {
  id: string;
  position: number;
  superset_group_id: string | null;
}

export type DisplayItem<T extends OrderedRow = TemplateExercise> =
  | { kind: "single"; id: string; te: T }
  | { kind: "group"; id: string; groupId: string; members: T[] };

/** A single slot's desired state after an operation. */
export interface DesiredSlot {
  id: string;
  superset_group_id: string | null;
}

/** One PATCH to apply — only the fields that actually changed are set. */
export interface SlotPatch {
  id: string;
  position?: number;
  superset_group_id?: string | null;
}

/** Sort slots by (position, then id) so ties are stable. */
export function sortByPosition<T extends OrderedRow>(tes: T[]): T[] {
  return [...tes].sort((a, b) => (a.position - b.position) || a.id.localeCompare(b.id));
}

/**
 * Fold the flat, position-sorted slots into display items: consecutive rows
 * sharing a non-null superset_group_id become one collapsed group item.
 */
export function buildDisplayItems<T extends OrderedRow>(tes: T[]): DisplayItem<T>[] {
  const flat = sortByPosition(tes);
  const items: DisplayItem<T>[] = [];
  for (const te of flat) {
    const last = items[items.length - 1];
    if (
      te.superset_group_id &&
      last &&
      last.kind === "group" &&
      last.groupId === te.superset_group_id
    ) {
      last.members.push(te);
    } else if (te.superset_group_id) {
      items.push({ kind: "group", id: `group:${te.superset_group_id}`, groupId: te.superset_group_id, members: [te] });
    } else {
      items.push({ kind: "single", id: te.id, te });
    }
  }
  return items;
}

/** The dnd id for a display item (single → slot id, group → "group:<uuid>"). */
export function displayItemId(item: { id: string }): string {
  return item.id;
}

/** "Bench + Row" for two members, "Bench + 2 others" beyond that. */
export function supersetLabel(names: string[]): string {
  if (names.length <= 2) return names.join(" + ");
  return `${names[0]} + ${names.length - 1} others`;
}

/**
 * Given the current slots and the desired flat order (with each slot's target
 * group), produce the minimal PATCH list: renumber positions 0..n-1 and change
 * any group that differs. Slots absent from `desired` are left untouched.
 */
export function diffSlots(current: TemplateExercise[], desired: DesiredSlot[]): SlotPatch[] {
  const byId = new Map(current.map((t) => [t.id, t]));
  const patches: SlotPatch[] = [];
  desired.forEach((slot, index) => {
    const cur = byId.get(slot.id);
    if (!cur) return;
    const patch: SlotPatch = { id: slot.id };
    if (cur.position !== index) patch.position = index;
    if ((cur.superset_group_id ?? null) !== (slot.superset_group_id ?? null)) {
      patch.superset_group_id = slot.superset_group_id;
    }
    if (patch.position !== undefined || "superset_group_id" in patch) patches.push(patch);
  });
  return patches;
}

/** Flatten display items back to a desired-slot list preserving group membership. */
function flattenItems(items: DisplayItem[]): DesiredSlot[] {
  const out: DesiredSlot[] = [];
  for (const item of items) {
    if (item.kind === "single") {
      out.push({ id: item.te.id, superset_group_id: null });
    } else {
      for (const m of item.members) out.push({ id: m.id, superset_group_id: item.groupId });
    }
  }
  return out;
}

/** Reorder top-level display items (drag in the main list) → PATCH list. */
export function reorderItems(
  current: TemplateExercise[],
  items: DisplayItem[],
): SlotPatch[] {
  return diffSlots(current, flattenItems(items));
}

/**
 * Merge `selectedIds` into one new superset group. The block is placed at the
 * position of the highest-ranked (lowest-position) selected slot; the selected
 * slots keep their current relative order inside the block. Consumed slots that
 * belonged to other supersets migrate wholesale into the new group.
 */
export function linkSelection(
  current: TemplateExercise[],
  selectedIds: Set<string>,
  newGroupId: string,
): SlotPatch[] {
  const flat = sortByPosition(current);
  const selected = flat.filter((t) => selectedIds.has(t.id));
  const desired: DesiredSlot[] = [];
  let emitted = false;
  for (const te of flat) {
    if (selectedIds.has(te.id)) {
      if (!emitted) {
        for (const s of selected) desired.push({ id: s.id, superset_group_id: newGroupId });
        emitted = true;
      }
      // other selected slots are represented by the block already
    } else {
      desired.push({ id: te.id, superset_group_id: te.superset_group_id ?? null });
    }
  }
  return diffSlots(current, desired);
}

/** Dissolve a group: every member becomes standalone, positions unchanged. */
export function unlinkGroup(current: TemplateExercise[], groupId: string): SlotPatch[] {
  const flat = sortByPosition(current);
  const desired: DesiredSlot[] = flat.map((te) => ({
    id: te.id,
    superset_group_id: te.superset_group_id === groupId ? null : (te.superset_group_id ?? null),
  }));
  return diffSlots(current, desired);
}

/**
 * Reorder the members inside one superset (the detail sheet). `memberOrder` is
 * the group's slot ids in their new internal order; the group occupies its
 * existing contiguous position range, so only those slots move.
 */
export function reorderWithinGroup(
  current: TemplateExercise[],
  groupId: string,
  memberOrder: string[],
): SlotPatch[] {
  const flat = sortByPosition(current);
  const orderIndex = new Map(memberOrder.map((id, i) => [id, i]));
  const desired: DesiredSlot[] = [];
  let block: TemplateExercise[] = [];
  const flush = () => {
    block
      .slice()
      .sort((a, b) => (orderIndex.get(a.id) ?? 0) - (orderIndex.get(b.id) ?? 0))
      .forEach((m) => desired.push({ id: m.id, superset_group_id: groupId }));
    block = [];
  };
  for (const te of flat) {
    if (te.superset_group_id === groupId) {
      block.push(te);
    } else {
      flush();
      desired.push({ id: te.id, superset_group_id: te.superset_group_id ?? null });
    }
  }
  flush();
  return diffSlots(current, desired);
}

/** A compact "3×8" / "3 sets" style summary of a slot's default targets. */
export function targetSummary(te: TemplateExercise): string {
  const sets = te.default_sets;
  const reps = te.default_reps;
  if (sets && reps) return `${sets}×${reps}`;
  if (sets) return `${sets} ${sets === 1 ? "set" : "sets"}`;
  if (reps) return `${reps} reps`;
  return "—";
}
