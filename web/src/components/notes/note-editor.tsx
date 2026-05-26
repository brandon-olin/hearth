"use client";

import { useEffect, useLayoutEffect, useRef, useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import { cn } from "@/lib/utils";
import {
  Loader2, Tag, X, Plus, Link2, Trash2, ChevronDown, ChevronRight, Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { JournalSession } from "@/components/journal/journal-session";
import { useAuth } from "@/lib/auth/context";
import type { components } from "@/lib/api/schema";

type NoteResponse = components["schemas"]["NoteResponse"];
type NoteSummary = components["schemas"]["NoteSummary"];
type TagResponse = components["schemas"]["TagResponse"];
type NoteTagRef = components["schemas"]["TagRef"];

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

// ── Journal entry-date helper (journal-001) ──────────────────────────────────

/**
 * Decide whether `note` is TODAY's journal entry — used to gate the
 * 'Talk it out' button. Three-step check:
 *
 *  1. The note must be in a journal-kind collection (server provides
 *     collection_kind on NoteResponse).
 *  2. Try to parse a date out of the title (the daily auto-create rule
 *     produces titles like "Tuesday, May 25, 2026"). Optional ordinal
 *     suffix tolerated.
 *  3. Fallback: use the note's created_at.
 *
 * Returns true when the resolved date equals today in the user's
 * timezone. Strict — past entries: no button. Future-dated journals
 * (rare): no button.
 */
function isTodayJournalEntry(
  collection_kind: string | null | undefined,
  title: string,
  created_at: string,
): boolean {
  if (collection_kind !== "journal") return false;

  // Try to parse a date from the title first.
  const match = title.match(/([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,\s+(\d{4})/);
  let resolved: Date | null = null;
  if (match) {
    const [, monthStr, dayStr, yearStr] = match;
    const parsed = new Date(`${monthStr} ${dayStr}, ${yearStr}`);
    if (!isNaN(parsed.getTime())) {
      resolved = parsed;
    }
  }
  if (!resolved) {
    const fallback = new Date(created_at);
    if (isNaN(fallback.getTime())) return false;
    resolved = fallback;
  }

  const today = new Date();
  return (
    resolved.getFullYear() === today.getFullYear() &&
    resolved.getMonth() === today.getMonth() &&
    resolved.getDate() === today.getDate()
  );
}


// ── Main editor ───────────────────────────────────────────────────────────────

interface NoteEditorProps {
  /** null = create mode, string = edit mode */
  noteId: string | null;
  /** When set, new notes are stamped with this collection_id on creation. */
  defaultCollectionId?: string;
  /** Pre-fill the title when opening in create mode (e.g. from a ghost node click). */
  initialTitle?: string;
  onCreated: (note: NoteSummary) => void;
  onDeleted: () => void;
  onNavigate: (id: string) => void;
}

export function NoteEditor({ noteId, defaultCollectionId, initialTitle, onCreated, onDeleted, onNavigate }: NoteEditorProps) {
  const qc = useQueryClient();
  const isNew = noteId === null;
  // ai-access-001: hide the 'Talk it out' button when AI features are
  // disabled for this member. Backend would 403 the journal endpoints
  // anyway; this just keeps the UI honest.
  const { user } = useAuth();
  const aiEnabled = user?.ai_features_enabled !== false;

  // ── Local form state ───────────────────────────────────────────────────────
  const [title, setTitle] = useState(initialTitle ?? "");
  const [content, setContent] = useState("");
  const [tagIds, setTagIds] = useState<string[]>([]);
  const [tags, setTags] = useState<NoteTagRef[]>([]);

  // ── Persistence state ──────────────────────────────────────────────────────
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // journal-001: 'Talk it out' overlay state. Gated by isTodayJournalEntry
  // below — the button only appears when conditions are met.
  const [journalOpen, setJournalOpen] = useState(false);

  // Autosave: save 1s after the user stops typing (update mode only)
  const autosaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isDirty = useRef(false);

  // Guard: only allow saves AFTER the server data has been loaded into the form.
  // Without this, a save firing before noteData arrives would overwrite the note
  // with empty content (content = "" until the populate effect runs).
  const hasInitializedRef = useRef(isNew); // new notes don't need server load

  // Guard: ensure the auto-create effect only POSTs once per mount.
  // React 18 Strict Mode (on by default in Next.js dev) intentionally
  // invokes useEffect twice — mount → run → cleanup → run again — to
  // surface non-idempotent effects. The previous `cancelled` flag only
  // suppressed the React handler; the network request had already been
  // dispatched, so the second invocation created a duplicate note. Refs
  // survive Strict Mode's double-invocation on the same component
  // instance, so flipping this once is enough to short-circuit the
  // second run. (See CLAUDE.md "Write idempotently" — the deeper fix
  // is an Idempotency-Key header on the POST so the backend dedupes
  // retries/back-button replays/multi-tab too.)
  const hasCreatedNewNoteRef = useRef(false);

  // Always-current refs so the setTimeout closure never reads stale state.
  const contentRef = useRef(content);
  const titleRef = useRef(title);
  useLayoutEffect(() => {
    contentRef.current = content;
    titleRef.current = title;
  }, [content, title]);

  // ── Mutations ──────────────────────────────────────────────────────────────
  const { mutateAsync: createNote } = $api.useMutation("post", "/notes");
  const { mutateAsync: updateNote } = $api.useMutation("patch", "/notes/{note_id}");
  const { mutateAsync: deleteNote } = $api.useMutation("delete", "/notes/{note_id}");

  // ── Auto-create on mount (new mode) ───────────────────────────────────────
  // Create immediately with an empty title so the note exists from the moment
  // the editor opens. The parent remounts this component in edit mode once
  // onCreated fires with the new note's real ID.
  //
  // The hasCreatedNewNoteRef guard prevents a duplicate POST under React
  // Strict Mode's dev-only effect double-invocation (mount → run → cleanup
  // → run again). Refs persist across that pseudo-unmount on the SAME
  // component instance, so flipping the ref once short-circuits the
  // second invocation.
  //
  // NOTE: an earlier version of this code also tracked a `cancelled` flag
  // in the cleanup function and bailed in the .then() if it was true.
  // That interacted badly with Strict Mode: the cleanup between the two
  // effect invocations flipped `cancelled = true`, so the .then() from
  // the single legitimate POST never ran, onCreated was never called,
  // and the spinner hung forever. The ref guard is sufficient; the
  // cancelled flag has been removed. If the component actually unmounts
  // (user navigates away mid-create) the worst case is a no-op setState
  // warning — harmless in React 18.
  useEffect(() => {
    if (!isNew) return;
    if (hasCreatedNewNoteRef.current) return;
    hasCreatedNewNoteRef.current = true;
    setSaving(true);
    createNote({
      body: {
        title: initialTitle ?? "",
        content_md: null,
        tag_ids: [],
        collection_id: defaultCollectionId ?? null,
      },
    }).then((note) => {
      qc.invalidateQueries({ queryKey: ["get", "/notes"] });
      onCreated(note as unknown as NoteSummary);
    }).catch(() => {
      setSaveError("Failed to create note");
    }).finally(() => {
      setSaving(false);
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // intentionally runs once on mount

  // ── Fetch existing note ────────────────────────────────────────────────────
  const { data: noteData, isLoading } = $api.useQuery(
    "get",
    "/notes/{note_id}",
    { params: { path: { note_id: noteId! } } },
    { enabled: !isNew }
  );

  // Populate form when note loads
  useEffect(() => {
    if (isNew || !noteData) return;
    setTitle(noteData.title);
    setContent(noteData.content_md ?? "");
    setTagIds(noteData.tags.map((t) => t.id));
    setTags(noteData.tags);
    isDirty.current = false;
    setSaveError(null);
    setConfirmDelete(false);
    // Allow saves now that we have real data in the form.
    hasInitializedRef.current = true;
  }, [noteId, noteData, isNew]);

  // ── Save helpers ───────────────────────────────────────────────────────────
  const save = useCallback(
    async (fields: { title?: string; content_md?: string; tag_ids?: string[] }) => {
      if (isNew || !hasInitializedRef.current) return;
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

  // Autosave content after 1s idle.
  // Uses contentRef/titleRef so the setTimeout closure always reads the latest
  // values — avoids the stale-closure bug where one render's content would be
  // saved instead of the current content.
  const scheduleAutosave = useCallback(() => {
    if (isNew) return;
    isDirty.current = true;
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
    autosaveTimer.current = setTimeout(() => {
      save({ content_md: contentRef.current, title: titleRef.current });
    }, 1000);
  }, [isNew, save]); // intentionally no content/title — read from refs instead

  // Flush pending autosave on unmount (e.g. when switching list ↔ graph view).
  // Without this, keystrokes typed in the last second before unmount would be
  // silently dropped.
  const saveRef = useRef(save);
  useLayoutEffect(() => { saveRef.current = save; }, [save]);
  useEffect(() => {
    return () => {
      if (autosaveTimer.current) {
        clearTimeout(autosaveTimer.current);
        if (isDirty.current && hasInitializedRef.current) {
          // Fire the save synchronously on unmount so in-flight edits aren't lost.
          saveRef.current({ content_md: contentRef.current, title: titleRef.current });
        }
      }
    };
  }, []);

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

  // ── Loading states ─────────────────────────────────────────────────────────
  // Show a spinner while auto-creating (isNew) or loading existing note
  if (isNew || (!noteData && isLoading)) {
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
          {!saving && !saveError && (
            <span className="text-xs text-muted-foreground">
              {noteData?.content_md ? <WikilinkCount content={noteData.content_md} /> : null}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
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
            isDirty.current = true;
          }}
          onBlur={handleTitleBlur}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              (e.currentTarget.nextElementSibling as HTMLElement | null)?.focus();
            }
          }}
          placeholder="Untitled"
          className="w-full text-xl font-semibold bg-transparent outline-none placeholder:text-muted-foreground/30 border-none"
        />

        {/* Tags row + journal-001 'Talk it out' button */}
        <div className="flex flex-wrap items-center gap-1.5">
          {tags.map((tag) => (
            <TagPill key={tag.id} tag={tag} onRemove={() => removeTag(tag.id)} />
          ))}
          <TagAdder currentTagIds={tagIds} onAdd={addTag} />
          {!isNew &&
            noteData &&
            aiEnabled &&
            isTodayJournalEntry(
              noteData.collection_kind,
              noteData.title,
              noteData.created_at,
            ) && (
              <button
                type="button"
                onClick={() => setJournalOpen(true)}
                className="ml-2 inline-flex items-center gap-1.5 rounded-full border border-primary/40 bg-primary/5 px-3 py-1 text-xs font-medium text-primary hover:bg-primary/10 transition-colors cursor-pointer"
                title="Start a guided journal session for today's entry"
              >
                <Sparkles className="h-3 w-3" />
                Talk it out
              </button>
            )}
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

        {/* Backlinks */}
        <div className="border-t pt-4 mt-2">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">
            Linked here
          </p>
          <BacklinksPanel backlinks={backlinks} onNavigate={onNavigate} />
        </div>
      </div>

      {/* journal-001: 'Talk it out' overlay. Renders only when explicitly
          opened, so the note editor stays unchanged for everything else. */}
      {journalOpen && noteData && (
        <JournalSession
          noteId={noteData.id}
          noteTitle={noteData.title || "Today"}
          onClose={() => setJournalOpen(false)}
          onSaved={(savedNoteId) => {
            setJournalOpen(false);
            // Refresh the note so the appended summary appears in the
            // editor. Invalidate both the singular and the list query.
            qc.invalidateQueries({ queryKey: ["get", "/notes/{note_id}", { params: { path: { note_id: savedNoteId } } }] });
            qc.invalidateQueries({ queryKey: ["get", "/notes"] });
          }}
        />
      )}
    </div>
  );
}
