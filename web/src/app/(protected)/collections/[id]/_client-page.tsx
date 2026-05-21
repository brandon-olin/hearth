"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useSegmentId } from "@/lib/hooks/use-segment-id";
import { useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import { getAccessToken } from "@/lib/auth/token";
import { apiBaseUrl } from "@/lib/api/client";
import { resolveFolderIcon } from "@/lib/sidebar/folder-icons";
import { NoteEditor } from "@/components/notes/note-editor";
import { NoteGraph } from "@/components/notes/note-graph";
import { useResizablePanel } from "@/lib/hooks/use-resizable-panel";
import { useFocusMode } from "@/lib/focus/context";
import { FocusToggle } from "@/components/focus/focus-toggle";
import { Button } from "@/components/ui/button";
import {
  Loader2, BookOpen, FileText, AlertCircle,
  Settings, CalendarCheck, Plus, X, Check, ChevronDown,
  List, Network,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { components } from "@/lib/api/schema";

type NoteSummary  = components["schemas"]["NoteSummary"];
type CollectionResponse = components["schemas"]["CollectionResponse"];
type TemplateResponse   = components["schemas"]["TemplateResponse"];
type View = "list" | "graph";

/** Sentinel value: user clicked "New" but hasn't saved yet */
const NEW_ITEM_ID = "__new__";

export default function CollectionPage() {
  const id = useSegmentId();
  const router = useRouter();
  const qc = useQueryClient();
  const { focused } = useFocusMode();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pendingTitle, setPendingTitle] = useState<string>("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [todayLoading, setTodayLoading] = useState(false);
  const [view, setView] = useState<View>("list");

  // ── Fetch collection metadata ─────────────────────────────────────────────
  const { data: collection, isLoading: collectionLoading, isError: collectionError } =
    $api.useQuery("get", "/collections/{collection_id}", {
      params: { path: { collection_id: id } },
    });

  // ── Ensure-today mutation ─────────────────────────────────────────────────
  const ensureTodayMutation = $api.useMutation(
    "post",
    "/collections/{collection_id}/ensure-today",
  );

  const handleTodayClick = useCallback(async () => {
    if (!collection?.auto_create_rule) return;
    setTodayLoading(true);
    try {
      const result = await ensureTodayMutation.mutateAsync({
        params: { path: { collection_id: id } },
      });
      setSelectedId(result.item_id);
      if (collection.domain === "notes") {
        qc.invalidateQueries({ queryKey: ["get", "/notes"] });
      }
    } catch {
      // Silently ignore — best-effort
    } finally {
      setTodayLoading(false);
    }
  }, [collection, ensureTodayMutation, id, qc]);

  // Auto-ensure-today: when a collection with auto_create_rule loads, immediately
  // open/create today's entry so the user lands on it without any extra click.
  const autoEnsuredRef = useRef(false);
  useEffect(() => {
    if (autoEnsuredRef.current || !collection?.auto_create_rule) return;
    autoEnsuredRef.current = true;
    ensureTodayMutation.mutateAsync({
      params: { path: { collection_id: id } },
    }).then((result) => {
      setSelectedId(result.item_id);
      if (collection.domain === "notes") {
        qc.invalidateQueries({ queryKey: ["get", "/notes"] });
      }
    }).catch(() => { /* silently ignore */ });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collection]); // run once when collection data arrives

  const { width, startResize } = useResizablePanel({
    defaultWidth: 260,
    minWidth: 180,
    maxWidth: 400,
    storageKey: `ld-collection-list-width-${id}`,
  });

  const handleSelect   = useCallback((note: NoteSummary) => setSelectedId(note.id), []);
  const handleNewItem  = useCallback(() => setSelectedId(NEW_ITEM_ID), []);
  const handleCreated  = useCallback((note: NoteSummary) => {
    setSelectedId(note.id);
    setPendingTitle("");
  }, []);
  const handleDeleted  = useCallback(() => setSelectedId(null), []);
  const handleNavigate = useCallback((noteId: string) => setSelectedId(noteId), []);

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
  // Resolve the stored icon: Lucide name → component, emoji → keep as string
  const ColIcon = collection.icon ? resolveFolderIcon(collection.icon) : null;
  const iconDisplay = collection.icon ?? (collection.domain === "notes" ? "📓" : "📄");

  // ── Notes-backed collection ───────────────────────────────────────────────
  if (collection.domain === "notes") {
    return (
      <div className="flex flex-col h-full min-h-full">
        {/* Header */}
        <div className="flex items-center gap-2 px-3 py-1.5 border-b shrink-0 bg-background min-h-[40px]">
          {/* Icon + title */}
          {ColIcon
            ? <ColIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
            : <span className="text-base leading-none shrink-0">{iconDisplay}</span>}
          <h1 className="text-sm font-semibold truncate">{collection.name}</h1>

          {/* List / Graph toggle */}
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

          <div className="flex-1" />

          {/* Today button — only for auto-create collections */}
          {collection.auto_create_rule && (
            <Button
              variant="outline" size="sm"
              className="h-7 px-2.5 gap-1.5 text-xs shrink-0"
              onClick={handleTodayClick}
              disabled={todayLoading}
              title="Open or create today's entry"
            >
              {todayLoading
                ? <Loader2 className="h-3 w-3 animate-spin" />
                : <CalendarCheck className="h-3 w-3" />}
              Today
            </Button>
          )}

          {/* Settings gear */}
          <Button
            variant="ghost" size="sm"
            className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground shrink-0"
            onClick={() => setSettingsOpen(true)}
            title="Collection settings"
          >
            <Settings className="h-3.5 w-3.5" />
          </Button>

          <FocusToggle className="ml-1" />
        </div>

        {/* Main content */}
        <div className="flex flex-1 min-h-0">
          {view === "list" ? (
            <>
              {/* Note list sidebar */}
              <aside
                className="shrink-0 border-r flex flex-col overflow-hidden bg-background transition-[width,opacity] duration-300 ease-in-out"
                style={{ width: focused ? 0 : width, opacity: focused ? 0 : 1 }}
              >
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
                    {collection.auto_create_rule && (
                      <button
                        type="button"
                        onClick={handleTodayClick}
                        className="mt-3 text-sm text-primary hover:underline flex items-center gap-1.5"
                      >
                        <CalendarCheck className="h-4 w-4" />
                        Open today&apos;s entry
                      </button>
                    )}
                  </div>
                ) : (
                  <NoteEditor
                    key={selectedId}
                    noteId={editorNoteId}
                    initialTitle={isNew ? pendingTitle : undefined}
                    defaultCollectionId={id}
                    onCreated={handleCreated}
                    onDeleted={handleDeleted}
                    onNavigate={handleNavigate}
                  />
                )}
              </main>
            </>
          ) : (
            /* ── Graph view ── */
            <div className="flex flex-1 min-h-0 min-w-0">
              <div className="flex-1 min-w-0 min-h-0 relative overflow-hidden">
                <NoteGraph
                  selectedId={selectedId}
                  onSelect={(nodeId) => { setSelectedId(nodeId); }}
                />
              </div>
              {selectedId && selectedId !== "__new__" && (
                <>
                  <div className="w-px bg-border shrink-0" />
                  <div className="w-[380px] shrink-0 overflow-auto border-l">
                    <NoteEditor
                      key={selectedId}
                      noteId={selectedId}
                      defaultCollectionId={id}
                      onCreated={handleCreated}
                      onDeleted={() => setSelectedId(null)}
                      onNavigate={(noteId) => setSelectedId(noteId)}
                    />
                  </div>
                </>
              )}
            </div>
          )}
        </div>

        {/* Collection settings panel */}
        {settingsOpen && (
          <CollectionSettingsPanel
            collection={collection}
            onClose={() => setSettingsOpen(false)}
          />
        )}
      </div>
    );
  }

  // ── Documents-backed collection ───────────────────────────────────────────
  return (
    <div className="flex flex-col h-full min-h-full">
      <div className="flex items-center gap-2 px-3 py-1.5 border-b shrink-0 bg-background min-h-[40px]">
        {ColIcon
          ? <ColIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
          : <span className="text-base leading-none shrink-0">{iconDisplay}</span>}
        <h1 className="text-sm font-semibold truncate flex-1">{collection.name}</h1>
        <Button
          variant="ghost" size="sm"
          className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground shrink-0"
          onClick={() => setSettingsOpen(true)}
          title="Collection settings"
        >
          <Settings className="h-3.5 w-3.5" />
        </Button>
      </div>
      <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
        Documents collection view — coming soon
      </div>
      {settingsOpen && (
        <CollectionSettingsPanel
          collection={collection}
          onClose={() => setSettingsOpen(false)}
        />
      )}
    </div>
  );
}

