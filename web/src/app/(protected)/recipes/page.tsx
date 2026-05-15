"use client";

import { useState, useMemo, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import { apiClient, resolveMediaUrl } from "@/lib/api/client";
import { useDebounce } from "@/lib/hooks/use-debounce";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { RecipeSheet } from "@/components/recipes/recipe-sheet";
import { usePermissions } from "@/lib/hooks/use-permissions";
import {
  Plus, Loader2, ChefHat, Clock, Search, ChevronLeft, ChevronRight, X,
  Tag, Check,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { components } from "@/lib/api/schema";

const PAGE_SIZE = 24;

type Recipe = components["schemas"]["RecipeResponse"];
type TagSummary = components["schemas"]["TagSummary"];

// ── TagFilter ─────────────────────────────────────────────────────────────────
// Multi-select combobox. Active tags sort to the top; the trigger button shows
// the first selected tag name and a count badge for additional selections.
// Individual tags are deselected by clicking them in the dropdown — there is
// no inline X on the button. A separate clear-all button lives outside.

function TagFilter({
  tags,
  selectedIds,
  onSelect,
}: {
  tags: TagSummary[];
  selectedIds: string[];
  onSelect: (ids: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const selectedSet = new Set(selectedIds);

  // Active tags first, then alphabetical within each group.
  const sorted = [...tags].sort((a, b) => {
    const aActive = selectedSet.has(a.id) ? 0 : 1;
    const bActive = selectedSet.has(b.id) ? 0 : 1;
    if (aActive !== bActive) return aActive - bActive;
    return a.name.localeCompare(b.name);
  });

  const filtered = query
    ? sorted.filter((t) => t.name.toLowerCase().includes(query.toLowerCase()))
    : sorted;

  // Trigger label: first selected tag + overflow count
  const firstSelected = tags.find((t) => t.id === selectedIds[0]);
  const overflowCount = selectedIds.length - 1;

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  // Focus search input when dropdown opens
  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 0);
  }, [open]);

  function handleToggle(tag: TagSummary) {
    const next = selectedSet.has(tag.id)
      ? selectedIds.filter((id) => id !== tag.id)
      : [...selectedIds, tag.id];
    onSelect(next);
  }

  return (
    <div ref={containerRef} className="relative">
      <Button
        variant={selectedIds.length > 0 ? "default" : "outline"}
        size="sm"
        className="h-9 gap-1.5 text-sm"
        onClick={() => setOpen((o) => !o)}
      >
        <Tag className="h-3.5 w-3.5" />
        {selectedIds.length === 0
          ? "Filter"
          : firstSelected?.name}
        {overflowCount > 0 && (
          <span className="ml-0.5 rounded bg-primary-foreground/20 px-1 text-xs font-medium">
            +{overflowCount}
          </span>
        )}
      </Button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 w-56 rounded-md border bg-popover shadow-md">
          <div className="p-2 border-b">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                ref={inputRef}
                className="h-8 pl-8 text-sm"
                placeholder="Search tags…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
          </div>

          <div className="max-h-52 overflow-y-auto p-1">
            {filtered.length === 0 && (
              <p className="px-2 py-3 text-xs text-center text-muted-foreground">
                No tags found.
              </p>
            )}
            {filtered.map((tag) => (
              <button
                key={tag.id}
                type="button"
                className="w-full flex items-center gap-2 px-2 py-1.5 rounded-sm text-sm hover:bg-accent hover:text-accent-foreground text-left"
                onClick={() => handleToggle(tag)}
              >
                <Check
                  className={cn(
                    "h-3.5 w-3.5 shrink-0",
                    selectedSet.has(tag.id) ? "opacity-100" : "opacity-0",
                  )}
                />
                <span className="truncate">{tag.name}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── RecipeCard ────────────────────────────────────────────────────────────────

function formatTime(mins: number | null): string | null {
  if (!mins) return null;
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

function RecipeCard({
  recipe,
  onClick,
  onPrefetch,
}: {
  recipe: Recipe;
  onClick: () => void;
  onPrefetch: () => void;
}) {
  const totalMins =
    (recipe.prep_time_minutes ?? 0) + (recipe.cook_time_minutes ?? 0);
  const timeStr = formatTime(totalMins || null);

  return (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={onPrefetch}
      className="w-full flex flex-col text-left border rounded-lg bg-card hover:bg-muted/30 transition-colors cursor-pointer group overflow-hidden"
    >
      <div className="w-full h-36 overflow-hidden bg-muted shrink-0">
        {recipe.cover_image_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={resolveMediaUrl(recipe.cover_image_url) ?? ""}
            alt={recipe.name}
            className="w-full h-full object-cover object-center group-hover:scale-[1.02] transition-transform duration-300"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <ChefHat className="h-10 w-10 text-muted-foreground/20" />
          </div>
        )}
      </div>

      <div className="p-4 grow flex flex-col">
        <span className="font-medium text-sm leading-snug">{recipe.name}</span>
        {recipe.description && (
          <p className="mt-1 text-xs text-muted-foreground line-clamp-2">
            {recipe.description}
          </p>
        )}
        <div className="mt-auto">
          <div className="flex items-center gap-3 mt-2 text-xs text-muted-foreground">
            {timeStr && (
              <span className="flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {timeStr}
              </span>
            )}
            {recipe.servings && <span>{recipe.servings} servings</span>}
          </div>
          {recipe.tags.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {recipe.tags.map((tag) => (
                <span
                  key={tag.id}
                  className="text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium"
                >
                  {tag.name}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </button>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function RecipesPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { can } = usePermissions();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [selectedTagIds, setSelectedTagIds] = useState<string[]>([]);

  const debouncedSearch = useDebounce(search, 300);

  // All household tags for the filter combobox
  const { data: tagsData } = $api.useQuery("get", "/tags", {
    params: { query: { limit: 100 } },
  });

  // Unfiltered recipe list — used to surface tags that exist on recipes even
  // if they haven't been created as standalone tags via /tags
  const { data: allRecipesData } = $api.useQuery("get", "/recipes", {
    params: { query: { limit: 200 } as any },
  });

  const availableTags: TagSummary[] = useMemo(() => {
    const map = new Map<string, TagSummary>();
    for (const r of allRecipesData?.items ?? []) {
      for (const t of r.tags) map.set(t.id, t);
    }
    for (const t of (tagsData?.items ?? []) as TagSummary[]) {
      map.set(t.id, t);
    }
    return Array.from(map.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [tagsData, allRecipesData]);

  // Current page of recipes — server-side search, tag filter, pagination
  const { data, isLoading, isError } = $api.useQuery("get", "/recipes", {
    params: {
      query: {
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
        ...(debouncedSearch ? { search: debouncedSearch } : {}),
        ...(selectedTagIds.length > 0 ? { tag_ids: selectedTagIds } : {}),
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
      } as any,
    },
  });

  const recipes = data?.items ?? [];
  const total = data?.total ?? 0;
  const pageCount = Math.ceil(total / PAGE_SIZE);

  function handleSearchChange(value: string) {
    setSearch(value);
    setPage(0);
  }

  function handleTagSelect(tagIds: string[]) {
    setSelectedTagIds(tagIds);
    setPage(0);
  }

  function handlePrefetch(recipe: Recipe) {
    router.prefetch(`/recipes/${recipe.id}`);
    queryClient.prefetchQuery({
      queryKey: ["get", "/recipes/{recipe_id}", { params: { path: { recipe_id: recipe.id } } }],
      queryFn: () =>
        apiClient
          .GET("/recipes/{recipe_id}", { params: { path: { recipe_id: recipe.id } } })
          .then((r) => {
            if (r.error) throw r.error;
            return r.data!;
          }),
      staleTime: 30_000,
    });
  }

  const hasFilters = !!debouncedSearch || selectedTagIds.length > 0;

  return (
    <div className="p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <ChefHat className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-xl font-semibold">Recipes</h1>
        </div>
        {can("recipes", "create") && (
          <Button size="sm" onClick={() => setSheetOpen(true)}>
            <Plus className="h-4 w-4 mr-1" />
            New
          </Button>
        )}
      </div>

      {/* Search + tag filter — single row, minimal vertical footprint */}
      <div className="flex items-center gap-2 mb-5">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            className="pl-9 h-9"
            placeholder="Search recipes…"
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
          />
        </div>
        {availableTags.length > 0 && (
          <TagFilter
            tags={availableTags}
            selectedIds={selectedTagIds}
            onSelect={handleTagSelect}
          />
        )}
        {hasFilters && (
          <Button
            variant="secondary"
            size="sm"
            className="h-9 gap-1.5 text-sm shrink-0"
            onClick={() => { setSearch(""); setSelectedTagIds([]); setPage(0); }}
          >
            <X className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Clear</span>
          </Button>
        )}
      </div>

      {/* States */}
      {isLoading && (
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading…
        </div>
      )}
      {isError && (
        <p className="py-8 text-sm text-destructive">Failed to load recipes.</p>
      )}
      {!isLoading && !isError && recipes.length === 0 && (
        <div className="py-12 text-center">
          <ChefHat className="h-8 w-8 text-muted-foreground/30 mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">
            {hasFilters ? "No recipes match those filters." : "No recipes yet."}
          </p>
          {!hasFilters && can("recipes", "create") && (
            <Button
              variant="outline"
              size="sm"
              className="mt-4"
              onClick={() => setSheetOpen(true)}
            >
              <Plus className="h-4 w-4 mr-1" />
              Add one
            </Button>
          )}
        </div>
      )}

      {/* Recipe grid */}
      {recipes.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {recipes.map((r) => (
            <RecipeCard
              key={r.id}
              recipe={r}
              onClick={() => router.push(`/recipes/${r.id}`)}
              onPrefetch={() => handlePrefetch(r)}
            />
          ))}
        </div>
      )}

      {/* Pagination */}
      {pageCount > 1 && (
        <div className="flex items-center justify-between mt-6 text-sm text-muted-foreground">
          <span>
            {total} recipe{total !== 1 ? "s" : ""}
            {hasFilters ? " matching" : ""} · page {page + 1} of {pageCount}
          </span>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              className="h-8 w-8 p-0"
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            {Array.from({ length: pageCount }, (_, i) => i)
              .filter((i) => Math.abs(i - page) <= 2)
              .map((i) => (
                <Button
                  key={i}
                  variant={i === page ? "default" : "ghost"}
                  size="sm"
                  className="h-8 w-8 p-0 text-xs"
                  onClick={() => setPage(i)}
                >
                  {i + 1}
                </Button>
              ))}
            <Button
              variant="ghost"
              size="sm"
              className="h-8 w-8 p-0"
              disabled={page >= pageCount - 1}
              onClick={() => setPage((p) => p + 1)}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}

      <RecipeSheet
        open={sheetOpen}
        recipe={null}
        onClose={() => setSheetOpen(false)}
      />
    </div>
  );
}
