"use client";

/**
 * Weekly meal planner (meal-001).
 *
 * The grid is seven day columns × four meal slots. Recipes drag in from the
 * sidebar; planned meals drag between cells. Every drop is a server write —
 * there is no local plan state to fall out of sync, and the plan row for the
 * week is created lazily on the first drop (the API's POST /meal-plans is a
 * get-or-create, so racing drops cannot mint two plans).
 */

import { useMemo, useState } from "react";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Loader2,
  ShoppingCart,
  Search,
  X,
} from "lucide-react";
import Link from "next/link";

import { $api } from "@/lib/api/query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDebounce } from "@/lib/hooks/use-debounce";
import { cn } from "@/lib/utils";
import type { components } from "@/lib/api/schema";

type MealPlan = components["schemas"]["MealPlanResponse"];
type MealPlanEntry = components["schemas"]["MealPlanEntryResponse"];
type Recipe = components["schemas"]["RecipeResponse"];
type GenerateResult = components["schemas"]["GenerateGroceryListResponse"];

const SLOTS = ["breakfast", "lunch", "dinner", "snack"] as const;
type Slot = (typeof SLOTS)[number];

const SLOT_LABEL: Record<Slot, string> = {
  breakfast: "Breakfast",
  lunch: "Lunch",
  dinner: "Dinner",
  snack: "Snack",
};

const DAY_LABEL = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// ── Dates ─────────────────────────────────────────────────────────────────────
// Local-time throughout. toISOString() would shift the date by a day for anyone
// west of UTC, which on a *calendar* grid means meals landing on the wrong day.

function toISODate(d: Date): string {
  const month = `${d.getMonth() + 1}`.padStart(2, "0");
  const day = `${d.getDate()}`.padStart(2, "0");
  return `${d.getFullYear()}-${month}-${day}`;
}

/** The Monday of `d`'s week — the same normalisation the API applies. */
function mondayOf(d: Date): Date {
  const copy = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const offset = (copy.getDay() + 6) % 7; // JS Sunday=0 → Monday-first
  copy.setDate(copy.getDate() - offset);
  return copy;
}

function addDays(d: Date, n: number): Date {
  const copy = new Date(d);
  copy.setDate(copy.getDate() + n);
  return copy;
}

function formatRange(monday: Date): string {
  const sunday = addDays(monday, 6);
  const sameMonth = monday.getMonth() === sunday.getMonth();
  const opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
  const start = monday.toLocaleDateString(undefined, opts);
  const end = sunday.toLocaleDateString(
    undefined,
    sameMonth ? { day: "numeric" } : opts,
  );
  return `${start} – ${end}`;
}

// ── Drag ids ──────────────────────────────────────────────────────────────────
// Encoded as strings because dnd-kit ids are scalars. Parsing is centralised so
// a malformed id can never be mistaken for a valid one.

const recipeDragId = (id: string) => `recipe:${id}`;
const entryDragId = (id: string) => `entry:${id}`;
const cellDropId = (date: string, slot: Slot) => `cell:${date}:${slot}`;

function parseCell(id: string): { date: string; slot: Slot } | null {
  const parts = id.split(":");
  if (parts.length !== 3 || parts[0] !== "cell") return null;
  if (!SLOTS.includes(parts[2] as Slot)) return null;
  return { date: parts[1], slot: parts[2] as Slot };
}

// ── Sidebar recipe ────────────────────────────────────────────────────────────

function DraggableRecipe({ recipe }: { recipe: Recipe }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: recipeDragId(recipe.id),
    data: { kind: "recipe", recipeId: recipe.id, name: recipe.name },
  });
  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className={cn(
        "rounded-md border border-border bg-card px-3 py-2 text-sm select-none",
        "hover:border-primary/50 transition-colors cursor-grab active:cursor-grabbing",
        isDragging && "opacity-40",
      )}
    >
      <span className="line-clamp-2 break-words">{recipe.name}</span>
    </div>
  );
}

// ── Planned meal chip ─────────────────────────────────────────────────────────

