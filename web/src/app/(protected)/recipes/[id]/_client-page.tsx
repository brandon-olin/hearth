"use client";

import dynamic from "next/dynamic";
import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSegmentId } from "@/lib/hooks/use-segment-id";
import { $api } from "@/lib/api/query";
import { apiBaseUrl } from "@/lib/api/client";
import { fetchWithAuth } from "@/lib/api/fetch-with-auth";
import { Button } from "@/components/ui/button";
import { Loader2, ChevronLeft, ExternalLink, Clock, Users, Edit, ChefHat, Sun, SunDim, ShoppingCart, Check, Plus, ArrowRight } from "lucide-react";
import type { components } from "@/lib/api/schema";
import { resolveMediaUrl } from "@/lib/api/client";
import { useWakeLock } from "@/lib/hooks/use-wake-lock";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useAuth } from "@/lib/auth/context";
import { usePermissions } from "@/lib/hooks/use-permissions";
import { cn } from "@/lib/utils";
import { useRegisterCurrentResource } from "@/lib/chat-context/current-resource";

type Recipe = components["schemas"]["RecipeResponse"];

const RecipeBodyEditor = dynamic(
  () => import("@/components/recipes/recipe-body-editor").then((m) => m.RecipeBodyEditor),
  { ssr: false, loading: () => <div className="h-32 flex items-center justify-center text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin mr-2" />Loading editor…</div> }
);

// Maps common cooking decimals back to unicode fraction characters.
// e.g. 0.333... → "⅓", 1.5 → "1½", 2.25 → "2¼"
const FRAC_MAP: [number, string][] = [
  [1 / 8, "⅛"], [1 / 4, "¼"], [1 / 3, "⅓"], [3 / 8, "⅜"],
  [1 / 2, "½"], [5 / 8, "⅝"], [2 / 3, "⅔"], [3 / 4, "¾"], [7 / 8, "⅞"],
];
const EPS = 0.02;

function formatQuantity(qty: number | string | null | undefined): string | null {
  if (qty == null) return null;
  const n = Number(qty);
  if (isNaN(n) || n <= 0) return null;
  const whole = Math.floor(n);
  const frac = n - whole;
  if (frac < EPS) return String(whole);
  const fracChar = FRAC_MAP.find(([v]) => Math.abs(frac - v) < EPS)?.[1] ?? null;
  if (!fracChar) return n.toFixed(2).replace(/\.?0+$/, "");
  return whole > 0 ? `${whole}${fracChar}` : fracChar;
}

