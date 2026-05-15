"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useSegmentId } from "@/lib/hooks/use-segment-id";
import { $api } from "@/lib/api/query";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
  ChevronLeft, Loader2, Plus, Trash2, ImagePlus, X, Tag,
} from "lucide-react";
import { getAccessToken } from "@/lib/auth/token";
import type { components } from "@/lib/api/schema";
import { resolveMediaUrl, apiBaseUrl } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/context";
import { usePermissions } from "@/lib/hooks/use-permissions";

type ExistingTag = components["schemas"]["TagSummary"];
type PendingTag = { id: ""; name: string; color: null };
type SelectedTag = ExistingTag | PendingTag;
function isPending(t: SelectedTag): t is PendingTag { return t.id === ""; }

// ── Helpers ───────────────────────────────────────────────────────────────────

function useDebounced(value: string, delay: number) {
  const [d, setD] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setD(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return d;
}

/** Convert a stored decimal quantity back to a human-readable string for editing.
 *  e.g. 0.3333... → "1/3",  1.5 → "1 1/2",  2 → "2" */
function quantityToString(qty: number | string | null | undefined): string {
  if (qty == null) return "";
  const n = Number(qty);
  if (isNaN(n) || n <= 0) return "";
  const FRACS: [number, string][] = [
    [1 / 8, "1/8"], [1 / 4, "1/4"], [1 / 3, "1/3"], [3 / 8, "3/8"],
    [1 / 2, "1/2"], [5 / 8, "5/8"], [2 / 3, "2/3"], [3 / 4, "3/4"], [7 / 8, "7/8"],
  ];
  const EPS = 0.02;
  const whole = Math.floor(n);
  const frac = n - whole;
  if (frac < EPS) return String(whole);
  const match = FRACS.find(([v]) => Math.abs(frac - v) < EPS);
  if (match) return whole > 0 ? `${whole} ${match[1]}` : match[1];
  return n.toFixed(2).replace(/\.?0+$/, "");
}

/** Parse a quantity string typed by the user.
 *  Supports: "1/3", "1 1/2", "2.5", "3" — returns null if unparseable. */
function parseQuantityInput(s: string): number | null {
  const raw = s.trim();
  if (!raw) return null;
  let total = 0;
  for (const part of raw.split(/\s+/)) {
    if (part.includes("/")) {
      const [a, b] = part.split("/");
      const n = parseFloat(a), d = parseFloat(b);
      if (isNaN(n) || isNaN(d) || d === 0) return null;
      total += n / d;
    } else {
      const n = parseFloat(part);
      if (isNaN(n)) return null;
      total += n;
    }
  }
  return total > 0 ? total : null;
}

// ── TagPicker ─────────────────────────────────────────────────────────────────

function TagPicker({ selected, onChange }: {
  selected: SelectedTag[];
  onChange: (tags: SelectedTag[]) => void;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const dq = useDebounced(query.trim(), 200);

  const { data } = $api.useQuery(
    "get", "/tags",
    { params: { query: { search: dq || undefined, limit: 10 } } },
    { enabled: open },
  );
  const allTags = data?.items ?? [];
  const selectedIds = new Set(selected.map((t) => t.id).filter(Boolean));
  const filteredTags = allTags.filter((t) => !selectedIds.has(t.id));
  const trimmed = query.trim();
  const exactMatch = allTags.some((t) => t.name.toLowerCase() === trimmed.toLowerCase());
  const alreadySelected = selected.some((t) => t.name.toLowerCase() === trimmed.toLowerCase());
  const showCreate = trimmed && !exactMatch && !alreadySelected;

  function addTag(tag: ExistingTag) {
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

  return (
    <div className="space-y-2">
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selected.map((tag) => (
            <span
              key={tag.id || tag.name}
              className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium"
            >
              {tag.name}
              {isPending(tag) && <span className="text-[10px] opacity-60 ml-0.5">new</span>}
              <button
                type="button"
                onClick={() => onChange(selected.filter((t) => t.id ? t.id !== tag.id : t.name !== tag.name))}
                className="hover:opacity-60 transition-opacity"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="relative">
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              if (trimmed && !exactMatch && !alreadySelected) addPending();
              else if (filteredTags[0]) addTag(filteredTags[0]);
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
                onMouseDown={(e) => { e.preventDefault(); addTag(tag); }}
                className="flex items-center gap-2.5 w-full px-3 py-2 text-sm text-left hover:bg-muted transition-colors"
              >
                <Tag className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                <span className="truncate">{tag.name}</span>
              </button>
            ))}
            {showCreate && (
              <button
                type="button"
                onMouseDown={(e) => { e.preventDefault(); addPending(); }}
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

// ── Row types ─────────────────────────────────────────────────────────────────

type IngRow = { key: string; quantity: string; unit: string; name: string; notes: string; };
type StepRow = { key: string; instruction: string; notes: string; };

function newIngRow(): IngRow {
  return { key: crypto.randomUUID(), quantity: "", unit: "", name: "", notes: "" };
}
function newStepRow(): StepRow {
  return { key: crypto.randomUUID(), instruction: "", notes: "" };
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function RecipeEditPage() {
  const id = useSegmentId();
  const router = useRouter();
  const qc = useQueryClient();
  const { user } = useAuth();
  const { can } = usePermissions();

  const { data: recipe, isLoading, isError } = $api.useQuery(
    "get", "/recipes/{recipe_id}",
    { params: { path: { recipe_id: id } } },
  );

  const [form, setForm] = useState({
    name: "", description: "", source_url: "",
    prep_time_minutes: "", cook_time_minutes: "", servings: "", notes: "",
  });
  const [coverImageUrl, setCoverImageUrl] = useState<string | null>(null);
  const [uploadingImage, setUploadingImage] = useState(false);
  const [ingredients, setIngredients] = useState<IngRow[]>([newIngRow()]);
  const [steps, setSteps] = useState<StepRow[]>([newStepRow()]);
  const [selectedTags, setSelectedTags] = useState<SelectedTag[]>([]);
  const [initialized, setInitialized] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { mutateAsync: updateRecipe } = $api.useMutation("patch", "/recipes/{recipe_id}");
  const { mutateAsync: deleteRecipe } = $api.useMutation("delete", "/recipes/{recipe_id}");
  const { mutateAsync: createTag } = $api.useMutation("post", "/tags");
  const { mutateAsync: addTag } = $api.useMutation("put", "/recipes/{recipe_id}/tags/{tag_id}");
  const { mutateAsync: removeTag } = $api.useMutation("delete", "/recipes/{recipe_id}/tags/{tag_id}");

  // Initialise form once the recipe loads
  useEffect(() => {
    if (!recipe || initialized) return;
    setForm({
      name: recipe.name,
      description: recipe.description ?? "",
      source_url: recipe.source_url ?? "",
      prep_time_minutes: recipe.prep_time_minutes ? String(recipe.prep_time_minutes) : "",
      cook_time_minutes: recipe.cook_time_minutes ? String(recipe.cook_time_minutes) : "",
      servings: recipe.servings ? String(recipe.servings) : "",
      notes: recipe.notes ?? "",
    });
    setCoverImageUrl(recipe.cover_image_url ?? null);
    setIngredients(
      recipe.ingredients.length
        ? recipe.ingredients.map((ing) => ({
            key: ing.id,
            quantity: quantityToString(ing.quantity),
            unit: ing.unit ?? "",
            name: ing.name,
            notes: ing.notes ?? "",
          }))
        : [newIngRow()],
    );
    setSteps(
      recipe.steps.length
        ? recipe.steps.map((s) => ({
            key: s.id,
            instruction: s.instruction,
            notes: s.notes ?? "",
          }))
        : [newStepRow()],
    );
    setSelectedTags(recipe.tags);
    setInitialized(true);
  }, [recipe, initialized]);

  function setField(key: keyof typeof form, val: string) {
    setForm((p) => ({ ...p, [key]: val }));
  }

  function updateIng(i: number, patch: Partial<IngRow>) {
    setIngredients((prev) => prev.map((r, j) => j === i ? { ...r, ...patch } : r));
  }
  function updateStep(i: number, patch: Partial<StepRow>) {
    setSteps((prev) => prev.map((r, j) => j === i ? { ...r, ...patch } : r));
  }

  async function handleImageFile(file: File) {
    setUploadingImage(true);
    try {
      const token = getAccessToken();
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`${apiBaseUrl}/uploads`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: fd,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const { url } = (await res.json()) as { url: string };
      setCoverImageUrl(url);
    } catch {
      setError("Image upload failed.");
    } finally {
      setUploadingImage(false);
    }
  }

  async function syncTags(existingTags: ExistingTag[]) {
    const existingIds = new Set(existingTags.map((t) => t.id));
    const selectedIds = new Set<string>();
    const resolved: ExistingTag[] = await Promise.all(
      selectedTags.map(async (t) => {
        if (!isPending(t)) return t;
        return (await createTag({ body: { name: t.name } })) as ExistingTag;
      }),
    );
    for (const tag of resolved) {
      selectedIds.add(tag.id);
      if (!existingIds.has(tag.id)) {
        await addTag({ params: { path: { recipe_id: id, tag_id: tag.id } } });
      }
    }
    for (const tag of existingTags) {
      if (!selectedIds.has(tag.id)) {
        await removeTag({ params: { path: { recipe_id: id, tag_id: tag.id } } });
      }
    }
  }

  async function handleSave() {
    if (!form.name.trim()) { setError("Name is required."); return; }
    setSaving(true);
    setError(null);
    try {
      await updateRecipe({
        params: { path: { recipe_id: id } },
        body: {
          name: form.name.trim(),
          description: form.description.trim() || null,
          cover_image_url: coverImageUrl,
          source_url: form.source_url.trim() || null,
          prep_time_minutes: form.prep_time_minutes ? Number(form.prep_time_minutes) : null,
          cook_time_minutes: form.cook_time_minutes ? Number(form.cook_time_minutes) : null,
          servings: form.servings ? Number(form.servings) : null,
          notes: form.notes.trim() || null,
          ingredients: ingredients
            .filter((r) => r.name.trim())
            .map((r, i) => ({
              name: r.name.trim(),
              quantity: parseQuantityInput(r.quantity),
              unit: r.unit.trim() || null,
              notes: r.notes.trim() || null,
              sort_order: i,
            })),
          steps: steps
            .filter((r) => r.instruction.trim())
            .map((r, i) => ({
              step_number: i + 1,
              instruction: r.instruction.trim(),
              notes: r.notes.trim() || null,
            })),
        },
      });
      await syncTags(recipe?.tags ?? []);
      qc.invalidateQueries({ queryKey: ["get", "/recipes"] });
      qc.invalidateQueries({ queryKey: ["get", "/recipes/{recipe_id}"] });
      router.push(`/recipes/${id}`);
    } catch {
      setError("Something went wrong. Please try again.");
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!confirm("Delete this recipe? This cannot be undone.")) return;
    setDeleting(true);
    try {
      await deleteRecipe({ params: { path: { recipe_id: id } } });
      qc.invalidateQueries({ queryKey: ["get", "/recipes"] });
      router.push("/recipes");
    } catch {
      setError("Failed to delete recipe.");
      setDeleting(false);
    }
  }

  if (isLoading) return (
    <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" />Loading…
    </div>
  );
  if (isError || !recipe) return (
    <p className="p-8 text-sm text-destructive">Recipe not found.</p>
  );

  const busy = saving || deleting || uploadingImage;
  const isOwnItem = !recipe || recipe.created_by_user_id === (user as { id?: string } | null)?.id;
  const canManageThis = isOwnItem || can("recipes", "manage_others");

  return (
    <div className="page-content pb-16">
      {/* Back */}
      <Button
        variant="ghost" size="sm"
        className="mb-5 -ml-1.5 h-7 px-1.5 gap-1 text-xs text-muted-foreground hover:text-foreground"
        onClick={() => router.push(`/recipes/${id}`)}
      >
        <ChevronLeft className="h-3.5 w-3.5" />Back to recipe
      </Button>

      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-xl font-semibold">Edit recipe</h1>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => router.push(`/recipes/${id}`)} disabled={busy}>
            Cancel
          </Button>
          {!canManageThis ? (
            <span className="text-xs text-muted-foreground">View only</span>
          ) : (
            <Button size="sm" onClick={handleSave} disabled={busy}>
              {saving && <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />}
              Save
            </Button>
          )}
        </div>
      </div>

      {error && <p className="mb-5 text-sm text-destructive">{error}</p>}

      <div className="space-y-8">

        {/* ── Cover image ───────────────────────────────────────────────────── */}
        <div className="space-y-1.5">
          <Label>Cover image</Label>
          {coverImageUrl ? (
            <div className="relative rounded-xl overflow-hidden bg-muted group">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={resolveMediaUrl(coverImageUrl) ?? ""}
                alt="Cover"
                className="w-full h-48 object-cover"
                onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
              />
              {uploadingImage && (
                <div className="absolute inset-0 bg-background/60 flex items-center justify-center">
                  <Loader2 className="h-5 w-5 animate-spin" />
                </div>
              )}
              <div className="absolute top-3 right-3 flex gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                <label className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-md bg-background/90 border hover:bg-muted cursor-pointer transition-colors">
                  <input type="file" accept="image/jpeg,image/png,image/gif,image/webp" className="sr-only"
                    onChange={(e) => { const f = e.target.files?.[0]; if (f) handleImageFile(f); e.target.value = ""; }} />
                  Replace
                </label>
                <button type="button" onClick={() => setCoverImageUrl(null)}
                  className="inline-flex items-center justify-center h-7 w-7 rounded-md bg-background/90 border hover:bg-muted transition-colors"
                  aria-label="Remove cover image">
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ) : (
            <label className="flex flex-col items-center justify-center h-28 rounded-xl border-2 border-dashed border-input hover:bg-muted/40 cursor-pointer transition-colors">
              <input type="file" accept="image/jpeg,image/png,image/gif,image/webp" className="sr-only"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) handleImageFile(f); e.target.value = ""; }} />
              {uploadingImage
                ? <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                : <>
                    <ImagePlus className="h-5 w-5 text-muted-foreground mb-1.5" />
                    <span className="text-xs text-muted-foreground">Click to upload image</span>
                  </>
              }
            </label>
          )}
        </div>

        {/* ── Metadata ──────────────────────────────────────────────────────── */}
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="e-name">Name</Label>
            <Input id="e-name" value={form.name} onChange={(e) => setField("name", e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="e-desc">Description</Label>
            <Textarea id="e-desc" value={form.description} rows={2}
              onChange={(e) => setField("description", e.target.value)}
              placeholder="Short description…" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="e-url">Source URL</Label>
            <Input id="e-url" type="url" value={form.source_url}
              onChange={(e) => setField("source_url", e.target.value)}
              placeholder="https://…" />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="e-prep">Prep (min)</Label>
              <Input id="e-prep" type="number" min="0" value={form.prep_time_minutes}
                onChange={(e) => setField("prep_time_minutes", e.target.value)} placeholder="15" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="e-cook">Cook (min)</Label>
              <Input id="e-cook" type="number" min="0" value={form.cook_time_minutes}
                onChange={(e) => setField("cook_time_minutes", e.target.value)} placeholder="30" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="e-serv">Servings</Label>
              <Input id="e-serv" type="number" min="1" value={form.servings}
                onChange={(e) => setField("servings", e.target.value)} placeholder="4" />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Tags</Label>
            <TagPicker selected={selectedTags} onChange={setSelectedTags} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="e-notes">Notes</Label>
            <Textarea id="e-notes" value={form.notes} rows={3}
              onChange={(e) => setField("notes", e.target.value)}
              placeholder="Tips, substitutions, variations…" />
          </div>
        </div>

        {/* ── Ingredients ───────────────────────────────────────────────────── */}
        <div>
          <h2 className="text-base font-semibold mb-1">Ingredients</h2>
          <p className="text-xs text-muted-foreground mb-3">
            Quantity supports fractions — type <span className="font-mono">1/3</span>, <span className="font-mono">1 1/2</span>, or decimals.
          </p>
          <div className="space-y-2">
            {/* Column headers */}
            <div className="flex gap-2 items-center px-0.5">
              <span className="w-20 shrink-0 text-xs text-muted-foreground">Qty</span>
              <span className="w-24 shrink-0 text-xs text-muted-foreground">Unit</span>
              <span className="flex-1 text-xs text-muted-foreground">Ingredient</span>
              <span className="w-9 shrink-0" />
            </div>
            {ingredients.map((row, i) => (
              <div key={row.key} className="flex gap-2 items-center">
                <Input
                  className="w-20 shrink-0"
                  value={row.quantity}
                  onChange={(e) => updateIng(i, { quantity: e.target.value })}
                  placeholder="1/2"
                />
                <Input
                  className="w-24 shrink-0"
                  value={row.unit}
                  onChange={(e) => updateIng(i, { unit: e.target.value })}
                  placeholder="cup"
                />
                <Input
                  className="flex-1 min-w-0"
                  value={row.name}
                  onChange={(e) => updateIng(i, { name: e.target.value })}
                  placeholder="e.g. all-purpose flour"
                />
                <button
                  type="button"
                  onClick={() => setIngredients((prev) => prev.filter((_, j) => j !== i))}
                  className="shrink-0 h-9 w-9 flex items-center justify-center rounded-md text-muted-foreground hover:text-destructive hover:bg-muted transition-colors"
                  aria-label="Remove ingredient"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
          <Button type="button" variant="outline" size="sm" className="mt-3"
            onClick={() => setIngredients((prev) => [...prev, newIngRow()])}>
            <Plus className="h-3.5 w-3.5 mr-1.5" />Add ingredient
          </Button>
        </div>

        {/* ── Steps ─────────────────────────────────────────────────────────── */}
        <div>
          <h2 className="text-base font-semibold mb-3">Instructions</h2>
          <div className="space-y-3">
            {steps.map((row, i) => (
              <div key={row.key} className="flex gap-3 items-start">
                <span className="flex-none w-6 h-6 rounded-full bg-muted flex items-center justify-center text-xs font-semibold text-muted-foreground mt-2.5">
                  {i + 1}
                </span>
                <Textarea
                  className="flex-1 min-w-0 resize-none"
                  rows={2}
                  value={row.instruction}
                  onChange={(e) => updateStep(i, { instruction: e.target.value })}
                  placeholder={`Step ${i + 1}…`}
                />
                <button
                  type="button"
                  onClick={() => setSteps((prev) => prev.filter((_, j) => j !== i))}
                  className="shrink-0 h-9 w-9 flex items-center justify-center rounded-md text-muted-foreground hover:text-destructive hover:bg-muted mt-0.5 transition-colors"
                  aria-label="Remove step"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
          <Button type="button" variant="outline" size="sm" className="mt-3"
            onClick={() => setSteps((prev) => [...prev, newStepRow()])}>
            <Plus className="h-3.5 w-3.5 mr-1.5" />Add step
          </Button>
        </div>

        {/* ── Danger zone ───────────────────────────────────────────────────── */}
        {canManageThis && (
          <div className="pt-4 border-t">
            <Button
              type="button" variant="ghost" size="sm"
              className="text-destructive hover:text-destructive hover:bg-destructive/10"
              onClick={handleDelete}
              disabled={busy}
            >
              {deleting && <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />}
              Delete recipe
            </Button>
          </div>
        )}

      </div>
    </div>
  );
}
