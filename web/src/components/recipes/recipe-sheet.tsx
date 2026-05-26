"use client";

import { useEffect, useRef, useState } from "react";
import { $api } from "@/lib/api/query";
import { resolveMediaUrl, apiBaseUrl } from "@/lib/api/client";
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
import { Loader2, Link2, PenLine, Tag, Plus, X, ImagePlus } from "lucide-react";
import { getAccessToken } from "@/lib/auth/token";
import { VisibilityPicker, type Visibility } from "@/components/visibility-picker";
import type { components } from "@/lib/api/schema";

type Recipe = components["schemas"]["RecipeResponse"];

// ── Tag types ─────────────────────────────────────────────────────────────────

/** A tag that's been confirmed in the DB (has a real UUID id). */
type ExistingTag = components["schemas"]["TagSummary"];
/** A tag the user typed that hasn't been saved to the DB yet — id is "". */
type PendingTag = { id: ""; name: string; color: null };
type SelectedTag = ExistingTag | PendingTag;

function isPending(t: SelectedTag): t is PendingTag {
  return t.id === "";
}

// ── Debounce ─────────────────────────────────────────────────────────────────

function useDebounced(value: string, delay: number) {
  const [d, setD] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setD(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return d;
}

// ── TagPicker ─────────────────────────────────────────────────────────────────

interface TagPickerProps {
  selected: SelectedTag[];
  onChange: (tags: SelectedTag[]) => void;
}

function TagPicker({ selected, onChange }: TagPickerProps) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const dq = useDebounced(query.trim(), 200);

  const { data: searchData } = $api.useQuery(
    "get",
    "/tags",
    { params: { query: { search: dq || undefined, entity_type: "recipe", limit: 10 } } },
    { enabled: open }
  );

  const allTags = searchData?.items ?? [];
  const selectedIds = new Set(selected.map((t) => t.id).filter(Boolean));
  const filteredTags = allTags.filter((t) => !selectedIds.has(t.id));

  const trimmed = query.trim();
  const exactMatch = allTags.some(
    (t) => t.name.toLowerCase() === trimmed.toLowerCase()
  );
  const alreadySelected = selected.some(
    (t) => t.name.toLowerCase() === trimmed.toLowerCase()
  );
  const showCreate = trimmed && !exactMatch && !alreadySelected;

  function addExisting(tag: ExistingTag) {
    onChange([...selected, tag]);
    setQuery("");
    inputRef.current?.focus();
  }

  function addPending() {
    if (!trimmed) return;
    onChange([...selected, { id: "", name: trimmed, color: null }]);
    setQuery("");
    inputRef.current?.focus();
  }

  function remove(tag: SelectedTag) {
    onChange(
      selected.filter((t) =>
        t.id ? t.id !== tag.id : t.name !== tag.name
      )
    );
  }

  return (
    <div className="space-y-2">
      {/* Selected chips */}
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selected.map((tag) => (
            <span
              key={tag.id || tag.name}
              className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium"
            >
              {tag.name}
              {isPending(tag) && (
                <span className="text-[10px] opacity-60 ml-0.5">new</span>
              )}
              <button
                type="button"
                onClick={() => remove(tag)}
                className="hover:opacity-60 transition-opacity"
                aria-label={`Remove ${tag.name}`}
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Input + dropdown */}
      <div className="relative">
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              if (trimmed && !exactMatch && !alreadySelected) {
                addPending();
              } else if (filteredTags[0]) {
                addExisting(filteredTags[0]);
              }
            }
          }}
          placeholder="Add tag…"
          className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm placeholder:text-muted-foreground outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />

        {open && (filteredTags.length > 0 || showCreate) && (
          <div className="absolute z-10 top-full left-0 right-0 mt-1 rounded-md border bg-background shadow-md overflow-hidden">
            {filteredTags.map((tag) => (
              <button
                key={tag.id}
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault();
                  addExisting(tag);
                }}
                className="flex items-center gap-2.5 w-full px-3 py-2 text-sm text-left hover:bg-muted transition-colors"
              >
                <Tag className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                <span className="truncate">{tag.name}</span>
              </button>
            ))}
            {showCreate && (
              <button
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault();
                  addPending();
                }}
                className="flex items-center gap-2.5 w-full px-3 py-2 text-sm text-left hover:bg-muted transition-colors text-primary"
              >
                <Plus className="h-3.5 w-3.5 shrink-0" />
                <span>Create &ldquo;{trimmed}&rdquo;</span>
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

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
  cover_image_url: string | null;
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
      const res = await fetch(`${apiBaseUrl}/recipes/import?${qs}`, {
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
  onDeleted,
}: {
  open: boolean;
  recipe: Recipe | null;
  onClose: () => void;
  /** Called instead of onClose after a successful delete. Use to navigate away on detail pages. */
  onDeleted?: () => void;
}) {
  const qc = useQueryClient();
  const isEdit = recipe !== null;

  const [tab, setTab] = useState<Tab>("manual");
  const [form, setForm] = useState<FormState>(blankForm());
  const [selectedTags, setSelectedTags] = useState<SelectedTag[]>([]);
  const [visibility, setVisibility] = useState<Visibility>("household");
  const [sharedWith, setSharedWith] = useState<string[]>([]);
  // Ingredients + steps captured from an import (passed along verbatim on save)
  const [importedIngredients, setImportedIngredients] = useState<
    ImportPreview["ingredients"]
  >([]);
  const [importedSteps, setImportedSteps] = useState<ImportPreview["steps"]>([]);
  // Unified cover image URL — set from import preview or direct file upload
  const [coverImageUrl, setCoverImageUrl] = useState<string | null>(null);
  const [uploadingImage, setUploadingImage] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Sync form state whenever the sheet opens/closes
  const [lastOpen, setLastOpen] = useState(false);
  if (open !== lastOpen) {
    setLastOpen(open);
    if (open) {
      setTab("manual");
      setForm(recipe ? formFromRecipe(recipe) : blankForm());
      setSelectedTags(recipe?.tags ?? []);
      setVisibility((recipe?.visibility as Visibility) ?? "household");
      setSharedWith(recipe?.shared_with_user_ids ?? []);
      setImportedIngredients([]);
      setImportedSteps([]);
      setCoverImageUrl(recipe?.cover_image_url ?? null);
      setError(null);
    }
  }

  const { mutateAsync: createRecipe } = $api.useMutation("post", "/recipes");
  const { mutateAsync: updateRecipe } = $api.useMutation("patch", "/recipes/{recipe_id}");
  const { mutateAsync: deleteRecipe } = $api.useMutation("delete", "/recipes/{recipe_id}");
  const { mutateAsync: createTag } = $api.useMutation("post", "/tags");
  const { mutateAsync: addTag } = $api.useMutation("put", "/recipes/{recipe_id}/tags/{tag_id}");
  const { mutateAsync: removeTag } = $api.useMutation("delete", "/recipes/{recipe_id}/tags/{tag_id}");

  function set<K extends keyof FormState>(key: K, val: FormState[K]) {
    setForm((p) => ({ ...p, [key]: val }));
  }

  function handleImported(preview: ImportPreview) {
    setForm(formFromImport(preview));
    setImportedIngredients(preview.ingredients ?? []);
    setImportedSteps(preview.steps ?? []);
    setCoverImageUrl(preview.cover_image_url ?? null);
    setTab("manual"); // switch to form so user can review & edit
  }

  async function handleImageFile(file: File) {
    setUploadingImage(true);
    setError(null);
    try {
      const token = getAccessToken();
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`${apiBaseUrl}/uploads`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: fd,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`);
      }
      const { url } = (await res.json()) as { url: string };
      setCoverImageUrl(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Image upload failed.");
    } finally {
      setUploadingImage(false);
    }
  }

  /** Resolve any pending (new) tags in `selectedTags`, then sync adds/removes against `existingTags`. */
  async function syncTags(recipeId: string, existingTags: ExistingTag[]) {
    const existingIds = new Set(existingTags.map((t) => t.id));
    const selectedIds = new Set<string>();

    // Step 1: ensure every selected tag has a real DB id
    const resolvedTags: ExistingTag[] = await Promise.all(
      selectedTags.map(async (t) => {
        if (!isPending(t)) return t;
        // Create the tag in the DB
        const created = await createTag({ body: { name: t.name } });
        return created as ExistingTag;
      })
    );

    // Step 2: add tags not yet on the recipe
    for (const tag of resolvedTags) {
      selectedIds.add(tag.id);
      if (!existingIds.has(tag.id)) {
        await addTag({ params: { path: { recipe_id: recipeId, tag_id: tag.id } } });
      }
    }

    // Step 3: remove tags that were deselected
    for (const tag of existingTags) {
      if (!selectedIds.has(tag.id)) {
        await removeTag({ params: { path: { recipe_id: recipeId, tag_id: tag.id } } });
      }
    }
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
        visibility,
        shared_with_user_ids: sharedWith,
      };

      if (isEdit) {
        await updateRecipe({
          params: { path: { recipe_id: recipe.id } },
          body: { ...base, cover_image_url: coverImageUrl },
        });
        await syncTags(recipe.id, recipe.tags);
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
        const created = await createRecipe({
          body: {
            ...base,
            cover_image_url: coverImageUrl,
            ingredients,
            steps,
          },
        });
        // Sync tags onto the newly created recipe
        if (selectedTags.length > 0) {
          await syncTags(created.id, []);
        }
      }

      qc.invalidateQueries({ queryKey: ["get", "/recipes"] });
      qc.invalidateQueries({ queryKey: ["get", "/tags"] });
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
    setError(null);
    let succeeded = false;
    try {
      await deleteRecipe({ params: { path: { recipe_id: recipe.id } } });
      succeeded = true;
    } catch {
      setError("Failed to delete recipe.");
    } finally {
      setSaving(false);
    }
    if (!succeeded) return;
    // Post-delete cleanup is intentionally outside the try/catch so errors
    // in cache invalidation or navigation don't show a false "delete failed" message.
    qc.invalidateQueries({ queryKey: ["get", "/recipes"] });
    if (onDeleted) {
      onDeleted();
    } else {
      onClose();
    }
  }

  const hasImportedData =
    importedIngredients.length > 0 || importedSteps.length > 0;

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-md overflow-y-auto flex flex-col gap-0 p-0">
        <SheetHeader className="px-6 py-4 border-b">
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
              {/* Cover image */}
              <div className="space-y-1.5">
                <Label>Cover image</Label>
                {coverImageUrl ? (
                  <div className="relative rounded-lg overflow-hidden bg-muted group">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={resolveMediaUrl(coverImageUrl) ?? ""}
                      alt="Recipe cover"
                      className="w-full h-36 object-cover"
                      onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
                    />
                    {uploadingImage && (
                      <div className="absolute inset-0 bg-background/60 flex items-center justify-center">
                        <Loader2 className="h-5 w-5 animate-spin" />
                      </div>
                    )}
                    <div className="absolute top-2 right-2 flex gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                      <label className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded bg-background/90 border hover:bg-muted transition-colors cursor-pointer">
                        <input
                          type="file"
                          accept="image/jpeg,image/png,image/gif,image/webp"
                          className="sr-only"
                          onChange={(e) => {
                            const f = e.target.files?.[0];
                            if (f) handleImageFile(f);
                            e.target.value = "";
                          }}
                        />
                        Replace
                      </label>
                      <button
                        type="button"
                        onClick={() => setCoverImageUrl(null)}
                        className="inline-flex items-center justify-center h-6 w-6 rounded bg-background/90 border hover:bg-muted transition-colors"
                        aria-label="Remove cover image"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                ) : (
                  <label className="flex flex-col items-center justify-center h-24 rounded-lg border-2 border-dashed border-input hover:bg-muted/40 transition-colors cursor-pointer">
                    <input
                      type="file"
                      accept="image/jpeg,image/png,image/gif,image/webp"
                      className="sr-only"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) handleImageFile(f);
                        e.target.value = "";
                      }}
                    />
                    {uploadingImage ? (
                      <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                    ) : (
                      <>
                        <ImagePlus className="h-5 w-5 text-muted-foreground mb-1" />
                        <span className="text-xs text-muted-foreground">Click to upload image</span>
                      </>
                    )}
                  </label>
                )}
              </div>

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
                <Label>Tags</Label>
                <TagPicker selected={selectedTags} onChange={setSelectedTags} />
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
              <div className="space-y-1.5">
                <Label>Visibility</Label>
                <VisibilityPicker
                  value={visibility}
                  sharedWith={sharedWith}
                  onChange={(v, sw) => { setVisibility(v); setSharedWith(sw); }}
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