function formatTime(mins: number | null): string | null {
  if (!mins) return null;
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

function RecipeHeader({ recipe }: { recipe: Recipe }) {
  const totalMins = (recipe.prep_time_minutes ?? 0) + (recipe.cook_time_minutes ?? 0);
  const timeStr = formatTime(totalMins || null);

  return (
    <div className="space-y-4">
      {/* Cover image or placeholder */}
      <div className="relative w-full rounded-xl overflow-hidden bg-muted" style={{ height: "280px" }}>
        {recipe.cover_image_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={resolveMediaUrl(recipe.cover_image_url) ?? ""}
            alt={recipe.name}
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <ChefHat className="h-16 w-16 text-muted-foreground/20" />
          </div>
        )}
      </div>

      <div className="flex items-start justify-between gap-4">
        <h1 className="text-2xl font-semibold leading-tight">{recipe.name}</h1>
        {recipe.source_url && (
          <a
            href={recipe.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground px-3 py-1.5 rounded-md hover:bg-muted transition-colors"
          >
            <ExternalLink className="h-4 w-4" />Source
          </a>
        )}
      </div>

      {recipe.description && (
        <p className="text-muted-foreground">{recipe.description}</p>
      )}

      <div className="flex items-center gap-4 text-sm text-muted-foreground">
        {timeStr && (
          <span className="flex items-center gap-1.5">
            <Clock className="h-4 w-4" />{timeStr}
          </span>
        )}
        {recipe.prep_time_minutes && (
          <span>Prep: {formatTime(recipe.prep_time_minutes)}</span>
        )}
        {recipe.cook_time_minutes && (
          <span>Cook: {formatTime(recipe.cook_time_minutes)}</span>
        )}
        {recipe.servings && (
          <span className="flex items-center gap-1.5">
            <Users className="h-4 w-4" />{recipe.servings} servings
          </span>
        )}
      </div>

      {recipe.tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {recipe.tags.map((tag) => (
            <span
              key={tag.id}
              className="text-xs px-2.5 py-0.5 rounded-full bg-primary/10 text-primary font-medium"
            >
              {tag.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Add to grocery list ───────────────────────────────────────────────────────

type GroceryList = components["schemas"]["GroceryListResponse"];

function AddToGroceryList({ recipeId, recipeName, hasIngredients }: {
  recipeId: string;
  recipeName: string;
  hasIngredients: boolean;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [adding, setAdding] = useState(false);
  const [result, setResult] = useState<{ listId: string; listName: string; added: number } | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  // Fetch active lists when the picker opens
  const { data: listsData, isLoading: listsLoading } = $api.useQuery(
    "get",
    "/grocery-lists",
    { params: { query: { status: "active", limit: 50 } } },
    { enabled: open && !result }
  );
  const activeLists: GroceryList[] = listsData?.items ?? [];

  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);

  const doAdd = async (listId: string, listName: string) => {
    setAdding(true);
    try {
      const res = await fetchWithAuth(`${apiBaseUrl}/recipes/${recipeId}/add-to-grocery-list`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ list_id: listId }),
      });
      if (!res.ok) throw new Error("Failed");
      const data = await res.json() as { added: number; skipped: number };
      setResult({ listId, listName, added: data.added });
      setOpen(false);
    } finally {
      setAdding(false);
    }
  };

  const doCreateAndAdd = async () => {
    setCreating(true);
    try {
      const res = await fetchWithAuth(`${apiBaseUrl}/grocery-lists`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: recipeName, status: "active", items: [], visibility: "household" }),
      });
      if (!res.ok) throw new Error("Failed to create list");
      const newList = await res.json() as GroceryList;
      await doAdd(newList.id, newList.name);
    } finally {
      setCreating(false);
    }
  };

  if (!hasIngredients) return null;

  // Success state — show confirmation chip
  if (result) {
    return (
      <div className="flex items-center gap-2 mt-4">
        <span className="flex items-center gap-1.5 text-xs text-green-600 font-medium">
          <Check className="h-3.5 w-3.5" />
          {result.added > 0 ? `${result.added} item${result.added === 1 ? "" : "s"} added` : "Already in list"}
        </span>
        <button
          onClick={() => router.push("/grocery-lists")}
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          Open list <ArrowRight className="h-3 w-3" />
        </button>
        <button onClick={() => setResult(null)} className="text-xs text-muted-foreground/60 hover:text-muted-foreground ml-auto">
          ✕
        </button>
      </div>
    );
  }

  return (
    <div ref={ref} className="relative mt-4">
      <Button
        variant="outline"
        size="sm"
        onClick={() => setOpen((v) => !v)}
        disabled={adding || creating}
        className="gap-1.5"
      >
        {(adding || creating) ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShoppingCart className="h-3.5 w-3.5" />}
        Add to grocery list
      </Button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full mt-1 z-20 bg-background border rounded-lg shadow-lg py-1 min-w-[220px]">
            {listsLoading ? (
              <div className="flex items-center gap-2 px-3 py-2 text-sm text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading lists…
              </div>
            ) : activeLists.length === 0 ? (
              <p className="px-3 py-2 text-xs text-muted-foreground">No active grocery lists</p>
            ) : (
              <>
                <p className="px-3 pt-1.5 pb-1 text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  Add to list
                </p>
                {activeLists.map((list) => (
                  <button
                    key={list.id}
                    onClick={() => void doAdd(list.id, list.name)}
                    className="w-full text-left px-3 py-2 text-sm hover:bg-muted transition-colors flex items-center gap-2"
                  >
                    <ShoppingCart className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                    <span className="truncate">{list.name}</span>
                    {list.store && <span className="text-xs text-muted-foreground shrink-0">· {list.store}</span>}
                  </button>
                ))}
                <div className="border-t mt-1 pt-1" />
              </>
            )}
            <button
              onClick={() => void doCreateAndAdd()}
              className={cn(
                "w-full text-left px-3 py-2 text-sm hover:bg-muted transition-colors flex items-center gap-2",
                creating && "opacity-50 pointer-events-none"
              )}
            >
              <Plus className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
              New list for this recipe
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function IngredientsList({ recipe }: { recipe: Recipe }) {
  if (!recipe.ingredients.length) return null;
  return (
    <div>
      <h2 className="text-base font-semibold mb-3">Ingredients</h2>
      <ul className="space-y-1.5">
        {recipe.ingredients.map((ing) => (
          <li key={ing.id} className="flex items-baseline gap-2 text-sm">
            <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/50 shrink-0 mt-1.5" />
            <span>
              {ing.quantity != null && <span className="font-medium">{formatQuantity(ing.quantity)}{ing.unit ? ` ${ing.unit}` : ""} </span>}
              {ing.name}
              {ing.notes && <span className="text-muted-foreground"> — {ing.notes}</span>}
            </span>
          </li>
        ))}
      </ul>
      <AddToGroceryList
        recipeId={recipe.id}
        recipeName={recipe.name}
        hasIngredients={recipe.ingredients.length > 0}
      />
    </div>
  );
}

function StepsList({ recipe }: { recipe: Recipe }) {
  if (!recipe.steps.length) return null;
  return (
    <div>
      <h2 className="text-base font-semibold mb-3">Instructions</h2>
      <ol className="space-y-4">
        {recipe.steps.map((step) => (
          <li key={step.id} className="flex gap-4 text-sm">
            <span className="flex-none w-6 h-6 rounded-full bg-muted flex items-center justify-center text-xs font-semibold text-muted-foreground">
              {step.step_number}
            </span>
            <div className="flex-1 pt-0.5">
              <p>{step.instruction}</p>
              {step.notes && <p className="mt-1 text-muted-foreground text-xs">{step.notes}</p>}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

export default function RecipeDetailPage() {
  const id = useSegmentId();
  const router = useRouter();
  const { user } = useAuth();
  const { can } = usePermissions();
  const { isActive: wakeLockActive, isSupported: wakeLockSupported, toggle: toggleWakeLock } = useWakeLock();

  const { data: recipe, isLoading, isError } = $api.useQuery(
    "get",
    "/recipes/{recipe_id}",
    { params: { path: { recipe_id: id } } }
  );

  // chat-001: publish this recipe so the chat sidebar can show
  // 'Discussing: <recipe name>' and the AI can answer questions about
  // 'this recipe' without the user pasting any content.
  useRegisterCurrentResource(
    recipe ? { type: "recipe", id, title: recipe.name ?? "" } : null,
  );

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />Loading…
      </div>
    );
  }

  if (isError || !recipe) {
    return <p className="p-8 text-sm text-destructive">Recipe not found.</p>;
  }

  return (
    <div className="page-content">
      {/* Nav row: back left, actions right */}
      <div className="flex items-center justify-between mb-5">
        <Button
          variant="ghost"
          size="sm"
          className="-ml-1.5 h-7 px-1.5 gap-1 text-xs text-muted-foreground hover:text-foreground"
          onClick={() => router.push("/recipes")}
        >
          <ChevronLeft className="h-3.5 w-3.5" />
          Recipes
        </Button>
        <div className="flex items-center gap-2">
          {wakeLockSupported && (
            <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant={wakeLockActive ? "secondary" : "ghost"}
                  size="sm"
                  onClick={toggleWakeLock}
                  className={wakeLockActive ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground"}
                  aria-label={wakeLockActive ? "Screen will stay on — tap to disable" : "Keep screen on while cooking"}
                  aria-pressed={wakeLockActive}
                >
                  {wakeLockActive
                    ? <Sun className="h-3.5 w-3.5" />
                    : <SunDim className="h-3.5 w-3.5" />
                  }
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                {wakeLockActive ? "Screen staying on — tap to disable" : "Keep screen on while cooking"}
              </TooltipContent>
            </Tooltip>
            </TooltipProvider>
          )}
          {(recipe && (recipe.created_by_user_id === (user as { id?: string } | null)?.id || can("recipes", "manage_others"))) && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => router.push(`/recipes/${id}/edit`)}
            >
              <Edit className="h-3.5 w-3.5 mr-1.5" />
              Edit
            </Button>
          )}
        </div>
      </div>

      {/* Header: cover image, name, times */}
      <RecipeHeader recipe={recipe} />

      <div className="mt-8 space-y-8">
        {/* Structured sections */}
        <IngredientsList recipe={recipe} />
        <StepsList recipe={recipe} />

        {/* Notes */}
        {recipe.notes && (
          <div>
            <h2 className="text-base font-semibold mb-2">Notes</h2>
            <p className="text-sm text-muted-foreground whitespace-pre-wrap">{recipe.notes}</p>
          </div>
        )}

        {/* Divider before rich body */}
        {(recipe.ingredients.length > 0 || recipe.steps.length > 0) && (
          <hr className="border-border" />
        )}

        {/* BlockNote body — freeform rich text */}
        <div>
          <h2 className="text-base font-semibold mb-3">Notes &amp; Story</h2>
          <RecipeBodyEditor recipeId={id} initialBody={recipe.body} />
        </div>
      </div>

    </div>
  );
}
