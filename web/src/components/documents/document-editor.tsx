"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import { useCreateBlockNote } from "@blocknote/react";
import { BlockNoteView } from "@blocknote/shadcn";
import { Loader2, Check } from "lucide-react";
import type { Block } from "@blocknote/core";
import "@blocknote/core/fonts/inter.css";
import "@blocknote/shadcn/style.css";

type SaveState = "idle" | "saving" | "saved";

// Inner component is keyed on documentId so it fully remounts on navigation.
function EditorInner({ documentId }: { documentId: string }) {
  const qc = useQueryClient();
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const titleRef = useRef<string>("");
  const [title, setTitle] = useState("");

  const { data, isLoading } = $api.useQuery(
    "get",
    "/documents/{doc_id}",
    { params: { path: { doc_id: documentId } } }
  );

  const { mutateAsync: patchDocument } = $api.useMutation(
    "patch",
    "/documents/{doc_id}"
  );

  // Initialise editor (empty for now; we'll replace content once data arrives)
  const editor = useCreateBlockNote();

  // Once data loads, populate title and editor content.
  const initialised = useRef(false);
  useEffect(() => {
    if (!data || initialised.current) return;
    initialised.current = true;

    const loadedTitle = data.title ?? "";
    setTitle(loadedTitle);
    titleRef.current = loadedTitle;

    const blocks = (data.editor_json as { blocks?: Block[] } | null)?.blocks;
    if (blocks?.length) {
      // Already converted — load directly.
      editor.replaceBlocks(editor.document, blocks);
    } else if (data.source_markdown) {
      // Imported from markdown — convert on first open and save back so
      // subsequent loads are instant.
      const converted = editor.tryParseMarkdownToBlocks(data.source_markdown);
      if (converted.length) {
        editor.replaceBlocks(editor.document, converted);
        // Persist the converted JSON so we don't re-parse on every open.
        patchDocument({
          params: { path: { doc_id: documentId } },
          body: {
            editor_json: { blocks: editor.document as unknown as Record<string, unknown>[] },
          },
        }).catch(() => {/* best-effort */});
      }
    }
  }, [data, editor, documentId, patchDocument]);

  // Debounced save — reads from refs to avoid stale closures.
  const scheduleSave = useCallback(() => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(async () => {
      setSaveState("saving");
      try {
        await patchDocument({
          params: { path: { doc_id: documentId } },
          body: {
            title: titleRef.current,
            editor_json: { blocks: editor.document as unknown as Record<string, unknown>[] },
          },
        });
        qc.invalidateQueries({ queryKey: ["get", "/documents"] });
        setSaveState("saved");
        setTimeout(() => setSaveState("idle"), 2000);
      } catch {
        setSaveState("idle");
      }
    }, 1500);
  }, [documentId, editor, patchDocument, qc]);

  function handleTitleChange(e: React.ChangeEvent<HTMLInputElement>) {
    setTitle(e.target.value);
    titleRef.current = e.target.value;
    scheduleSave();
  }

  function handleTitleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      editor.focus();
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading…
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Title bar */}
      <div className="flex items-center gap-3 px-10 pt-10 pb-2">
        <input
          className="flex-1 text-3xl font-bold bg-transparent border-none outline-none placeholder:text-muted-foreground/40 text-foreground"
          placeholder="Untitled"
          value={title}
          onChange={handleTitleChange}
          onKeyDown={handleTitleKeyDown}
        />
        {/* Save indicator */}
        <span className="text-xs text-muted-foreground shrink-0 w-12 text-right">
          {saveState === "saving" && (
            <span className="flex items-center gap-1 justify-end">
              <Loader2 className="h-3 w-3 animate-spin" />
              Saving
            </span>
          )}
          {saveState === "saved" && (
            <span className="flex items-center gap-1 justify-end text-green-600">
              <Check className="h-3 w-3" />
              Saved
            </span>
          )}
        </span>
      </div>

      {/* BlockNote editor */}
      <div className="flex-1 overflow-auto px-6 pb-10">
        <BlockNoteView
          editor={editor}
          onChange={scheduleSave}
          theme="light"
        />
      </div>
    </div>
  );
}

export function DocumentEditor({ documentId }: { documentId: string }) {
  // key prop forces full remount when navigating between documents
  return <EditorInner key={documentId} documentId={documentId} />;
}
