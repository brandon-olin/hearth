"use client";

import { useState, useCallback, useEffect } from "react";
import { NoteList } from "@/components/notes/note-list";
import { NoteEditor } from "@/components/notes/note-editor";
import { NoteGraph } from "@/components/notes/note-graph";
import { useResizablePanel } from "@/lib/hooks/use-resizable-panel";
import { useFocusMode } from "@/lib/focus/context";
import { FocusToggle } from "@/components/focus/focus-toggle";
import { useAuth } from "@/lib/auth/context";
import { BookOpen, Network, List } from "lucide-react";
import { cn } from "@/lib/utils";
import type { components } from "@/lib/api/schema";

type NoteSummary = components["schemas"]["NoteSummary"];
type View = "list" | "graph";

/** Sentinel value: user clicked "New note" but hasn't saved yet */
const NEW_NOTE_ID = "__new__";

export default function NotesPage() {
  const { user } = useAuth();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<View>("list");

  // When the active user changes (e.g. impersonation switch), reset all
  // local selection state so the editor doesn't keep displaying another
  // user's private content from its own useState cache.
  useEffect(() => {
    setSelectedId(null);
  }, [user?.id]);

  // ── Resizable panel + focus ─────────────────────────────────────────────────
  const { width, startResize } = useResizablePanel({
    defaultWidth: 260,
    minWidth: 180,
    maxWidth: 400,
    storageKey: "ld-notes-list-width",
  });
  const { focused } = useFocusMode();

  const handleSelect = useCallback((note: NoteSummary) => {
    setSelectedId(note.id);
    setView("list");
  }, []);

  const handleGraphSelect = useCallback((id: string) => {
    setSelectedId(id);
  }, []);

  const handleNewNote = useCallback(() => {
    setSelectedId(NEW_NOTE_ID);
    setView("list");
  }, []);

  const handleCreated = useCallback((note: NoteSummary) => {
    setSelectedId(note.id);
  }, []);

  const handleDeleted = useCallback(() => {
    setSelectedId(null);
  }, []);

  const handleNavigate = useCallback((id: string) => {
    setSelectedId(id);
  }, []);

  const isNew = selectedId === NEW_NOTE_ID;
  const editorNoteId = isNew ? null : selectedId;

  return (
    <div className="flex flex-col h-full min-h-full">

      {/* ── View toggle bar ───────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b shrink-0 bg-background min-h-[40px]">
        <div className="flex rounded-md overflow-hidden border text-xs shrink-0">
          <button
            type="button"
            onClick={() => setView("list")}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1 transition-colors",
              view === "list"
                ? "bg-foreground text-background"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
            )}
          >
            <List className="h-3 w-3" />
            List
          </button>
          <button
            type="button"
            onClick={() => setView("graph")}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1 transition-colors border-l",
              view === "graph"
                ? "bg-foreground text-background"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
            )}
          >
            <Network className="h-3 w-3" />
            Graph
          </button>
        </div>
        <FocusToggle className="ml-auto shrink-0" />
      </div>

      {/* ── Main content ─────────────────────────────────────────────────── */}
      <div className="flex flex-1 min-h-0">

        {view === "list" ? (
          <>
            {/* Note list sidebar — collapses in focus mode */}
            <aside
              className="shrink-0 border-r flex flex-col overflow-hidden bg-background transition-[width,opacity] duration-300 ease-in-out"
              style={{ width: focused ? 0 : width, opacity: focused ? 0 : 1 }}
            >
              <NoteList
                selectedId={isNew ? null : selectedId}
                onSelect={handleSelect}
                onNewNote={handleNewNote}
                onAllDeleted={() => setSelectedId(null)}
              />
            </aside>

            {/* Resize handle — hidden in focus mode */}
            <div
              className="shrink-0 cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-[width] duration-300 ease-in-out"
              style={{ width: focused ? 0 : 4 }}
              onMouseDown={startResize}
            />

            {/* Editor pane */}
            <main className="flex-1 min-w-0 overflow-auto">
              {selectedId === null ? (
                <div className="flex flex-col items-center justify-center h-full text-center px-6 text-muted-foreground">
                  <BookOpen className="h-10 w-10 mb-3 opacity-30" />
                  <p className="text-sm">Select a note or create one.</p>
                </div>
              ) : (
                <NoteEditor
                  key={selectedId}
                  noteId={editorNoteId}
                  onCreated={handleCreated}
                  onDeleted={handleDeleted}
                  onNavigate={handleNavigate}
                />
              )}
            </main>
          </>
        ) : (
          /* ── Graph view ──────────────────────────────────────── */
          <div className="flex flex-1 min-h-0 min-w-0">
            {/* Graph canvas */}
            <div className="flex-1 min-w-0 min-h-0 relative overflow-hidden">
              <NoteGraph
                selectedId={selectedId}
                onSelect={handleGraphSelect}
              />
            </div>

            {/* Editor side-panel — slides in when a node is selected */}
            {selectedId && !isNew && (
              <>
                <div className="w-px bg-border shrink-0" />
                <div className="w-[380px] shrink-0 overflow-auto border-l">
                  <NoteEditor
                    key={selectedId}
                    noteId={selectedId}
                    onCreated={handleCreated}
                    onDeleted={() => { setSelectedId(null); }}
                    onNavigate={(id) => { setSelectedId(id); }}
                  />
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
