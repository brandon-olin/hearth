"use client";

import { useState } from "react";
import { $api } from "@/lib/api/query";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
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
  ChefHat,
  Clock,
  ExternalLink,
  Search,
} from "lucide-react";
import type { components } from "@/lib/api/schema";

type Recipe = components["schemas"]["RecipeResponse"];

// ── helpers ───────────────────────────────────────────────────────────────────

function formatTime(mins: number | null): string | null {
  if (!mins) return null;
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

// ── recipe sheet ──────────────────────────────────────────────────────────────

type FormState = {
  name: string;
  description: string;
  source_url: string;
  prep_time_minutes: string;
  cook_time_minutes: string;
  servings: string;
  notes: string;
};

function blankForm(): FormState {
  return {
    name: "",
    description: "",
    source_url: "",
    prep_time_minutes: "",
    cook_time_minutes: "",
    servings: "",
    notes: "",
  };
}

function formFromRecipe(r: Recipe): FormState {
  return {
    name: r.name,
    description: r.description ?? "",
    source_url: r.source_url ?? "",
    prep_time_minutes: r.prep_time_minutes ? String(r.prep_time_minutes) : "",
    cook_time_minutes: r.cook_time_minutes ? String(r.cook_time_minutes) : "",
    servings: r.servings ? String(r.servings) : "",
    notes: r.notes ?? "",
  };
}

function RecipeSheet({
  open,
  recipe,
  onClose,
}: {
  open: boolean;
  recipe: Recipe | null;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const isEdit = recipe !== null;
  const [form, setForm] = useState<FormState>(blankForm());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset form on open
  const [lastOpen, setLastOpen] = useState(false);
  if (open !== lastOpen) {
    setLastOpen(open);
    if (open) {
      setForm(recipe ? formFromRecipe(recipe) : blankForm());
      setError(null);
    }
  }

  const { mutateAsync: createRecipe } = $api.useMutation("post", "/recipes");
  const { mutateAsync: updateRecipe } = $api.useMutation("patch", "/recipes/{recipe_id}");
  const { mutateAsync: deleteRecipe } = $api.useMutation("delete", "/recipes/{recipe_id}");

  function set<K extends keyof FormState>(key: K, val: FormState[K]) {
    setForm((p) => ({ ...p, [key]: val }));
  }

  async function handleSave() {
    if (!form.name.trim()) { setError("Name is required."); return; }
    setSaving(true); setError(null);
    try {
      const body = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        source_url: form.source_url.trim() || null,
        prep_time_minutes: form.prep_time_minutes ? Number(form.prep_time_minutes) : null,
        cook_time_minutes: form.cook_time_minutes ? Number(form.cook_time_minutes) : null,
        servings: form.servings ? Number(form.servings) : null,
        notes: form.notes.trim() || null,
      };
      if (isEdit) {
        await updateRecipe({ params: { path: { recipe_id: recipe.id } }, body });
      } else {
        await createRecipe({ body: { ...body, ingredients: [], steps: [] } });
      }
      qc.invalidateQueries({ queryKey: ["get", "/recipes"] });
      onClose();
    } catch { setError("Something went wrong."); }
    finally { setSaving(false); }
  }

  async function handleDelete() {
    if (!recipe) return;
    setSaving(true);
    try {
      await deleteRecipe({ params: { path: { recipe_id: recipe.id } } });
      qc.invalidateQueries({ queryKey: ["get", "/recipes"] });
      onClose();
    } finally { setSaving(false); }
  }

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-md overflow-y-auto flex flex-col gap-0 p-0">
        <SheetHeader className="px-6 pt-6 pb-4 border-b">
          <SheetTitle>{isEdit ? "Edit recipe" : "New recipe"}</SheetTitle>
          <SheetDescription className="sr-only">
            {isEdit ? "Update this recipe" : "Add a new recipe"}
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="r-name">Name</Label>
            <Input id="r-name" value={form.name} onChange={(e) => set("name", e.target.value)}
              placeholder="Pasta carbonara" autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="r-desc">Description</Label>
            <Textarea id="r-desc" value={form.description} rows={2}
              onChange={(e) => set("description", e.target.value)}
              placeholder="Short description…" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="r-url">Source URL</Label>
            <Input id="r-url" type="url" value={form.source_url}
              onChange={(e) => set("source_url", e.target.value)}
              placeholder="https://…" />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="r-prep">Prep (min)</Label>
              <Input id="r-prep" type="number" min="0" value={form.prep_time_minutes}
                onChange={(e) => set("prep_time_minutes", e.target.value)} placeholder="15" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="r-cook">Cook (min)</Label>
              <Input id="r-cook" type="number" min="0" value={form.cook_time_minutes}
                onChange={(e) => set("cook_time_minutes", e.target.value)} placeholder="30" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="r-serv">Servings</Label>
              <Input id="r-serv" type="number" min="1" value={form.servings}
                onChange={(e) => set("servings", e.target.value)} placeholder="4" />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="r-notes">Notes</Label>
            <Textarea id="r-notes" value={form.notes} rows={3}
              onChange={(e) => set("notes", e.target.value)}
              placeholder="Tips, substitutions, variations…" />
          </div>
        </div>

        <div className="px-6 py-4 border-t flex items-center gap-2">
          {error ? <p className="flex-1 text-sm text-destructive">{error}</p> : <span className="flex-1" />}
          {isEdit && (
            <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive"
              onClick={handleDelete} disabled={saving}>Delete</Button>
          )}
          <Button variant="outline" size="sm" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button size="sm" onClick={handleSave} disabled={saving}>
            {saving && <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />}
            {isEdit ? "Save" : "Create"}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

// ── recipe card ───────────────────────────────────────────────────────────────

function RecipeCard({ recipe, onClick }: { recipe: Recipe; onClick: () => void }) {
  const totalMins = (recipe.prep_time_minutes ?? 0) + (recipe.cook_time_minutes ?? 0);
  const timeStr = formatTime(totalMins || null);

  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left border rounded-lg p-4 bg-card hover:bg-muted/30 transition-colors group"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="font-medium text-sm leading-snug">{recipe.name}</span>
        {recipe.source_url && (
          <a
            href={recipe.source_url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="shrink-0 text-muted-foreground hover:text-foreground"
          >
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        )}
      </div>
      {recipe.description && (
        <p className="mt-1 text-xs text-muted-foreground line-clamp-2">{recipe.description}</p>
      )}
      <div className="flex items-center gap-3 mt-2 text-xs text-muted-foreground">
        {timeStr && (
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {timeStr}
          </span>
        )}
        {recipe.servings && <span>{recipe.servings} servings</span>}
      </div>
    </button>
  );
}

// ── page ──────────────────────────────────────────────────────────────────────

export default function RecipesPage() {
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editing, setEditing] = useState<Recipe | null>(null);
  const [search, setSearch] = useState("");

  const { data, isLoading, isError } = $api.useQuery("get", "/recipes", {
    params: { query: { limit: 200 } },
  });

  const q = search.toLowerCase();
  const displayed = (data?.items ?? []).filter(
    (r) => !q || r.name.toLowerCase().includes(q) || r.description?.toLowerCase().includes(q)
  );

  function openCreate() { setEditing(null); setSheetOpen(true); }
  function openEdit(r: Recipe) { setEditing(r); setSheetOpen(true); }
  function handleClose() { setSheetOpen(false); setTimeout(() => setEditing(null), 300); }

  return (
    <div className="p-6 max-w-4xl">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <ChefHat className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-xl font-semibold">Recipes</h1>
        </div>
        <Button size="sm" onClick={openCreate}>
          <Plus className="h-4 w-4 mr-1" />New
        </Button>
      </div>

      {/* Search */}
      <div className="relative mb-5">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          className="pl-9"
          placeholder="Search recipes…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Loading…
        </div>
      )}
      {isError && <p className="py-8 text-sm text-destructive">Failed to load recipes.</p>}
      {!isLoading && !isError && displayed.length === 0 && (
        <div className="py-12 text-center">
          <ChefHat className="h-8 w-8 text-muted-foreground/30 mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">
            {search ? "No recipes match that search." : "No recipes yet."}
          </p>
          {!search && (
            <Button variant="outline" size="sm" className="mt-4" onClick={openCreate}>
              <Plus className="h-4 w-4 mr-1" />Add one
            </Button>
          )}
        </div>
      )}
      {displayed.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {displayed.map((r) => (
            <RecipeCard key={r.id} recipe={r} onClick={() => openEdit(r)} />
          ))}
        </div>
      )}

      <RecipeSheet open={sheetOpen} recipe={editing} onClose={handleClose} />
    </div>
  );
}