// ── CollectionNoteList ────────────────────────────────────────────────────────

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
  const [search, setSearch] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const debounceTimer = useState<ReturnType<typeof setTimeout> | null>(null)[0];

  const { data, isLoading, isError } = $api.useQuery("get", "/notes", {
    params: {
      query: {
        collection_id: collectionId,
        q: debouncedQ || undefined,
        limit: 500,
      },
    },
  });

  const handleSearch = useCallback((val: string) => {
    setSearch(val);
    clearTimeout(debounceTimer ?? undefined);
    const timer = setTimeout(() => setDebouncedQ(val), 300);
    // store in ref via closure — we just need the debounce effect
    void timer;
    setDebouncedQ(val); // instant for small queries
  }, [debounceTimer]);

  const notes = data?.items ?? [];

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 pt-3 pb-2 shrink-0 space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider px-1 truncate">
            {collectionName}
          </span>
          <Button
            size="sm" variant="ghost"
            className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground shrink-0"
            onClick={onNewNote}
            title="New entry"
          >
            <Plus className="h-4 w-4" />
          </Button>
        </div>
        <div className="relative">
          <input
            type="text"
            value={search}
            onChange={(e) => handleSearch(e.target.value)}
            placeholder="Search…"
            className="w-full h-7 pl-2.5 pr-7 rounded-md border text-xs bg-muted/50 focus:outline-none focus:ring-1 focus:ring-primary/40"
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
            <p className="text-xs text-muted-foreground">
              {debouncedQ ? "No matching entries." : "No entries yet."}
            </p>
            {!debouncedQ && (
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
            <span className={cn("block truncate font-medium", !note.title && "italic text-muted-foreground")}>
              {note.title || "Untitled"}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ── CollectionSettingsPanel ───────────────────────────────────────────────────

interface CollectionSettingsPanelProps {
  collection: CollectionResponse;
  onClose: () => void;
}

function CollectionSettingsPanel({ collection, onClose }: CollectionSettingsPanelProps) {
  const qc = useQueryClient();

  // ── Local field state ────────────────────────────────────────────────────
  const [name,        setName]        = useState(collection.name);
  const [icon,        setIcon]        = useState(collection.icon ?? "");
  const [showInNav,   setShowInNav]   = useState(collection.show_in_nav);
  const [autoCreate,  setAutoCreate]  = useState(!!collection.auto_create_rule);
  const [titleTpl,    setTitleTpl]    = useState(
    collection.auto_create_rule?.title_template ??
    "{{day_of_week}}, {{month}} {{day}}, {{year}}"
  );

  // ── Templates assigned to this collection ─────────────────────────────────
  const { data: collectionTemplates } = $api.useQuery(
    "get",
    "/collections/{collection_id}/templates",
    { params: { path: { collection_id: collection.id } } },
  );
  const assignedTemplates = collectionTemplates?.items ?? [];
  const defaultTemplate = assignedTemplates.find((t) => t.is_default);

  // ── All available templates (for picker) ─────────────────────────────────
  const { data: allTemplatesData } = $api.useQuery("get", "/templates", {
    params: { query: { domain: collection.domain, limit: 100 } },
  });
  const allTemplates: TemplateResponse[] = allTemplatesData?.items ?? [];

  // ── Template picker ───────────────────────────────────────────────────────
  const [tplPickerOpen, setTplPickerOpen] = useState(false);
  const [tplSearch,     setTplSearch]     = useState("");
  const filteredTpls = tplSearch.trim()
    ? allTemplates.filter((t) =>
        t.name.toLowerCase().includes(tplSearch.trim().toLowerCase())
      )
    : allTemplates;

  // ── Saving state ─────────────────────────────────────────────────────────
  const [saving, setSaving] = useState(false);
  const [saved,  setSaved]  = useState(false);
  const [error,  setError]  = useState<string | null>(null);

  async function saveCollection() {
    setSaving(true);
    setError(null);
    try {
      const token = getAccessToken();
      const body = {
        name: name.trim() || collection.name,
        icon: icon.trim() || null,
        show_in_nav: showInNav,
        auto_create_rule: autoCreate
          ? { frequency: "daily" as const, title_template: titleTpl.trim() || "{{day_of_week}}, {{month}} {{day}}, {{year}}" }
          : null,
      };
      const res = await fetch(`${apiBaseUrl}/collections/${collection.id}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const b = await res.json().catch(() => ({}));
        throw new Error((b as { detail?: string }).detail ?? "Failed to save");
      }
      await qc.invalidateQueries({ queryKey: ["get", "/collections"] });
      await qc.invalidateQueries({
        queryKey: ["get", "/collections/{collection_id}", { params: { path: { collection_id: collection.id } } }],
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function setDefaultTemplate(templateId: string) {
    const token = getAccessToken();
    // Assign first if not already assigned
    const alreadyAssigned = assignedTemplates.some((t) => t.template.id === templateId);
    if (!alreadyAssigned) {
      await fetch(`${apiBaseUrl}/collections/${collection.id}/templates`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ template_id: templateId, is_default: true }),
      });
    } else {
      await fetch(`${apiBaseUrl}/collections/${collection.id}/templates/${templateId}/default`, {
        method: "PATCH",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
    }
    await qc.invalidateQueries({
      queryKey: ["get", "/collections/{collection_id}/templates"],
    });
    setTplPickerOpen(false);
    setTplSearch("");
  }

  async function clearDefaultTemplate() {
    if (!defaultTemplate) return;
    const token = getAccessToken();
    await fetch(
      `${apiBaseUrl}/collections/${collection.id}/templates/${defaultTemplate.template.id}`,
      {
        method: "DELETE",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      }
    );
    await qc.invalidateQueries({
      queryKey: ["get", "/collections/{collection_id}/templates"],
    });
  }

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/20"
        onClick={onClose}
        aria-hidden
      />

      {/* Panel */}
      <aside className="fixed right-0 top-0 bottom-0 z-50 w-80 bg-background border-l shadow-xl flex flex-col animate-in slide-in-from-right duration-200">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b shrink-0">
          <h2 className="text-sm font-semibold">Collection settings</h2>
          <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">

          {/* Name */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wide block mb-1.5">
              Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full h-9 px-3 rounded-md border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
            />
          </div>

          {/* Icon */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wide block mb-1.5">
              Icon (emoji or leave blank)
            </label>
            <input
              type="text"
              value={icon}
              onChange={(e) => setIcon(e.target.value)}
              placeholder="📓"
              className="w-full h-9 px-3 rounded-md border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
            />
          </div>

          {/* Show in nav */}
          <div className="flex items-center justify-between py-1">
            <div>
              <p className="text-sm font-medium">Show in sidebar</p>
              <p className="text-xs text-muted-foreground mt-0.5">
                Pin this collection to the main navigation.
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={showInNav}
              onClick={() => setShowInNav((v) => !v)}
              className={cn(
                "relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none",
                showInNav ? "bg-primary" : "bg-muted-foreground/30"
              )}
            >
              <span
                className={cn(
                  "pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow-sm transform transition-transform",
                  showInNav ? "translate-x-4" : "translate-x-0"
                )}
              />
            </button>
          </div>

          {/* Auto-create rule */}
          <div className="border rounded-lg overflow-hidden">
            <button
              type="button"
              onClick={() => setAutoCreate((v) => !v)}
              className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium hover:bg-muted/40 transition-colors"
            >
              <div className="text-left">
                <p className="font-medium">Auto-create daily entries</p>
                <p className="text-xs text-muted-foreground font-normal mt-0.5">
                  Automatically create an entry each day when you open this collection.
                </p>
              </div>
              <div className={cn(
                "relative inline-flex h-5 w-9 shrink-0 rounded-full border-2 border-transparent transition-colors ml-3",
                autoCreate ? "bg-primary" : "bg-muted-foreground/30"
              )}>
                <span className={cn(
                  "pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow-sm transform transition-transform",
                  autoCreate ? "translate-x-4" : "translate-x-0"
                )} />
              </div>
            </button>

            {autoCreate && (
              <div className="border-t px-4 py-3 space-y-2">
                <label className="text-xs text-muted-foreground block">Entry title template</label>
                <input
                  type="text"
                  value={titleTpl}
                  onChange={(e) => setTitleTpl(e.target.value)}
                  placeholder="{{day_of_week}}, {{month}} {{day}}, {{year}}"
                  className="w-full h-8 px-2.5 rounded border bg-background text-xs font-mono focus:outline-none focus:ring-1 focus:ring-primary/40"
                />
                <p className="text-[10px] text-muted-foreground">
                  Variables: {"{{"+"day_of_week"+"}}"}, {"{{"+"month"+"}}"}, {"{{"+"day"+"}}"}, {"{{"+"year"+"}}"}, {"{{"+"date"+"}}"}
                </p>
              </div>
            )}
          </div>

          {/* Default template */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wide block mb-1.5">
              Default template
            </label>
            <p className="text-xs text-muted-foreground mb-2">
              Content copied into new entries automatically.
            </p>

            {defaultTemplate ? (
              <div className="flex items-center gap-2 p-3 rounded-md border bg-muted/20">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{defaultTemplate.template.name}</p>
                  {defaultTemplate.template.description && (
                    <p className="text-xs text-muted-foreground truncate mt-0.5">
                      {defaultTemplate.template.description}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={clearDefaultTemplate}
                  className="shrink-0 text-muted-foreground hover:text-destructive transition-colors"
                  title="Remove default template"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ) : (
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setTplPickerOpen((v) => !v)}
                  className="w-full flex items-center justify-between h-9 px-3 rounded-md border bg-background text-sm hover:bg-muted/40 transition-colors"
                >
                  <span className="text-muted-foreground">
                    {allTemplates.length === 0 ? "No templates available" : "Select a template…"}
                  </span>
                  <ChevronDown className={cn("h-4 w-4 text-muted-foreground transition-transform", tplPickerOpen && "rotate-180")} />
                </button>

                {tplPickerOpen && allTemplates.length > 0 && (
                  <div className="absolute z-10 mt-1 w-full rounded-md border bg-popover shadow-md">
                    <div className="p-2 border-b">
                      <input
                        type="text"
                        value={tplSearch}
                        onChange={(e) => setTplSearch(e.target.value)}
                        placeholder="Search templates…"
                        autoFocus
                        className="w-full h-7 px-2 text-xs rounded border bg-background focus:outline-none"
                      />
                    </div>
                    <div className="max-h-48 overflow-y-auto">
                      {filteredTpls.length === 0 ? (
                        <p className="px-3 py-4 text-xs text-muted-foreground text-center">No match</p>
                      ) : filteredTpls.map((t) => (
                        <button
                          key={t.id}
                          type="button"
                          onClick={() => setDefaultTemplate(t.id)}
                          className="w-full text-left px-3 py-2 text-sm hover:bg-muted/60 transition-colors"
                        >
                          <p className="font-medium truncate">{t.name}</p>
                          {t.description && (
                            <p className="text-xs text-muted-foreground truncate">{t.description}</p>
                          )}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-3.5 border-t shrink-0 space-y-2">
          {error && (
            <p className="text-xs text-destructive flex items-center gap-1.5">
              <AlertCircle className="h-3.5 w-3.5 shrink-0" /> {error}
            </p>
          )}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={saveCollection}
              disabled={saving}
              className="flex-1 h-9 text-sm font-medium rounded-md bg-primary text-primary-foreground disabled:opacity-40 flex items-center justify-center gap-1.5"
            >
              {saving
                ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                : saved
                ? <Check className="h-3.5 w-3.5" />
                : null}
              {saved ? "Saved" : "Save"}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="h-9 px-4 text-sm rounded-md border hover:bg-muted/50 transition-colors"
            >
              Close
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}
