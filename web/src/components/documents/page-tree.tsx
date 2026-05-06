"use client";

import { useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { $api } from "@/lib/api/query";
import { useQueryClient } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import {
  ChevronRight,
  ChevronDown,
  FileText,
  Plus,
  Loader2,
  Upload,
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
  const [expanded, setExpanded] = useState(true);
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
              key={node.doc.id}
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
