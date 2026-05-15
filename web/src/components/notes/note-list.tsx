"use client";

import { useState, useCallback, useRef, useMemo } from "react";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import { apiBaseUrl } from "@/lib/api/client";
import { getAccessToken } from "@/lib/auth/token";
import { NoteRow } from "./note-row";
import { TagMultiSelect } from "./tag-multi-select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Plus, Search, Loader2, X, Trash2 } from "lucide-react";
import type { components } from "@/lib/api/schema";

type NoteSummary = components["schemas"]["NoteSummary"];
type TagResponse  = components["schemas"]["TagResponse"];

interface NoteListProps {
  selectedId: string | null;
  onSelect: (note: NoteSummary) => void;
  onNewNote: () => void;
  onAllDeleted?: () => void;
  /**
   * When provided, fetches notes belonging to these collection IDs instead of
   * the default (uncollected-only) view. Pass an empty array or undefined to
   * show uncollected notes.
   */
  collectionIds?: string[];
}

export function NoteList({ selectedId, onSelect, onNewNote, onAllDeleted, collectionIds }: NoteListProps) {
  const [search, setSearch] = useState("");
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing,     setClearing]     = useState(false);
  const qc = useQueryClient();

  async function handleDeleteAll() {
    setClearing(true);
    try {
      const token = getAccessToken();
      await fetch(`${apiBaseUrl}/notes`, {
        method: "DELETE",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      qc.invalidateQueries({ queryKey: ["get", "/notes"] });
      onAllDeleted?.();
    } finally {
      setClearing(false);
      setConfirmClear(false);
    }
  }
  const [activeTagIds, setActiveTagIds] = useState<string[]>([]);
  const [tagMode, setTagMode] = useState<"any" | "all">("any");
  const searchRef = useRef<HTMLInputElement>(null);

  // Debounced search — API handles text search
  const [debouncedQ, setDebouncedQ] = useState("");
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleSearchChange = useCallback((val: string) => {
    setSearch(val);
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => setDebouncedQ(val), 300);
  }, []);

  // Fetch notes — tag filtering is client-side; collection filter is server-side.
  // When collectionIds is provided: filter to those collections.
  // Default (no prop): show uncollected notes only (the API's default behaviour).
  const { data, isLoading, isError } = $api.useQuery("get", "/notes", {
    params: {
      query: {
        q: debouncedQ || undefined,
        limit: 500,
        // Pass collection_ids when the caller has toggled specific collections.
        // When undefined, the API defaults to returning uncollected notes.
        ...(collectionIds && collectionIds.length > 0
          ? { collection_ids: collectionIds }
          : {}),
      },
    },
  });

  const { data: tagsData } = $api.useQuery("get", "/tags", {
    params: { query: { limit: 100 } },
  });

  const tags: TagResponse[] = tagsData?.items ?? [];

  // Per-tag note counts (for the dropdown labels)
  const tagCountQueries = useQueries({
    queries: tags.map((tag) => ({
      queryKey: ["notes-tag-count", tag.id],
      queryFn: async (): Promise<number> => {
        const token = getAccessToken();
        const res = await fetch(`${apiBaseUrl}/notes?tag_id=${tag.id}&limit=1`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        const d = await res.json();
        return d.total ?? 0;
      },
      staleTime: 60_000,
      enabled: tags.length > 0,
    })),
  });

  const tagCounts = new Map(
    tags.map((tag, i) => [tag.id, tagCountQueries[i]?.data ?? null])
  );

  // Only show tags that actually appear on at least one note.
  // While a count is still loading (null) we keep the tag visible to avoid flicker.
  // Once all counts are known, tags with count 0 are hidden (e.g. recipe-only tags).
  const noteTags = useMemo(
    () => tags.filter((tag) => { const c = tagCounts.get(tag.id); return c == null || c > 0; }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tags, tagCounts]  // tagCounts is a new Map each render, values stabilise quickly
  );

  // Build per-tag note ID sets from dedicated queries
  const tagNoteIdQueries = useQueries({
    queries: tags.map((tag) => ({
      queryKey: ["notes-by-tag-ids", tag.id],
      queryFn: async (): Promise<string[]> => {
        const token = getAccessToken();
        const res = await fetch(`${apiBaseUrl}/notes?tag_id=${tag.id}&limit=500`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        const d = await res.json();
        return (d.items ?? []).map((n: { id: string }) => n.id);
      },
      staleTime: 60_000,
      enabled: tags.length > 0,
    })),
  });

  // Map tagId → Set<noteId>
  const tagNoteIdMap = useMemo(() => {
    const map = new Map<string, Set<string>>();
    tags.forEach((tag, i) => {
      const ids = tagNoteIdQueries[i]?.data;
      if (ids) map.set(tag.id, new Set(ids));
    });
    return map;
  }, [tags, tagNoteIdQueries]);

  // Apply multi-tag filter: OR (any) or AND (all)
  const displayedNotes = useMemo(() => {
    const all = data?.items ?? [];
    if (activeTagIds.length === 0) return all;
    const fn = tagMode === "all"
      ? (note: NoteSummary) => activeTagIds.every((id) => tagNoteIdMap.get(id)?.has(note.id))
      : (note: NoteSummary) => activeTagIds.some((id)  => tagNoteIdMap.get(id)?.has(note.id));
    return all.filter(fn);
  }, [data, activeTagIds, tagMode, tagNoteIdMap]);

  const totalShown = displayedNotes.length;

  return (
    <div className="flex flex-col h-full">

      {/* ── Header ─────────────────────────────────────────────────── */}
      <div className="px-3 pt-3 pb-2 shrink-0 space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider px-1">
            Notes
          </span>
          <div className="flex items-center gap-0.5">
            {(data?.items?.length ?? 0) > 0 && (
              confirmClear ? (
                <>
                  <span className="text-[10px] text-muted-foreground mr-1">Delete all?</span>
                  <Button
                    size="sm" variant="destructive"
                    onClick={handleDeleteAll}
                    disabled={clearing}
                    className="h-6 text-[10px] px-1.5"
                  >
                    {clearing ? <Loader2 className="h-2.5 w-2.5 animate-spin" /> : "Yes"}
                  </Button>
                  <Button
                    size="sm" variant="ghost"
                    onClick={() => setConfirmClear(false)}
                    className="h-6 text-[10px] px-1.5"
                  >
                    No
                  </Button>
                </>
              ) : (
                <Button
                  size="sm" variant="ghost"
                  onClick={() => setConfirmClear(true)}
                  className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                  title="Delete all notes"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              )
            )}
            <Button
              size="sm"
              variant="ghost"
              className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
              onClick={onNewNote}
              title="New note"
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
          <Input
            ref={searchRef}
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            placeholder="Search notes…"
            className="h-7 pl-7 pr-7 text-xs bg-muted/50 border-0 focus-visible:ring-1"
          />
          {search && (
            <button
              type="button"
              onClick={() => { setSearch(""); setDebouncedQ(""); }}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>

        {/* Tag multi-select — only tags that appear on at least one note */}
        {noteTags.length > 0 && (
          <TagMultiSelect
            tags={noteTags}
            counts={tagCounts}
            selected={activeTagIds}
            onChange={setActiveTagIds}
            mode={tagMode}
            onModeChange={setTagMode}
          />
        )}
      </div>

      {/* ── Status line ────────────────────────────────────────────── */}
      {!isLoading && data && (
        <div className="px-4 pb-1 shrink-0">
          <span className="text-[11px] text-muted-foreground">
            {totalShown} {totalShown === 1 ? "note" : "notes"}
            {activeTagIds.length > 0 && ` · ${activeTagIds.length} tag${activeTagIds.length > 1 ? `s (${tagMode})` : ""}`}
            {debouncedQ ? ` matching "${debouncedQ}"` : ""}
          </span>
        </div>
      )}

      {/* ── List ───────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-1.5 pb-2 space-y-0.5">
        {isLoading && (
          <div className="flex items-center gap-2 px-3 py-4 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Loading…
          </div>
        )}

        {isError && (
          <p className="px-3 py-4 text-xs text-destructive">Failed to load notes.</p>
        )}

        {!isLoading && !isError && displayedNotes.length === 0 && (
          <div className="px-3 py-6 text-center">
            <p className="text-xs text-muted-foreground">
              {debouncedQ || activeTagIds.length > 0
                ? "No matching notes."
                : "No notes yet."}
            </p>
            {!debouncedQ && activeTagIds.length === 0 && (
              <button
                type="button"
                onClick={onNewNote}
                className="mt-2 text-xs text-primary hover:underline"
              >
                Create one
              </button>
            )}
          </div>
        )}

        {!isLoading && !isError && displayedNotes.map((note) => (
          <NoteRow
            key={note.id}
            note={note}
            selected={note.id === selectedId}
            onSelect={onSelect}
          />
        ))}
      </div>
    </div>
  );
}