function PlannedMeal({
  entry,
  onRemove,
  removing,
}: {
  entry: MealPlanEntry;
  onRemove: () => void;
  removing: boolean;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: entryDragId(entry.id),
    data: { kind: "entry", entryId: entry.id, name: entry.recipe_name },
  });
  return (
    <div
      ref={setNodeRef}
      className={cn(
        "group flex items-start gap-1 rounded-md bg-primary/10 border border-primary/30",
        "px-2 py-1 text-xs",
        isDragging && "opacity-40",
      )}
    >
      <span
        {...listeners}
        {...attributes}
        // break-words matters on the grid: a column is 1fr, whose floor is
        // min-content, so one unbreakable recipe name would widen its day
        // column and squeeze the other six.
        className="flex-1 min-w-0 break-words cursor-grab active:cursor-grabbing line-clamp-2"
      >
        {entry.recipe_name ?? "Recipe"}
      </span>
      <button
        type="button"
        onClick={onRemove}
        disabled={removing}
        aria-label={`Remove ${entry.recipe_name ?? "recipe"}`}
        className="opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity text-muted-foreground hover:text-foreground shrink-0"
      >
        {removing ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : (
          <X className="h-3 w-3" />
        )}
      </button>
    </div>
  );
}

// ── Grid cell ─────────────────────────────────────────────────────────────────

