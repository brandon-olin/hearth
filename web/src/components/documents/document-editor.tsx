"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useThemeCustomizer } from "@/lib/theme/context";
import { isThemeDark } from "@/lib/theme/presets";
import { $api } from "@/lib/api/query";
import {
  useCreateBlockNote,
  SuggestionMenuController,
  getDefaultReactSlashMenuItems,
  createReactBlockSpec,
} from "@blocknote/react";
import { BlockNoteView } from "@blocknote/shadcn";
import { BlockNoteSchema, defaultBlockSpecs } from "@blocknote/core/blocks";
import { filterSuggestionItems } from "@blocknote/core/extensions";
import { DocumentSideMenuController } from "./document-side-menu";
import { uploadImageFile } from "@/lib/api/upload";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Loader2, Check, Trash2, FilePlus, FileText, ChevronRight } from "lucide-react";
import { VisibilityPicker, type Visibility } from "@/components/visibility-picker";
import type { Block } from "@blocknote/core";
import "@blocknote/core/fonts/inter.css";
import "@blocknote/shadcn/style.css";

// ── Page link custom block ─────────────────────────────────────────────────────

/**
 * Rendered inside the editor whenever a /page block exists.
 * Using a named component so useRouter() hooks are valid here.
 */
function PageLinkRenderer({ block }: { block: any }) {
  const router = useRouter();
  const { docId, title } = block.props as { docId: string; title: string };
  return (
    <div
      contentEditable={false}
      className="group flex items-center gap-2 w-full px-3 py-2 rounded-md border border-border/60 bg-muted/20 hover:bg-muted/50 cursor-pointer select-none text-sm font-medium text-foreground transition-colors"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        if (docId) router.push(`/documents/${docId}`);
      }}
    >
      <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
      <span className="flex-1 min-w-0 truncate">{title || "Untitled"}</span>
      <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
    </div>
  );
}

const pageLinkBlockSpec = createReactBlockSpec(
  {
    type: "pageLinkBlock" as const,
    propSchema: {
      docId: { default: "" },
      title: { default: "Untitled" },
    },
    content: "none" as const,
  },
  {
    render: (props: any) => <PageLinkRenderer block={props.block} />,
  },
)();

// Extended schema — defined at module level so it's stable across renders.
const docSchema = BlockNoteSchema.create({
  blockSpecs: { ...defaultBlockSpecs, pageLinkBlock: pageLinkBlockSpec as any },
});

// ── Toggle-block pre-opener ────────────────────────────────────────────────────

type SaveState = "idle" | "saving" | "saved";

/**
 * BlockNote stores toggle open/close state in localStorage under the key
 * `toggle-{blockId}`, defaulting to closed when no entry exists.
 *
 * On first open of a document, pre-populate localStorage so all toggle
 * blocks that the user hasn't explicitly interacted with start expanded.
 * We only write if there is no existing entry — so user collapses are
 * respected across navigations.
 */
function preOpenToggleBlocks(blocks: Block[]): void {
  for (const block of blocks) {
    const isToggle =
      block.type === "toggleListItem" ||
      (block.type === "heading" && (block.props as Record<string, unknown>).isToggleable === true);

    if (isToggle) {
      const key = `toggle-${block.id}`;
      if (localStorage.getItem(key) === null) {
        localStorage.setItem(key, "true");
      }
    }

    if (block.children?.length) {
      preOpenToggleBlocks(block.children as Block[]);
    }
  }
}

// ── Editor inner (keyed per document) ─────────────────────────────────────────

