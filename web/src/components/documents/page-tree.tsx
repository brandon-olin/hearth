"use client";

import { useState, useCallback, useRef } from "react";
import { useRouter, usePathname } from "next/navigation";

// Module-level set: survives component unmounts when navigating between sections.
// Stores IDs of all nodes the user has explicitly expanded.
const _expandedIds = new Set<string>();
import { $api } from "@/lib/api/query";
import { apiBaseUrl } from "@/lib/api/client";
import { useQueryClient } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import {
  ChevronRight,
  ChevronDown,
  SquareMinus,
  FileText,
  Plus,
  Loader2,
  Upload,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { NotionImportDialog } from "@/components/documents/notion-import-dialog";
import type { components } from "@/lib/api/schema";

type DocumentSummary = components["schemas"]["DocumentSummary"];

interface TreeNode {
  doc: DocumentSummary;
  children: TreeNode[];
}

function buildTree(items: DocumentSummary[]): TreeNode[] {
  const map = new Map<string, TreeNode>();
  const roots: TreeNode[] = [];

  for (const doc of items) {
    map.set(doc.id, { doc, children: [] });
  }

  for (const doc of items) {
    const node = map.get(doc.id)!;
    if (doc.parent_id && map.has(doc.parent_id)) {
      map.get(doc.parent_id)!.children.push(node);
    } else {
      roots.push(node);
    }
  }

  return roots;
}

/** Returns true if targetId is a descendant of ancestorId in the flat items list. */
function isDescendantOf(items: DocumentSummary[], ancestorId: string, targetId: string): boolean {
  const children = items.filter((d) => d.parent_id === ancestorId);
  if (children.some((c) => c.id === targetId)) return true;
  return children.some((c) => isDescendantOf(items, c.id, targetId));
}

interface DragState {
  draggingId: string | null;
  dropTargetId: string | null;
  onDragStart: (id: string) => void;
  onDragOver: (id: string) => void;
  onDragLeave: () => void;
  onDrop: (targetId: string | null) => void;
  onDragEnd: () => void;
}

function TreeNodeRow({
  node,
  depth,
  activePath,
  onCreateChild,
  drag,
}: {
  node: TreeNode;
  depth: number;
  activePath: string;
  onCreateChild: (parentId: string) => void;
  drag: DragState;
}) {
  const router = useRouter();
  const isActive = activePath === `/documents/${node.doc.id}`;
  const [expanded, setExpanded] = useState(() => _expandedIds.has(node.doc.id));
  const hasChildren = node.children.length > 0;

  const isDragging = drag.draggingId === node.doc.id;
  const isDropTarget = drag.dropTargetId === node.doc.id && drag.draggingId !== node.doc.id;
  const dragStartedRef = useRef(false);

  const toggle = useCallback(() => {
    setExpanded((v) => {
      const next = !v;
      if (next) _expandedIds.add(node.doc.id);
      else _expandedIds.delete(node.doc.id);
      return next;
    });
  }, [node.doc.id]);

  return (
    <li>
      <div
        draggable
        onDragStart={(e) => {
          e.dataTransfer.effectAllowed = "move";
          e.dataTransfer.setData("text/plain", node.doc.id);
          dragStartedRef.current = true;
          drag.onDragStart(node.doc.id);
        }}
        onDragOver={(e) => {
          e.preventDefault();
          e.dataTransfer.dropEffect = "move";
          drag.onDragOver(node.doc.id);
        }}
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node)) {
            drag.onDragLeave();
          }
        }}
        onDrop={(e) => {
          e.preventDefault();
          drag.onDrop(node.doc.id);
        }}
        onDragEnd={(e) => {
          drag.onDragEnd();
          setTimeout(() => { dragStartedRef.current = false; }, 100);
        }}
        className={cn(
          "group flex items-center gap-1 rounded-md pr-1 cursor-pointer select-none transition-all",
          isActive ? "bg-accent text-accent-foreground" : "hover:bg-muted/60 text-foreground",
          isDragging && "opacity-40",
          isDropTarget && "ring-2 ring-primary/50 bg-primary/5",
        )}
        style={{ paddingLeft: `${8 + depth * 16}px` }}
        onClick={() => {
          if (dragStartedRef.current) return;
          router.push(`/documents/${node.doc.id}`);
        }}
      >
        {/* Expand / collapse toggle */}
        <button
          type="button"
          className="p-0.5 rounded hover:bg-muted text-muted-foreground hover:text-foreground shrink-0"
          onClick={(e) => {
            e.stopPropagation();
            toggle();
          }}
        >
          {hasChildren ? (
            expanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )
          ) : (
            <span className="w-3 h-3 inline-block" />
          )}
        </button>

        {node.doc.icon ? (
          <span className="shrink-0 text-sm leading-none">{node.doc.icon}</span>
        ) : (
          <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        )}

        <span className="flex-1 min-w-0 truncate py-1.5 text-sm">
          {node.doc.title || "Untitled"}
        </span>

        {/* Add child button — appears on hover */}
        <button
          type="button"
          className="invisible group-hover:visible p-0.5 rounded hover:bg-muted text-muted-foreground hover:text-foreground shrink-0"
          onClick={(e) => {
            e.stopPropagation();
            onCreateChild(node.doc.id);
          }}
          title="New page inside"
        >
          <Plus className="h-3 w-3" />
        </button>
      </div>

      {hasChildren && expanded && (
        <ul>
          {node.children.map((child) => (
            <TreeNodeRow
              key={child.doc.id}
              node={child}
              depth={depth + 1}
              activePath={activePath}
              onCreateChild={onCreateChild}
              drag={drag}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

export function PageTree() {
  const router = useRouter();
  const pathname = usePathname();
  const qc = useQueryClient();
  const [isCreating, setIsCreating] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [collapseKey, setCollapseKey] = useState(0);

  // Drag-and-drop state
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dropTargetId, setDropTargetId] = useState<string | null>(null);

  const { data, isLoading } = $api.useQuery("get", "/documents", {
    params: { query: { include_archived: false } },
  });

  const { mutateAsync: createDocument } = $api.useMutation("post", "/documents");
  const { mutateAsync: patchDocument } = $api.useMutation("patch", "/documents/{doc_id}");

  const items = data?.items ?? [];
  const tree = buildTree(items);

  async function handleCreate(parentId?: string) {
    setIsCreating(true);
    try {
      const doc = await createDocument({
        body: { title: "Untitled", kind: "page", parent_id: parentId ?? null, visibility: "personal", shared_with_user_ids: [] },
      });
      qc.invalidateQueries({ queryKey: ["get", "/documents"] });
      if (doc?.id) router.push(`/documents/${doc.id}`);
    } finally {
      setIsCreating(false);
    }
  }

  async function handleDeleteAll() {
    setIsDeleting(true);
    try {
      const token = (await import("@/lib/auth/token")).getAccessToken();
      const headers: Record<string, string> = {};
      if (token) headers["Authorization"] = `Bearer ${token}`;
      await fetch(`${apiBaseUrl}/documents`, { method: "DELETE", headers, credentials: "same-origin" });
      qc.invalidateQueries({ queryKey: ["get", "/documents"] });
      router.push("/documents");
    } finally {
      setIsDeleting(false);
      setDeleteConfirm(false);
    }
  }

  async function handleDrop(targetId: string | null) {
    if (!draggingId) return;
    if (draggingId === targetId) return;
    if (targetId && isDescendantOf(items, draggingId, targetId)) return; // cycle guard
    try {
      await patchDocument({
        params: { path: { doc_id: draggingId as any } },
        body: { parent_id: (targetId ?? null) as any },
      });
      qc.invalidateQueries({ queryKey: ["get", "/documents"] });
    } catch (e) {
      console.error("Failed to reparent document", e);
    }
    setDraggingId(null);
    setDropTargetId(null);
  }

  const drag: DragState = {
    draggingId,
    dropTargetId,
    onDragStart: (id) => setDraggingId(id),
    onDragOver: (id) => setDropTargetId(id),
    onDragLeave: () => setDropTargetId(null),
    onDrop: (targetId) => handleDrop(targetId),
    onDragEnd: () => { setDraggingId(null); setDropTargetId(null); },
  };

  return (
    <>
      {showImport && <NotionImportDialog onClose={() => setShowImport(false)} />}
      <div className="flex flex-col h-full">
        {/* Header */}
        <div className="flex items-center justify-between px-3 py-3 border-b shrink-0">
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
            Documents
          </span>
          <div className="flex items-center gap-0.5">
            {deleteConfirm ? (
              <span className="flex items-center gap-1 text-xs text-destructive">
                <button
                  className="underline underline-offset-2 hover:opacity-70"
                  onClick={handleDeleteAll}
                  disabled={isDeleting}
                >
                  {isDeleting ? "Deleting…" : "Delete all?"}
                </button>
                <button
                  className="opacity-50 hover:opacity-100"
                  onClick={() => setDeleteConfirm(false)}
                  disabled={isDeleting}
                >
                  ✕
                </button>
              </span>
            ) : (
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 text-muted-foreground hover:text-destructive"
                onClick={() => setDeleteConfirm(true)}
                title="Delete all documents"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => {
                _expandedIds.clear();
                setCollapseKey((k) => k + 1);
              }}
              title="Collapse all"
            >
              <SquareMinus className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => setShowImport(true)}
              title="Import pages"
            >
              <Upload className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => handleCreate()}
              disabled={isCreating}
              title="New page"
            >
              {isCreating ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Plus className="h-3.5 w-3.5" />
              )}
            </Button>
          </div>
        </div>

        {/* Tree */}
        <div
          className="flex-1 overflow-y-auto py-2 px-1"
          onDragOver={(e) => {
            // Allow drop on the empty tree area → move to root
            if (draggingId) {
              e.preventDefault();
              e.dataTransfer.dropEffect = "move";
            }
          }}
          onDrop={(e) => {
            e.preventDefault();
            // Only fire if drop landed on tree background (not a row)
            const target = e.target as HTMLElement;
            if (!target.closest("li")) {
              handleDrop(null);
            }
          }}
        >
          {isLoading && (
            <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              Loading…
            </div>
          )}

          {!isLoading && tree.length === 0 && (
            <p className="px-3 py-2 text-xs text-muted-foreground">No pages yet.</p>
          )}

          {/* "Move to root" drop zone — shown only while dragging */}
          {draggingId && (
            <div
              className={cn(
                "mx-2 mb-1 rounded-md border-2 border-dashed text-xs text-center py-1 transition-colors cursor-default",
                dropTargetId === null
                  ? "border-primary/60 bg-primary/5 text-primary"
                  : "border-border/50 text-muted-foreground",
              )}
              onDragOver={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setDropTargetId(null);
              }}
              onDrop={(e) => {
                e.preventDefault();
                e.stopPropagation();
                handleDrop(null);
              }}
            >
              Move to root
            </div>
          )}

          <ul>
            {tree.map((node) => (
              <TreeNodeRow
                key={`${node.doc.id}-${collapseKey}`}
                node={node}
                depth={0}
                activePath={pathname}
                onCreateChild={(parentId) => handleCreate(parentId)}
                drag={drag}
              />
            ))}
          </ul>
        </div>
      </div>
    </>
  );
}
