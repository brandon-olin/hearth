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
import { Loader2, Link2, PenLine } from "lucide-react";
import { getAccessToken } from "@/lib/auth/token";
import type { components } from "@/lib/api/schema";

type Recipe = components["schemas"]["RecipeResponse"];

type FormState = {
  name: string;
  description: string;
  source_url: string;
  prep_time_minutes: string;
  cook_time_minutes: string;
  servings: string;
  notes: string;
};

// Structured data returned from GET /recipes/import
type ImportPreview = {
  name: string;
  description: string | null;
  source_url: string | null;
  prep_time_minutes: number | null;
  cook_time_minutes: number | null;
  servings: number | null;
  ingredients: Array<{
    name: string;
    quantity: string | null;
    unit: string | null;
    sort_order: number;
  }>;
  steps: Array<{ step_number: number; instruction: string }>;
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

function formFromImport(p: ImportPreview): FormState {
  return {
    name: p.name,
    description: p.description ?? "",
    source_url: p.source_url ?? "",
    prep_time_minutes: p.prep_time_minutes ? String(p.prep_time_minutes) : "",
    cook_time_minutes: p.cook_time_minutes ? String(p.cook_time_minutes) : "",
    servings: p.servings ? String(p.servings) : "",
    notes: "",
  };
}

// ── Import tab ────────────────────────────────────────────────────────────────

function ImportTab({ onImported }: { onImported: (p: ImportPreview) => void }) {
  const [url, setUrl] = useState("");
  const [fetching, setFetching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFetch() {
    const trimmed = url.trim();
    if (!trimmed) {
      setError("Please enter a URL.");
      return;
    }
    setFetching(true);
    setError(null);
    try {
      const token = getAccessToken();
      const qs = new URLSearchParams({ url: trimmed });
      const res = await fetch(`/api/recipes/import?${qs}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          (body as { detail?: string }).detail ?? `HTTP ${res.status}`
        );
      }
      const preview = (await res.json()) as ImportPreview;
      onImported(preview);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setFetching(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        Paste a recipe URL and the fields will be filled in automatically from
        the page's structured data.
      </p>
      <div className="space-y-1.5">
        <Label htmlFor="import-url">Recipe URL</Label>
        <div className="flex gap-2">
          <Input
            id="import-url"
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !fetching && handleFetch()}
            placeholder="https://www.allrecipes.com/recipe/…"
            autoFocus
            className="flex-1"
          />
          <Button onClick={handleFetch} disabled={fetching} size="sm">
            {fetching ? <Loader2 className="h-4 w-4 animate-spin" /> : "Fetch"}
          </Button>
        </div>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <p className="text-xs text-muted-foreground">
        Works on sites that publish Schema.org recipe markup — AllRecipes, NYT
        Cooking, Serious Eats, BBC Good Food, and most major recipe sites.
      </p>
    </div>
  );
}

// ── Main sheet ────────────────────────────────────────────────────────────────

type Tab = "manual" | "import";

export function RecipeSheet({
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

  const [tab, setTab] = useState<Tab>("manual");
  const [form, setForm] = useState<FormState>(blankForm());
  // Ingredients + steps captured from an import (passed along verbatim on save)
  const [importedIngredients, setImportedIngredients] = useState<
    ImportPreview["ingredients"]
  >([]);
  const [importedSteps, setImportedSteps] = useState<ImportPreview["steps"]>(
    []
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Sync form state whenever the sheet opens/closes
  const [lastOpen, setLastOpen] = useState(false);
  if (open !== lastOpen) {
    setLastOpen(open);
    if (open) {
      setTab("manual");
      setForm(recipe ? formFromRecipe(recipe) : blankForm());
      setImportedIngredients([]);
      setImportedSteps([]);
      setError(null);
    }
  }

  const { mutateAsync: createRecipe } = $api.useMutation("post", "/recipes");
  const { mutateAsync: updateRecipe } = $api.useMutation("patch", "/recipes/{recipe_id}");
  const { mutateAsync: deleteRecipe } = $api.useMutation("delete", "/recipes/{recipe_id}");

  function set<K extends keyof FormState>(key: K, val: FormState[K]) {
    setForm((p) => ({ ...p, [key]: val }));
  }

  function handleImported(preview: ImportPreview) {
    setForm(formFromImport(preview));
    setImportedIngredients(preview.ingredients ?? []);
    setImportedSteps(preview.steps ?? []);
    setTab("manual"); // switch to form so user can review & edit
  }

  async function handleSave() {
    if (!form.name.trim()) {
      setError("Name is required.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const base = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        source_url: form.source_url.trim() || null,
        prep_time_minutes: form.prep_time_minutes
          ? Number(form.prep_time_minutes)
          : null,
        cook_time_minutes: form.cook_time_minutes
          ? Number(form.cook_time_minutes)
          : null,
        servings: form.servings ? Number(form.servings) : null,
        notes: form.notes.trim() || null,
      };

      if (isEdit) {
        await updateRecipe({
          params: { path: { recipe_id: recipe.id } },
          body: base,
        });
      } else {
        const ingredients = importedIngredients.map((ing, i) => ({
          name: ing.name,
          quantity: ing.quantity != null ? Number(ing.quantity) : null,
          unit: ing.unit ?? null,
          notes: null,
          sort_order: ing.sort_order ?? i,
        }));
        const steps = importedSteps.map((s) => ({
          step_number: s.step_number,
          instruction: s.instruction,
          notes: null,
        }));
        await createRecipe({ body: { ...base, ingredients, steps } });
      }

      qc.invalidateQueries({ queryKey: ["get", "/recipes"] });
      onClose();
    } catch {
      setError("Something went wrong.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!recipe) return;
    setSaving(true);
    try {
      await deleteRecipe({ params: { path: { recipe_id: recipe.id } } });
      qc.invalidateQueries({ queryKey: ["get", "/recipes"] });
      onClose();
    } finally {
      setSaving(false);
    }
  }

  const hasImportedData =
    importedIngredients.length > 0 || importedSteps.length > 0;

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-md overflow-y-auto flex flex-col gap-0 p-0">
        <SheetHeader className="px-6 pt-6 pb-4 border-b">
          <SheetTitle>{isEdit ? "Edit recipe" : "New recipe"}</SheetTitle>
          <SheetDescription className="sr-only">
            {isEdit ? "Update this recipe" : "Add a new recipe"}
          </SheetDescription>
        </SheetHeader>

        {/* Tab switcher — only for new recipes */}
        {!isEdit && (
          <div className="flex border-b px-6">
            {(["manual", "import"] as Tab[]).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className={`flex items-center gap-1.5 px-1 py-3 text-sm font-medium border-b-2 mr-4 last:mr-0 transition-colors ${
                  tab === t
                    ? "border-primary text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                }`}
              >
                {t === "manual" ? (
                  <PenLine className="h-3.5 w-3.5" />
                ) : (
                  <Link2 className="h-3.5 w-3.5" />
                )}
                {t === "manual" ? "Manual" : "Import from URL"}
              </button>
            ))}
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {tab === "import" && !isEdit ? (
            <ImportTab onImported={handleImported} />
          ) : (
            <div className="space-y-4">
              {hasImportedData && (
                <div className="rounded-md bg-muted/60 border px-3 py-2 text-xs text-muted-foreground">
                  Imported {importedIngredients.length} ingredient
                  {importedIngredients.length !== 1 ? "s" : ""} and{" "}
                  {importedSteps.length} step
                  {importedSteps.length !== 1 ? "s" : ""} — they'll be saved
                  with the recipe.
                </div>
              )}
              <div className="space-y-1.5">
                <Label htmlFor="r-name">Name</Label>
                <Input
                  id="r-name"
                  value={form.name}
                  onChange={(e) => set("name", e.target.value)}
                  placeholder="Pasta carbonara"
                  autoFocus
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="r-desc">Description</Label>
                <Textarea
                  id="r-desc"
                  value={form.description}
                  rows={2}
                  onChange={(e) => set("description", e.target.value)}
                  placeholder="Short description…"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="r-url">Source URL</Label>
                <Input
                  id="r-url"
                  type="url"
                  value={form.source_url}
                  onChange={(e) => set("source_url", e.target.value)}
                  placeholder="https://…"
                />
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="r-prep">Prep (min)</Label>
                  <Input
                    id="r-prep"
                    type="number"
                    min="0"
                    value={form.prep_time_minutes}
                    onChange={(e) => set("prep_time_minutes", e.target.value)}
                    placeholder="15"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="r-cook">Cook (min)</Label>
                  <Input
                    id="r-cook"
                    type="number"
                    min="0"
                    value={form.cook_time_minutes}
                    onChange={(e) => set("cook_time_minutes", e.target.value)}
                    placeholder="30"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="r-serv">Servings</Label>
                  <Input
                    id="r-serv"
                    type="number"
                    min="1"
                    value={form.servings}
                    onChange={(e) => set("servings", e.target.value)}
                    placeholder="4"
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="r-notes">Notes</Label>
                <Textarea
                  id="r-notes"
                  value={form.notes}
                  rows={3}
                  onChange={(e) => set("notes", e.target.value)}
                  placeholder="Tips, substitutions, variations…"
                />
              </div>
            </div>
          )}
        </div>

        {/* Footer — hidden while on the import tab (no save action yet) */}
        {(tab === "manual" || isEdit) && (
          <div className="px-6 py-4 border-t flex items-center gap-2">
            {error ? (
              <p className="flex-1 text-sm text-destructive">{error}</p>
            ) : (
              <span className="flex-1" />
            )}
            {isEdit && (
              <Button
                variant="ghost"
                size="sm"
                className="text-destructive hover:text-destructive"
                onClick={handleDelete}
                disabled={saving}
              >
                Delete
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={onClose} disabled={saving}>
              Cancel
            </Button>
            <Button size="sm" onClick={handleSave} disabled={saving}>
              {saving && (
                <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
              )}
              {isEdit ? "Save" : "Create"}
            </Button>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