function Cell({
  date,
  slot,
  entries,
  onRemove,
  removingId,
}: {
  date: string;
  slot: Slot;
  entries: MealPlanEntry[];
  onRemove: (entryId: string) => void;
  removingId: string | null;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: cellDropId(date, slot) });
  return (
    <div
      ref={setNodeRef}
      data-testid={`cell-${date}-${slot}`}
      className={cn(
        // min-w-0 lets the 1fr day columns stay equal: without it a track's
        // floor is its min-content width, so one long recipe name widens that
        // day and squeezes the other six.
        "min-w-0 min-h-[64px] rounded-md border border-dashed p-1.5 flex flex-col gap-1 transition-colors",
        isOver ? "border-primary bg-primary/5" : "border-border",
      )}
    >
      {entries.map((entry) => (
        <PlannedMeal
          key={entry.id}
          entry={entry}
          onRemove={() => onRemove(entry.id)}
          removing={removingId === entry.id}
        />
      ))}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function MealPlannerPage() {
  const qc = useQueryClient();
  const [monday, setMonday] = useState(() => mondayOf(new Date()));
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounce(search, 300);
  const [dragLabel, setDragLabel] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [generated, setGenerated] = useState<GenerateResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const weekDates = useMemo(
    () => Array.from({ length: 7 }, (_, i) => toISODate(addDays(monday, i))),
    [monday],
  );
  const mondayISO = toISODate(monday);

  const { data: plan, isLoading: planLoading } = $api.useQuery(
    "get",
    "/meal-plans/week",
    { params: { query: { day: mondayISO } } },
  );

  const { data: recipeList, isLoading: recipesLoading } = $api.useQuery(
    "get",
    "/recipes",
    {
      params: {
        query: { limit: 100, ...(debouncedSearch ? { search: debouncedSearch } : {}) },
      },
    },
  );

  const { mutateAsync: createPlan } = $api.useMutation("post", "/meal-plans");
  const { mutateAsync: addEntry } = $api.useMutation(
    "post",
    "/meal-plans/{plan_id}/entries",
  );
  const { mutateAsync: moveEntry } = $api.useMutation(
    "patch",
    "/meal-plans/{plan_id}/entries/{entry_id}",
  );
  const { mutateAsync: deleteEntry } = $api.useMutation(
    "delete",
    "/meal-plans/{plan_id}/entries/{entry_id}",
  );
  const { mutateAsync: generateList, isPending: generating } = $api.useMutation(
    "post",
    "/meal-plans/{plan_id}/grocery-list",
  );

  const sensors = useSensors(
    // A few pixels of travel before a drag starts, so clicking the remove "×"
    // inside a draggable chip still registers as a click.
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  );

  const entriesByCell = useMemo(() => {
    const map = new Map<string, MealPlanEntry[]>();
    for (const entry of (plan as MealPlan | null)?.entries ?? []) {
      const key = `${entry.entry_date}:${entry.meal_slot}`;
      map.set(key, [...(map.get(key) ?? []), entry]);
    }
    return map;
  }, [plan]);

  function refresh() {
    qc.invalidateQueries({ queryKey: ["get", "/meal-plans/week"] });
  }

  /** The week's plan id, creating the plan on first use. */
  async function ensurePlanId(): Promise<string> {
    if (plan?.id) return plan.id;
    // Household visibility, always: a meal plan the cook cannot see is useless.
    // The planner never offers a visibility picker, so this is not a default
    // being repeated — it is the only value this screen ever writes.
    const created = await createPlan({
      body: { week_start: mondayISO, visibility: "household" },
    });
    return created.id;
  }

  async function handleDragEnd(event: DragEndEvent) {
    setDragLabel(null);
    const { active, over } = event;
    if (!over) return;
    const cell = parseCell(String(over.id));
    if (!cell) return;

    const data = active.data.current as
      | { kind: "recipe"; recipeId: string }
      | { kind: "entry"; entryId: string }
      | undefined;
    if (!data) return;

    setBusy(true);
    setError(null);
    try {
      const planId = await ensurePlanId();
      if (data.kind === "recipe") {
        await addEntry({
          params: { path: { plan_id: planId } },
          body: {
            recipe_id: data.recipeId,
            entry_date: cell.date,
            meal_slot: cell.slot,
            // Several dishes can share one slot; they render in insertion order.
            sort_order: entriesByCell.get(`${cell.date}:${cell.slot}`)?.length ?? 0,
          },
        });
      } else {
        await moveEntry({
          params: { path: { plan_id: planId, entry_id: data.entryId } },
          body: { entry_date: cell.date, meal_slot: cell.slot },
        });
      }
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update the plan");
    } finally {
      setBusy(false);
    }
  }

  async function handleRemove(entryId: string) {
    if (!plan?.id) return;
    setRemovingId(entryId);
    setError(null);
    try {
      await deleteEntry({
        params: { path: { plan_id: plan.id, entry_id: entryId } },
      });
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not remove that meal");
    } finally {
      setRemovingId(null);
    }
  }

  async function handleGenerate() {
    if (!plan?.id) return;
    setError(null);
    setGenerated(null);
    try {
      const result = await generateList({
        params: { path: { plan_id: plan.id } },
        body: {},
      });
      setGenerated(result);
      qc.invalidateQueries({ queryKey: ["get", "/grocery-lists"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not generate the list");
    }
  }

  function handleDragStart(event: DragStartEvent) {
    const data = event.active.data.current as { name?: string } | undefined;
    setDragLabel(data?.name ?? null);
  }

  const plannedCount = (plan as MealPlan | null)?.entries?.length ?? 0;
  const recipes = (recipeList?.items ?? []) as Recipe[];
  const isThisWeek = mondayISO === toISODate(mondayOf(new Date()));

  return (
    <DndContext
      sensors={sensors}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <div className="flex flex-col h-full min-h-0">
        {/* Header */}
        <div className="flex flex-wrap items-center gap-3 border-b px-6 py-4">
          <h1 className="text-lg font-semibold">Meal planner</h1>

          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              aria-label="Previous week"
              onClick={() => setMonday(addDays(monday, -7))}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="text-sm text-muted-foreground min-w-[9rem] text-center">
              {formatRange(monday)}
            </span>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Next week"
              onClick={() => setMonday(addDays(monday, 7))}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>

          {!isThisWeek && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setMonday(mondayOf(new Date()))}
            >
              Plan this week
            </Button>
          )}

          <div className="flex-1" />

          {busy && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}

          <Button
            size="sm"
            onClick={handleGenerate}
            disabled={generating || plannedCount === 0}
            title={
              plannedCount === 0
                ? "Plan at least one meal first"
                : "Aggregate this week's ingredients into a grocery list"
            }
          >
            {generating ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ShoppingCart className="h-4 w-4" />
            )}
            Generate grocery list
          </Button>
        </div>

        {/* Result / error banners */}
        {generated && (
          <div className="mx-6 mt-3 rounded-md border border-border bg-muted/40 px-3 py-2 text-sm flex items-center gap-2">
            <span>
              {generated.added > 0
                ? `Added ${generated.added} ${generated.added === 1 ? "item" : "items"}`
                : "Everything was already on the list"}
              {generated.skipped > 0 && ` · ${generated.skipped} already there`}
              {" · "}
              from {generated.recipes_planned}{" "}
              {generated.recipes_planned === 1 ? "meal" : "meals"}
            </span>
            <Link
              href="/grocery-lists"
              className="font-medium underline underline-offset-2"
            >
              Open {generated.list_name}
            </Link>
            <button
              type="button"
              className="ml-auto text-muted-foreground hover:text-foreground"
              onClick={() => setGenerated(null)}
              aria-label="Dismiss"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
        {error && (
          <div className="mx-6 mt-3 rounded-md border border-border bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        )}

        <div className="flex flex-col md:flex-row flex-1 min-h-0">
          {/* Recipe sidebar — on a phone the full-height rail would leave the
              week grid ~150px to render seven days in, so below md it becomes a
              bounded strip above the grid and the week gets the full width. */}
          <aside className="w-full md:w-56 shrink-0 max-h-48 md:max-h-none border-b md:border-b-0 md:border-r flex flex-col min-h-0">
            <div className="p-3 border-b">
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search recipes…"
                  className="pl-7 h-8 text-sm"
                />
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-2">
              {recipesLoading && (
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              )}
              {!recipesLoading && recipes.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  {search ? "No recipes match." : "No recipes yet."}
                </p>
              )}
              {recipes.map((recipe) => (
                <DraggableRecipe key={recipe.id} recipe={recipe} />
              ))}
            </div>
          </aside>

          {/* Week grid */}
          <div className="flex-1 overflow-auto p-4">
            {planLoading ? (
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            ) : (
              <div className="min-w-[40rem] md:min-w-[52rem]">
                {/* Day header row */}
                <div className="grid grid-cols-[3.5rem_repeat(7,1fr)] md:grid-cols-[5rem_repeat(7,1fr)] gap-1.5 mb-1.5">
                  <div />
                  {weekDates.map((iso, i) => (
                    <div key={iso} className="text-center">
                      <div className="text-xs font-medium">{DAY_LABEL[i]}</div>
                      <div className="text-[11px] text-muted-foreground">
                        {Number(iso.slice(8, 10))}
                      </div>
                    </div>
                  ))}
                </div>

                {SLOTS.map((slot) => (
                  <div
                    key={slot}
                    className="grid grid-cols-[3.5rem_repeat(7,1fr)] md:grid-cols-[5rem_repeat(7,1fr)] gap-1.5 mb-1.5"
                  >
                    <div className="text-xs text-muted-foreground pt-2">
                      {SLOT_LABEL[slot]}
                    </div>
                    {weekDates.map((iso) => (
                      <Cell
                        key={`${iso}:${slot}`}
                        date={iso}
                        slot={slot}
                        entries={entriesByCell.get(`${iso}:${slot}`) ?? []}
                        onRemove={handleRemove}
                        removingId={removingId}
                      />
                    ))}
                  </div>
                ))}

                {plannedCount === 0 && (
                  <p className="mt-6 text-sm text-muted-foreground">
                    Drag a recipe from the left onto a day to plan a meal.
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      <DragOverlay dropAnimation={null}>
        {dragLabel && (
          <div className="rounded-md border border-primary bg-card px-3 py-2 text-sm shadow-lg">
            {dragLabel}
          </div>
        )}
      </DragOverlay>
    </DndContext>
  );
}
