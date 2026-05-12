"use client";

import { useEffect, useCallback, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import { getAccessToken } from "@/lib/auth/token";
import { NoteList } from "@/components/notes/note-list";
import { NoteEditor } from "@/components/notes/note-editor";
import { useResizablePanel } from "@/lib/hooks/use-resizable-panel";
import { useFocusMode } from "@/lib/focus/context";
import { FocusToggle } from "@/components/focus/focus-toggle";
import { Button } from "@/components/ui/button";
import { Loader2, BookOpen, FileText, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { components } from "@/lib/api/schema";

type NoteSummary = components["schemas"]["NoteSummary"];

/** Sentinel value: user clicked "New" but hasn't saved yet */
const NEW_ITEM_ID = "__new__";

export default function CollectionPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const { focused } = useFocusMode();

  const [selectedId, setSelectedId] = useState<string | null>(null);

  // ── Fetch collection metadata ─────────────────────────────────────────────
  const { data: collection, isLoading: collectionLoading, isError: collectionError } =
    $api.useQuery("get", "/collections/{collection_id}", {
      params: { path: { collection_id: id } },
    });

  // ── Auto-create today's entry if auto_create_rule is set ─────────────────
  const ensureTodayMutation = $api.useMutation(
    "post",
    "/collections/{collection_id}/ensure-today",
  );

  useEffect(() => {
    if (!collection?.auto_create_rule) return;

    ensureTodayMutation.mutateAsync({
      params: { path: { collection_id: id } },
    }).then((result) => {
      if (result.created || selectedId === null) {
        // Jump to today's entry on first load or when freshly created
        setSelectedId(result.item_id);
      }
      // Invalidate the notes/documents list so the new entry appears
      if (collection.domain === "notes") {
        qc.invalidateQueries({ queryKey: ["get", "/notes"] });
      } else {
        qc.invalidateQueries({ queryKey: ["get", "/documents"] });
      }
    }).catch(() => {
      // Silently ignore — ensure-today is best-effort
    });
    // Only run once on mount / when collection first loads
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collection?.id]);

  const { width, startResize } = useResizablePanel({
    defaultWidth: 260,
    minWidth: 180,
    maxWidth: 400,
    storageKey: `ld-collection-list-width-${id}`,
  });

  const handleSelect = useCallback((note: NoteSummary) => {
    setSelectedId(note.id);
  }, []);

  const handleNewItem = useCallback(() => {
    setSelectedId(NEW_ITEM_ID);
  }, []);

  const handleCreated = useCallback((note: NoteSummary) => {
    setSelectedId(note.id);
  }, []);

  const handleDeleted = useCallback(() => {
    setSelectedId(null);
  }, []);

  const handleNavigate = useCallback((noteId: string) => {
    setSelectedId(noteId);
  }, []);

  // ── Loading / error states ────────────────────────────────────────────────
  if (collectionLoading) {
    return (
      <div className="flex items-center justify-center h-full gap-2 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        <span className="text-sm">Loading…</span>
      </div>
    );
  }

  if (collectionError || !collection) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
        <AlertCircle className="h-8 w-8 opacity-40" />
        <p className="text-sm">Collection not found.</p>
        <Button variant="ghost" size="sm" onClick={() => router.back()}>
          Go back
        </Button>
      </div>
    );
  }

  const isNew = selectedId === NEW_ITEM_ID;
  const editorNoteId = isNew ? null : selectedId;
  const DomainIcon = collection.domain === "notes" ? BookOpen : FileText;
  const iconDisplay = collection.icon ?? (collection.domain === "notes" ? "📓" : "📄");

  // ── Notes-backed collection ───────────────────────────────────────────────
  if (collection.domain === "notes") {
    return (
      <div className="flex flex-col h-full min-h-full">
        {/* Header */}
        <div className="flex items-center gap-2 px-3 py-1.5 border-b shrink-0 bg-background">
          <span className="text-lg leading-none">{iconDisplay}</span>
          <h1 className="text-sm font-semibold truncate flex-1">{collection.name}</h1>
          <FocusToggle className="ml-auto" />
        </div>

        {/* Main content */}
        <div className="flex flex-1 min-h-0">
          {/* Note list sidebar */}
          <aside
            className="shrink-0 border-r flex flex-col overflow-hidden bg-background transition-[width,opacity] duration-300 ease-in-out"
            style={{ width: focused ? 0 : width, opacity: focused ? 0 : 1 }}
          >
            {/* Scoped NoteList: filter by collection_id */}
            <CollectionNoteList
              collectionId={id}
              collectionName={collection.name}
              selectedId={isNew ? null : selectedId}
              onSelect={handleSelect}
              onNewNote={handleNewItem}
            />
          </aside>

          {/* Resize handle */}
          <div
            className="shrink-0 cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-[width] duration-300 ease-in-out"
            style={{ width: focused ? 0 : 4 }}
            onMouseDown={startResize}
          />

          {/* Editor pane */}
          <main className="flex-1 min-w-0 overflow-auto">
            {selectedId === null ? (
              <div className="flex flex-col items-center justify-center h-full text-center px-6 text-muted-foreground">
                <DomainIcon className="h-10 w-10 mb-3 opacity-30" />
                <p className="text-sm">Select an entry or create one.</p>
              </div>
            ) : (
              <NoteEditor
                key={selectedId}
                noteId={editorNoteId}
                defaultCollectionId={id}
                onCreated={handleCreated}
                onDeleted={handleDeleted}
                onNavigate={handleNavigate}
              />
            )}
          </main>
        </div>
      </div>
    );
  }

  // ── Documents-backed collection ───────────────────────────────────────────
  // For now, redirect to /documents filtered by this collection.
  // A dedicated documents collection view can be built as a follow-up.
  return (
    <div className="flex flex-col h-full min-h-full">
      <div className="flex items-center gap-2 px-3 py-1.5 border-b shrink-0 bg-background">
        <span className="text-lg leading-none">{iconDisplay}</span>
        <h1 className="text-sm font-semibold truncate flex-1">{collection.name}</h1>
      </div>
      <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
        Documents collection view — coming soon
      </div>
    </div>
  );
}

