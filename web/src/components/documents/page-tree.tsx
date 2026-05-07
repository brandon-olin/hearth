"use client";

import { useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { $api } from "@/lib/api/query";
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

function TreeNodeRow({
  node,
  depth,
  activePath,
  onCreateChild,
}: {
  node: TreeNode;
  depth: number;
  activePath: string;
  onCreateChild: (parentId: string) => void;
}) {
  const router = useRouter();
  const isActive = activePath === `/documents/${node.doc.id}`;
  const [expanded, setExpanded] = useState(false);
  const hasChildren = node.children.length > 0;

  return (
    <li>
      <div
        className={cn(
          "group flex items-center gap-1 rounded-md pr-1 cursor-pointer select-none",
          isActive
            ? "bg-accent text-accent-foreground"
            : "hover:bg-muted/60 text-foreground"
        )}
        style={{ paddingLeft: `${8 + depth * 16}px` }}
        onClick={() => router.push(`/documents/${node.doc.id}`)}
      >
        {/* Expand / collapse toggle */}
        <button
          type="button"
          className="p-0.5 rounded hover:bg-muted text-muted-foreground hover:text-foreground shrink-0"
          onClick={(e) => {
            e.stopPropagation();
            setExpanded((v) => !v);
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

        <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />

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
  // Incrementing this remounts all TreeNodeRows, resetting their expanded state to false.
  const [collapseKey, setCollapseKey] = useState(0);

  const { data, isLoading } = $api.useQuery("get", "/documents", {
    params: { query: { include_archived: false } },
  });

  const { mutateAsync: createDocument } = $api.useMutation("post", "/documents");

  const items = data?.items ?? [];
  const tree = buildTree(items);

  async function handleCreate(parentId?: string) {
    setIsCreating(true);
    try {
      const doc = await createDocument({
        body: {
          title: "Untitled",
          kind: "page",
          parent_id: parentId ?? null,
        },
      });
      qc.invalidateQueries({ queryKey: ["get", "/documents"] });
      if (doc?.id) {
        router.push(`/documents/${doc.id}`);
      }
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
      await fetch("/api/documents", { method: "DELETE", headers, credentials: "same-origin" });
      qc.invalidateQueries({ queryKey: ["get", "/documents"] });
      router.push("/documents");
    } finally {
      setIsDeleting(false);
      setDeleteConfirm(false);
    }
  }

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
            onClick={() => setCollapseKey((k) => k + 1)}
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
      <div className="flex-1 overflow-y-auto py-2 px-1">
        {isLoading && (
          <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            Loading…
          </div>
        )}

        {!isLoading && tree.length === 0 && (
          <p className="px-3 py-2 text-xs text-muted-foreground">
            No pages yet.
          </p>
        )}

        <ul>
          {tree.map((node) => (
            <TreeNodeRow
              key={`${node.doc.id}-${collapseKey}`}
              node={node}
              depth={0}
              activePath={pathname}
              onCreateChild={(parentId) => handleCreate(parentId)}
            />
          ))}
        </ul>
      </div>
    </div>
    </>
  );
}
