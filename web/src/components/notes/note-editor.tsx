"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import { cn } from "@/lib/utils";
import {
  Loader2, Tag, X, Plus, Link2, Archive, Trash2, ChevronDown, ChevronRight,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import type { components } from "@/lib/api/schema";

type NoteResponse = components["schemas"]["NoteResponse"];
type NoteSummary = components["schemas"]["NoteSummary"];
type TagResponse = components["schemas"]["TagResponse"];
type NoteTagRef = components["schemas"]["NoteTagRef"];

// ── Wikilink highlighting ─────────────────────────────────────────────────────

function WikilinkCount({ content }: { content: string }) {
  const count = (content.match(/\[\[[^\]]+\]\]/g) ?? []).length;
  if (count === 0) return null;
  return (
    <span className="text-[11px] text-muted-foreground">
      {count} {count === 1 ? "link" : "links"}
    </span>
  );
}

// ── Tag pill ──────────────────────────────────────────────────────────────────

function TagPill({
  tag,
  onRemove,
}: {
  tag: NoteTagRef;
  onRemove?: () => void;
}) {
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-muted"
      style={tag.color ? { borderLeft: `3px solid ${tag.color}` } : undefined}
    >
      {tag.name}
      {onRemove && (
        <button type="button" onClick={onRemove} className="hover:text-destructive transition-colors">
          <X className="h-2.5 w-2.5" />
        </button>
      )}
    </span>
  );
}

// ── Tag adder ─────────────────────────────────────────────────────────────────