// ── CollectionNoteList ────────────────────────────────────────────────────────
// A thin wrapper around the notes API that scopes to a specific collection_id.
// Rather than threading collection_id through NoteList's full props surface,
// we build a minimal scoped list here.

interface CollectionNoteListProps {
  collectionId: string;
  collectionName: string;
  selectedId: string | null;
  onSelect: (note: NoteSummary) => void;
  onNewNote: () => void;
}

function CollectionNoteList({
  collectionId,
  collectionName,
  selectedId,
  onSelect,
  onNewNote,
}: CollectionNoteListProps) {
  const { data, isLoading, isError } = $api.useQuery("get", "/notes", {
    params: {
      query: {
        collection_id: collectionId,
        limit: 500,
      },
    },
  });

  const notes = data?.items ?? [];

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 pt-3 pb-2 shrink-0">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider px-1 truncate">
            {collectionName}
          </span>
          <Button
            size="sm"
            variant="ghost"
            className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground shrink-0"
            onClick={onNewNote}
            title="New entry"
          >
            <span className="text-base leading-none">+</span>
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-1.5 pb-2 space-y-0.5">
        {isLoading && (
          <div className="flex items-center gap-2 px-3 py-4 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Loading…
          </div>
        )}
        {isError && (
          <p className="px-3 py-4 text-xs text-destructive">Failed to load entries.</p>
        )}
        {!isLoading && !isError && notes.length === 0 && (
          <div className="px-3 py-6 text-center">
            <p className="text-xs text-muted-foreground">No entries yet.</p>
            <button
              type="button"
              onClick={onNewNote}
              className="mt-2 text-xs text-primary hover:underline"
            >
              Create one
            </button>
          </div>
        )}
        {!isLoading && !isError && notes.map((note) => (
          <button
            key={note.id}
            type="button"
            onClick={() => onSelect(note)}
            className={cn(
              "w-full text-left px-3 py-2 rounded-md text-sm transition-colors",
              note.id === selectedId
                ? "bg-primary/10 text-primary"
                : "text-foreground hover:bg-muted",
            )}
          >
            <span className="block truncate font-medium">{note.title}</span>
            <span className="block text-[11px] text-muted-foreground mt-0.5">
              {new Date(note.updated_at).toLocaleDateString(undefined, {
                month: "short",
                day: "numeric",
                year: "numeric",
              })}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
