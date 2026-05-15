"use client";

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useSegmentId } from "@/lib/hooks/use-segment-id";
import { $api } from "@/lib/api/query";
import { Button } from "@/components/ui/button";
import { Loader2, ChevronLeft, ExternalLink, Clock, Users, Edit, ChefHat, Sun, SunDim } from "lucide-react";
import type { components } from "@/lib/api/schema";
import { resolveMediaUrl } from "@/lib/api/client";
import { useWakeLock } from "@/lib/hooks/use-wake-lock";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useAuth } from "@/lib/auth/context";
import { usePermissions } from "@/lib/hooks/use-permissions";

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