function EditorInner({ documentId }: { documentId: string }) {
  const qc = useQueryClient();
  const router = useRouter();
  const { config } = useThemeCustomizer();
  const bnTheme = isThemeDark(config) ? "dark" : "light";
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const titleRef = useRef<string>("");
  const [title, setTitle] = useState("");
  const [visibility, setVisibility] = useState<Visibility>("personal");
  const [sharedWith, setSharedWith] = useState<string[]>([]);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [isCreatingSubpage, setIsCreatingSubpage] = useState(false);

  const { data, isLoading } = $api.useQuery(
    "get",
    "/documents/{doc_id}",
    { params: { path: { doc_id: documentId } } },
  );

  const { mutateAsync: patchDocument } = $api.useMutation("patch", "/documents/{doc_id}");
  const { mutateAsync: archiveDocument } = $api.useMutation("delete", "/documents/{doc_id}");
  const { mutateAsync: createDocument } = $api.useMutation("post", "/documents");

  const editor = useCreateBlockNote({
    schema: docSchema as any,
    uploadFile: uploadImageFile,
  });

  // Once data loads, populate title and editor content.
  const initialised = useRef(false);
  useEffect(() => {
    if (!data || initialised.current) return;
    initialised.current = true;

    const loadedTitle = data.title ?? "";
    setTitle(loadedTitle);
    titleRef.current = loadedTitle;
    setVisibility((data.visibility as Visibility) ?? "personal");
    setSharedWith(data.shared_with_user_ids ?? []);

    const blocks = (data.editor_json as { blocks?: Block[] } | null)?.blocks;
    if (blocks?.length) {
      preOpenToggleBlocks(blocks);
      (editor as any).replaceBlocks(editor.document, blocks);
    } else if (data.source_markdown) {
      const converted = editor.tryParseMarkdownToBlocks(data.source_markdown);
      if (converted.length) {
        preOpenToggleBlocks(converted as Block[]);
        (editor as any).replaceBlocks(editor.document, converted);
        patchDocument({
          params: { path: { doc_id: documentId } },
          body: { editor_json: { blocks: editor.document as unknown as Record<string, unknown>[] } },
        }).catch(() => {/* best-effort */});
      }
    }
  }, [data, editor, documentId, patchDocument]);

  // Debounced save
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

  async function handleVisibilityChange(v: Visibility, sw: string[]) {
    setVisibility(v);
    setSharedWith(sw);
    try {
      await patchDocument({
        params: { path: { doc_id: documentId } },
        body: { visibility: v, shared_with_user_ids: sw },
      });
    } catch { /* ignore */ }
  }

  async function handleDelete() {
    setIsDeleting(true);
    try {
      await archiveDocument({ params: { path: { doc_id: documentId as any } } });
      qc.invalidateQueries({ queryKey: ["get", "/documents"] });
      setDeleteOpen(false);
      router.push("/documents");
    } finally {
      setIsDeleting(false);
    }
  }

  async function handleNewSubpage() {
    setIsCreatingSubpage(true);
    try {
      const doc = await createDocument({
        body: { title: "Untitled", kind: "page", parent_id: documentId as any },
      });
      qc.invalidateQueries({ queryKey: ["get", "/documents"] });
      if (doc?.id) router.push(`/documents/${doc.id}`);
    } finally {
      setIsCreatingSubpage(false);
    }
  }

  // Called from /page slash menu item
  function insertPageLinkBlock() {
    const cursorBlock = editor.getTextCursorPosition().block;
    createDocument({
      body: { title: "Untitled", kind: "page", parent_id: documentId as any },
    })
      .then((newDoc) => {
        if (!newDoc?.id) return;
        qc.invalidateQueries({ queryKey: ["get", "/documents"] });
        (editor as any).insertBlocks(
          [{ type: "pageLinkBlock", props: { docId: String(newDoc.id), title: newDoc.title } }],
          cursorBlock,
          "after",
        );
      })
      .catch(console.error);
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
      <div className="flex items-start gap-3 px-10 pt-10 pb-2">
        <input
          className="flex-1 text-3xl font-bold bg-transparent border-none outline-none placeholder:text-muted-foreground/40 text-foreground"
          placeholder="Untitled"
          value={title}
          onChange={handleTitleChange}
          onKeyDown={handleTitleKeyDown}
        />

        {/* Save indicator + action buttons */}
        <div className="flex items-center gap-1 shrink-0 pt-1">
          <span className="text-xs text-muted-foreground w-12 text-right mr-1">
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

          {/* New subpage */}
          <button
            type="button"
            onClick={handleNewSubpage}
            disabled={isCreatingSubpage}
            title="New subpage"
            className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors disabled:opacity-50"
          >
            {isCreatingSubpage ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <FilePlus className="h-4 w-4" />
            )}
          </button>

          {/* Delete — modal confirmation */}
          <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
            <AlertDialogTrigger
              title="Delete page"
              className="p-1.5 rounded-md text-muted-foreground hover:text-destructive hover:bg-muted/60 transition-colors"
            >
              <Trash2 className="h-4 w-4" />
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Delete "{title || "Untitled"}"?</AlertDialogTitle>
                <AlertDialogDescription>
                  This page will be archived and removed from your document tree.
                  Any subpages will remain but move to the root level.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel disabled={isDeleting}>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  onClick={handleDelete}
                  disabled={isDeleting}
                  variant="destructive"
                >
                  {isDeleting ? (
                    <span className="flex items-center gap-2">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Deleting…
                    </span>
                  ) : (
                    "Delete"
                  )}
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>

      {/* Visibility */}
      <div className="px-10 pb-3">
        <VisibilityPicker
          value={visibility}
          sharedWith={sharedWith}
          onChange={handleVisibilityChange}
        />
      </div>

      {/* BlockNote editor */}
      <div
        className="flex-1 overflow-auto px-6 pb-10"
        onClick={(e) => {
          const anchor = (e.target as Element).closest("a");
          if (!anchor) return;
          const href = anchor.getAttribute("href") ?? "";
          if (href.startsWith("/documents/")) {
            e.preventDefault();
            router.push(href);
          }
        }}
      >
        <BlockNoteView
          editor={editor as any}
          onChange={scheduleSave}
          theme={bnTheme}
          sideMenu={false}
        >
          {/* Custom slash menu with /page item */}
          <SuggestionMenuController
            triggerCharacter="/"
            getItems={async (query) =>
              filterSuggestionItems(
                [
                  ...getDefaultReactSlashMenuItems(editor as any),
                  {
                    title: "Page",
                    aliases: ["page", "subpage"],
                    group: "Navigation",
                    icon: <FileText size={18} />,
                    subtext: "Insert a link to a new subpage",
                    onItemClick: insertPageLinkBlock,
                  },
                ],
                query,
              )
            }
          />
          <DocumentSideMenuController />
        </BlockNoteView>
      </div>
    </div>
  );
}

export function DocumentEditor({ documentId }: { documentId: string }) {
  return <EditorInner key={documentId} documentId={documentId} />;
}
