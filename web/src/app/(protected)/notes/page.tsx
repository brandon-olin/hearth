"use client";

import { useState, useCallback, useEffect } from "react";
import { $api } from "@/lib/api/query";
import { NoteList } from "@/components/notes/note-list";
import { NoteEditor } from "@/components/notes/note-editor";
import { NoteGraph } from "@/components/notes/note-graph";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { HintBanner } from "@/components/onboarding/hint-banner";
import { useRegisterCurrentResource } from "@/lib/chat-context/current-resource";
import { useResizablePanel } from "@/lib/hooks/use-resizable-panel";
import { useFocusMode } from "@/lib/focus/context";
import { FocusToggle } from "@/components/focus/focus-toggle";
import { useAuth } from "@/lib/auth/context";
import { BookOpen, Network, List, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import type { components } from "@/lib/api/schema";

type NoteSummary = components["schemas"]["NoteSummary"];
type View = "list" | "graph";

/** Sentinel value: user clicked "New note" but hasn't saved yet */
const NEW_NOTE_ID = "__new__";

export default function NotesPage() {
  const { user } = useAuth();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // chat-001: keep the selected note's title in sync so the chat sidebar
  // can show 'Discussing: <title>' without an extra fetch.
  const [selectedTitle, setSelectedTitle] = useState<string>("");
  const [view, setView] = useState<View>("list");

  // When the active user changes (e.g. impersonation switch), reset all
  // local selection state so the editor doesn't keep displaying another
  // user's private content from its own useState cache.
  useEffect(() => {
    setSelectedId(null);
  }, [user?.id]);

  // onboarding-003: the list lives in NoteList, which owns the search box — its
  // count reflects the filter. A one-row unfiltered probe is the only honest
  // "does this household have any notes at all" signal available on this page.
  const { data: notesProbe } = $api.useQuery("get", "/notes", {
    params: { query: { limit: 1 } },
  });
  const hasNoNotes = notesProbe !== undefined && notesProbe.items.length === 0;

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
    setSelectedTitle(note.title ?? "");
    setView("list");
  }, []);

  const handleGraphSelect = useCallback((id: string) => {
    setSelectedId(id);
    // Title not known from a graph click — chip falls back to a short id.
    setSelectedTitle("");
  }, []);

  const handleNewNote = useCallback(() => {
    setSelectedId(NEW_NOTE_ID);
    setSelectedTitle("");
    setView("list");
  }, []);

  // Title to pre-fill when a ghost node is clicked in the graph view
  const [pendingTitle, setPendingTitle] = useState<string>("");

  const handleGhostSelect = useCallback((title: string) => {
    setPendingTitle(title);
    setSelectedId(NEW_NOTE_ID);
    setView("list");
  }, []);

  const handleCreated = useCallback((note: NoteSummary) => {
    setSelectedId(note.id);
    setPendingTitle("");
  }, []);

  const handleDeleted = useCallback(() => {
    setSelectedId(null);
    setPendingTitle("");
  }, []);

  const handleNavigate = useCallback((id: string) => {
    setSelectedId(id);
  }, []);

  const isNew = selectedId === NEW_NOTE_ID;
  const editorNoteId = isNew ? null : selectedId;

  // chat-001: publish the open note so the sidebar chatbot knows what
  // 'this' refers to when the user asks about the entry they're reading.
  useRegisterCurrentResource(
    editorNoteId
      ? { type: "note", id: editorNoteId, title: selectedTitle }
      : null,
  );

  return (
    <div className="flex flex-col h-full min-h-full">

      {/* ── View toggle bar ───────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b shrink-0 bg-background min-h-[40px]">
        <BookOpen className="h-4 w-4 shrink-0 text-muted-foreground" />
        <h1 className="text-sm font-semibold">Notes</h1>
        <div className="flex rounded-md overflow-hidden border text-xs shrink-0 ml-2">
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

      {/* shrink-0: the pane layout below is `flex-1 min-h-0`, so a growable
          banner here would eat the editor's scroll area. */}
      <HintBanner id="notes" className="shrink-0 m-3 mb-0" />

      {/* ── Main content ─────────────────────────────────────────────────── */}
      <div className="flex flex-1 min-h-0">

        {view === "list" ? (
          <>
            {/* Note list sidebar — collapses in focus mode */}
            {/* On phones the list and editor are alternating full-width views —
                260px of sidebar would leave ~110px for the editor. The stored
                width is passed as a CSS var so it only applies from md up. */}
            <aside
              className={cn(
                "shrink-0 border-r flex flex-col overflow-hidden bg-background transition-[width,opacity] duration-300 ease-in-out",
                "w-full md:w-[var(--notes-list-w)]",
                (selectedId !== null || focused) && "hidden md:flex",
              )}
              style={
                {
                  "--notes-list-w": `${focused ? 0 : width}px`,
                  opacity: focused ? 0 : 1,
                } as React.CSSProperties
              }
            >
              <NoteList
                selectedId={isNew ? null : selectedId}
                onSelect={handleSelect}
                onNewNote={handleNewNote}
                onAllDeleted={() => setSelectedId(null)}
              />
            </aside>

            {/* Resize handle — hidden in focus mode */}
            {/* Mouse-only affordance — no touch equivalent, so hide it on phones. */}
            <div
              className="hidden md:block shrink-0 cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-[width] duration-300 ease-in-out"
              style={{ width: focused ? 0 : 4 }}
              onMouseDown={startResize}
            />

            {/* Editor pane — hidden on phones until a note is picked */}
            <main
              className={cn(
                "flex-1 min-w-0 overflow-auto",
                selectedId === null && "hidden md:block",
              )}
            >
              {selectedId === null ? (
                /* onboarding-003: the sidebar is ~260px, too narrow for a rich
                   empty state, so it lives in the editor pane instead. Someone
                   who already has notes gets the short "pick one" prompt — they
                   do not need to be told what notes are. */
                hasNoNotes ? (
                  <EmptyState
                    icon={BookOpen}
                    title="No notes yet"
                    description="Notes are for quick thoughts and references you want to find again later, without the ceremony of a document."
                    className="h-full"
                    action={
                      <Button size="sm" onClick={handleNewNote}>
                        <Plus className="h-4 w-4 mr-1" />
                        Write your first note
                      </Button>
                    }
                  />
                ) : (
                  <div className="flex flex-col items-center justify-center h-full text-center px-6 text-muted-foreground">
                    <BookOpen className="h-10 w-10 mb-3 opacity-30" />
                    <p className="text-sm">Select a note or create one.</p>
                  </div>
                )
              ) : (
                <NoteEditor
                  key={selectedId}
                  noteId={editorNoteId}
                  initialTitle={isNew ? pendingTitle : undefined}
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
            {/* Graph canvas — yields the whole viewport to the editor panel on
                phones rather than sharing 375px with it. */}
            <div
              className={cn(
                "flex-1 min-w-0 min-h-0 relative overflow-hidden",
                selectedId && !isNew && "hidden md:block",
              )}
            >
              <NoteGraph
                selectedId={selectedId}
                onSelect={handleGraphSelect}
              />
            </div>

            {/* Editor side-panel — slides in when a node is selected */}
            {selectedId && !isNew && (
              <>
                <div className="hidden md:block w-px bg-border shrink-0" />
                <div className="w-full md:w-[380px] shrink-0 overflow-auto border-l">
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