function TagAdder({
  currentTagIds,
  onAdd,
}: {
  currentTagIds: string[];
  onAdd: (tagId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [newTagName, setNewTagName] = useState("");
  const qc = useQueryClient();

  const { data: tagsData } = $api.useQuery("get", "/tags", {
    params: { query: { limit: 100 } },
  });
  const { mutateAsync: createTag } = $api.useMutation("post", "/tags");

  const available = (tagsData?.items ?? []).filter(
    (t: TagResponse) => !currentTagIds.includes(t.id)
  );

  async function handleCreateAndAdd() {
    const name = newTagName.trim();
    if (!name) return;
    const tag = await createTag({ body: { name } });
    qc.invalidateQueries({ queryKey: ["get", "/tags"] });
    onAdd(tag.id);
    setNewTagName("");
    setOpen(false);
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <Plus className="h-3 w-3" />
        Add tag
      </button>
    );
  }

  return (
    <div className="flex flex-col gap-1.5 border rounded-md p-2 bg-popover shadow-md min-w-[180px]">
      {available.length > 0 && (
        <div className="space-y-0.5 max-h-32 overflow-y-auto">
          {available.map((t: TagResponse) => (
            <button
              key={t.id}
              type="button"
              onClick={() => { onAdd(t.id); setOpen(false); }}
              className="flex items-center gap-2 w-full px-2 py-1 text-xs hover:bg-muted/60 rounded transition-colors text-left"
            >
              <span
                className="w-2 h-2 rounded-full shrink-0"
                style={{ background: t.color ?? "var(--muted-foreground)" }}
              />
              {t.name}
            </button>
          ))}
          <div className="border-t my-1" />
        </div>
      )}
      <div className="flex gap-1">
        <input
          autoFocus
          value={newTagName}
          onChange={(e) => setNewTagName(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") handleCreateAndAdd(); if (e.key === "Escape") setOpen(false); }}
          placeholder="New tag…"
          className="flex-1 min-w-0 text-xs bg-transparent border-b border-border outline-none px-1 py-0.5"
        />
        <button
          type="button"
          onClick={handleCreateAndAdd}
          disabled={!newTagName.trim()}
          className="text-xs text-primary disabled:opacity-40"
        >
          Add
        </button>
      </div>
      <button
        type="button"
        onClick={() => setOpen(false)}
        className="text-[11px] text-muted-foreground text-center hover:text-foreground"
      >
        Cancel
      </button>
    </div>
  );
}

// ── Backlinks panel ───────────────────────────────────────────────────────────

function BacklinksPanel({
  backlinks,
  onNavigate,
}: {
  backlinks: NoteResponse["backlinks"];
  onNavigate: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(true);

  if (backlinks.length === 0) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground px-1">
        <Link2 className="h-3.5 w-3.5" />
        No backlinks
      </div>
    );
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors mb-1"
      >
        {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        <Link2 className="h-3.5 w-3.5" />
        {backlinks.length} {backlinks.length === 1 ? "backlink" : "backlinks"}
      </button>
      {expanded && (
        <div className="space-y-1 ml-5">
          {backlinks.map((bl) => (
            <button
              key={bl.id}
              type="button"
              onClick={() => onNavigate(bl.id)}
              className="block text-xs text-primary hover:underline truncate text-left w-full"
            >
              {bl.alias && bl.alias !== bl.title
                ? <><span className="text-muted-foreground">[[{bl.alias}]]</span> → {bl.title}</>
                : bl.title}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main editor ───────────────────────────────────────────────────────────────

interface NoteEditorProps {
  /** null = create mode, string = edit mode */
  noteId: string | null;
  /** When set, new notes are stamped with this collection_id on creation. */
  defaultCollectionId?: string;
  onCreated: (note: NoteSummary) => void;
  onDeleted: () => void;
  onNavigate: (id: string) => void;
}

export function NoteEditor({ noteId, defaultCollectionId, onCreated, onDeleted, onNavigate }: NoteEditorProps) {
  const qc = useQueryClient();
  const isNew = noteId === null;

  // ── Local form state ───────────────────────────────────────────────────────
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [tagIds, setTagIds] = useState<string[]>([]);
  const [tags, setTags] = useState<NoteTagRef[]>([]);

  // ── Persistence state ──────────────────────────────────────────────────────
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Autosave: save 1s after the user stops typing (update mode only)
  const autosaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isDirty = useRef(false);

  // ── Fetch existing note ────────────────────────────────────────────────────
  const { data: noteData, isLoading } = $api.useQuery(
    "get",
    "/notes/{note_id}",
    { params: { path: { note_id: noteId! } } },
    { enabled: !isNew }
  );

  // Populate form when note loads or noteId changes
  useEffect(() => {
    if (isNew) {
      setTitle("");
      setContent("");
      setTagIds([]);
      setTags([]);
      isDirty.current = false;
    } else if (noteData) {
      setTitle(noteData.title);
      setContent(noteData.content_md ?? "");
      setTagIds(noteData.tags.map((t) => t.id));
      setTags(noteData.tags);
      isDirty.current = false;
    }
    setSaveError(null);
    setConfirmDelete(false);
  }, [noteId, noteData, isNew]);

  // ── Mutations ──────────────────────────────────────────────────────────────
  const { mutateAsync: createNote } = $api.useMutation("post", "/notes");
  const { mutateAsync: updateNote } = $api.useMutation("patch", "/notes/{note_id}");
  const { mutateAsync: deleteNote } = $api.useMutation("delete", "/notes/{note_id}");

  // ── Save helpers ───────────────────────────────────────────────────────────
  const save = useCallback(
    async (fields: { title?: string; content_md?: string; tag_ids?: string[] }) => {
      if (isNew) return;
      setSaving(true);
      setSaveError(null);
      try {
        await updateNote({
          params: { path: { note_id: noteId! } },
          body: fields,
        });
        qc.invalidateQueries({ queryKey: ["get", "/notes"] });
        qc.invalidateQueries({ queryKey: ["get", "/notes/{note_id}", { path: { note_id: noteId } }] });
        isDirty.current = false;
      } catch {
        setSaveError("Failed to save");
      } finally {
        setSaving(false);
      }
    },
    [isNew, noteId, updateNote, qc]
  );

  // Autosave content after 1s idle
  const scheduleAutosave = useCallback(() => {
    if (isNew) return;
    isDirty.current = true;
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
    autosaveTimer.current = setTimeout(() => {
      save({ content_md: content, title });
    }, 1000);
  }, [isNew, save, content, title]);

  // Flush autosave on unmount
  useEffect(() => {
    return () => {
      if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
    };
  }, []);

  // ── Create ─────────────────────────────────────────────────────────────────
  async function handleCreate() {
    const t = title.trim();
    if (!t) return;
    setSaving(true);
    setSaveError(null);
    try {
      const note = await createNote({
        body: {
          title: t,
          content_md: content || null,
          tag_ids: tagIds,
          collection_id: defaultCollectionId ?? null,
        },
      });
      qc.invalidateQueries({ queryKey: ["get", "/notes"] });
      onCreated(note as unknown as NoteSummary);
    } catch {
      setSaveError("Failed to create note");
    } finally {
      setSaving(false);
    }
  }

  // ── Delete ─────────────────────────────────────────────────────────────────
  async function handleDelete() {
    if (!noteId) return;
    await deleteNote({ params: { path: { note_id: noteId } } });
    qc.invalidateQueries({ queryKey: ["get", "/notes"] });
    onDeleted();
  }

  // ── Tag mutations ──────────────────────────────────────────────────────────
  const { data: tagsData } = $api.useQuery("get", "/tags", {
    params: { query: { limit: 100 } },
  });

  function addTag(tagId: string) {
    const tag = tagsData?.items?.find((t: TagResponse) => t.id === tagId);
    if (!tag || tagIds.includes(tagId)) return;
    const newIds = [...tagIds, tagId];
    const newTags = [...tags, { id: tag.id, name: tag.name, color: tag.color ?? null }];
    setTagIds(newIds);
    setTags(newTags);
    if (!isNew) save({ tag_ids: newIds });
  }

  function removeTag(tagId: string) {
    const newIds = tagIds.filter((id) => id !== tagId);
    const newTags = tags.filter((t) => t.id !== tagId);
    setTagIds(newIds);
    setTags(newTags);
    if (!isNew) save({ tag_ids: newIds });
  }

  // ── Title save on blur ─────────────────────────────────────────────────────
  function handleTitleBlur() {
    if (!isNew && isDirty.current) {
      if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
      save({ title, content_md: content });
    }
  }

  // ── Empty state ────────────────────────────────────────────────────────────
  if (!isNew && isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    );
  }

  const backlinks = noteData?.backlinks ?? [];

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-6 py-3 border-b shrink-0 gap-2">
        <div className="flex items-center gap-2 min-w-0">
          {saving && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground shrink-0" />}
          {saveError && <span className="text-xs text-destructive">{saveError}</span>}
          {!saving && !saveError && !isNew && (
            <span className="text-xs text-muted-foreground">
              {noteData?.content_md ? <WikilinkCount content={noteData.content_md} /> : null}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {isNew ? (
            <Button
              size="sm"
              onClick={handleCreate}
              disabled={!title.trim() || saving}
              className="h-7 text-xs"
            >
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Create"}
            </Button>
          ) : (
            <>
              {confirmDelete ? (
                <div className="flex items-center gap-1">
                  <span className="text-xs text-muted-foreground mr-1">Delete?</span>
                  <Button size="sm" variant="destructive" className="h-7 text-xs" onClick={handleDelete}>
                    Yes
                  </Button>
                  <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setConfirmDelete(false)}>
                    No
                  </Button>
                </div>
              ) : (
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                  title="Delete note"
                  onClick={() => setConfirmDelete(true)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              )}
            </>
          )}
        </div>
      </div>

      {/* Editor body */}
      <div className="flex-1 overflow-y-auto px-6 py-5 flex flex-col gap-4">
        {/* Title */}
        <input
          type="text"
          value={title}
          onChange={(e) => {
            setTitle(e.target.value);
            if (!isNew) isDirty.current = true;
          }}
          onBlur={handleTitleBlur}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              (e.currentTarget.nextElementSibling as HTMLElement | null)?.focus();
            }
          }}
          placeholder="Note title…"
          className="w-full text-xl font-semibold bg-transparent outline-none placeholder:text-muted-foreground/50 border-none"
        />

        {/* Tags row */}
        <div className="flex flex-wrap items-center gap-1.5">
          {tags.map((tag) => (
            <TagPill key={tag.id} tag={tag} onRemove={() => removeTag(tag.id)} />
          ))}
          <TagAdder currentTagIds={tagIds} onAdd={addTag} />
        </div>

        {/* Markdown textarea */}
        <textarea
          value={content}
          onChange={(e) => {
            setContent(e.target.value);
            scheduleAutosave();
          }}
          placeholder={"Write your note in Markdown…\n\nLink to other notes with [[Note Title]]"}
          className={cn(
            "w-full flex-1 min-h-[320px] resize-none bg-transparent outline-none text-sm",
            "font-mono leading-relaxed placeholder:text-muted-foreground/40",
            "border-none focus:ring-0"
          )}
          spellCheck
        />

        {/* Backlinks — only in edit mode */}
        {!isNew && (
          <div className="border-t pt-4 mt-2">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">
              Linked here
            </p>
            <BacklinksPanel backlinks={backlinks} onNavigate={onNavigate} />
          </div>
        )}
      </div>
    </div>
  );
}
