"use client";

/**
 * NotionImportDialog
 *
 * Accepts a Notion "Export as Markdown & CSV" zip file, parses the folder
 * structure to reconstruct page hierarchy, converts each .md file to
 * BlockNote JSON, and POSTs the full set to POST /documents/import.
 *
 * Notion export structure:
 *   Export-<date>/
 *     Page Title <32-hex>.md
 *     Page Title <32-hex>/
 *       Sub Page <32-hex>.md
 *       ...
 *
 * Pages that have children have BOTH a .md sibling and a same-name directory.
 */

import { useRef, useState } from "react";
import JSZip from "jszip";
import { useCreateBlockNote } from "@blocknote/react";
import { useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import { Upload, Loader2, CheckCircle2, AlertCircle, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Block } from "@blocknote/core";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ParsedPage {
  clientId: string;       // stable key used for parent resolution
  clientParentId: string | null;
  title: string;
  markdown: string;
}

type ImportState =
  | { phase: "idle" }
  | { phase: "parsing" }
  | { phase: "converting"; done: number; total: number }
  | { phase: "uploading" }
  | { phase: "done"; created: number; skipped: number }
  | { phase: "error"; message: string };

// ── Notion filename helpers ───────────────────────────────────────────────────

// Notion appends a 32-char hex ID (+ optional space) to every file/folder name.
// e.g.  "My Recipe abc123def456789012345678901234.md"
//       "Sub Page abc123def456789012345678901234"
const NOTION_UUID_RE = /\s+[0-9a-f]{32}$/i;

function stripNotionId(name: string): string {
  return name.replace(NOTION_UUID_RE, "").trim();
}

function parseTitleFromPath(filePath: string): string {
  // Get the final segment (filename without extension)
  const segments = filePath.split("/");
  const filename = segments[segments.length - 1];
  const withoutExt = filename.replace(/\.md$/i, "");
  const title = stripNotionId(withoutExt);
  return title || "Untitled";
}

/**
 * Strips the Notion UUID from each path segment to produce a normalised path
 * used for hierarchy matching.
 *
 *   "Export/My Page abc123/Sub Page def456.md"
 *   → "My Page/Sub Page.md"
 */
function normalisePath(filePath: string): string {
  return filePath
    .split("/")
    .map((seg, i, arr) => {
      const isLast = i === arr.length - 1;
      if (isLast && seg.toLowerCase().endsWith(".md")) {
        return stripNotionId(seg.replace(/\.md$/i, "")) + ".md";
      }
      return stripNotionId(seg);
    })
    .filter(Boolean) // drop empty leading segment if path starts with /
    .join("/");
}

// ── Zip parser ────────────────────────────────────────────────────────────────

async function parseNotionZip(file: File): Promise<ParsedPage[]> {
  const zip = await JSZip.loadAsync(file);
  const pages: ParsedPage[] = [];

  // Collect all .md files, ignoring CSV databases and __MACOSX junk.
  const mdFiles: Array<{ path: string; file: JSZip.JSZipObject }> = [];

  zip.forEach((relativePath, zipEntry) => {
    if (
      !zipEntry.dir &&
      relativePath.toLowerCase().endsWith(".md") &&
      !relativePath.startsWith("__MACOSX")
    ) {
      mdFiles.push({ path: relativePath, file: zipEntry });
    }
  });

  // Build a map of normalised directory path → client ID so children can find
  // their parent.  A page at "Export/My Page abc/Sub Page def.md" has its
  // parent directory "Export/My Page abc/" which normalises to "My Page".
  //
  // We assign a stable clientId per file path up front so we can reference
  // them before all files are processed.
  const normalised: Array<{ path: string; norm: string; id: string }> =
    mdFiles.map((f, i) => ({
      path: f.path,
      norm: normalisePath(f.path),
      id: `import-${i}`,
    }));

  // Build a lookup: normalised directory → id
  // e.g. "My Page" → "import-0"
  const dirToId = new Map<string, string>();
  for (const entry of normalised) {
    // The "directory" for this file = norm without trailing ".md" segment
    const parts = entry.norm.split("/");
    parts.pop(); // remove filename
    const dir = parts.join("/");
    // The key is the stem of this file (without .md), relative to its own dir
    const stem = entry.norm.replace(/\.md$/i, "");
    dirToId.set(stem, entry.id);
  }

  // Read content and compute parent IDs
  for (let i = 0; i < mdFiles.length; i++) {
    const { path, file } = mdFiles[i];
    const { norm, id } = normalised[i];

    const markdown = await file.async("string");
    const title = parseTitleFromPath(path);

    // Determine parent: the normalised path without the last segment and ".md"
    const parts = norm.split("/");
    parts.pop(); // remove "Sub Page.md"
    const parentDir = parts.join("/"); // e.g. "My Page"

    const clientParentId = parentDir ? (dirToId.get(parentDir) ?? null) : null;

    pages.push({
      clientId: id,
      clientParentId,
      title,
      markdown,
    });
  }

  return pages;
}

// ── Component ─────────────────────────────────────────────────────────────────

interface Props {
  onClose: () => void;
}

export function NotionImportDialog({ onClose }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<ImportState>({ phase: "idle" });
  const editor = useCreateBlockNote();
  const qc = useQueryClient();

  const { mutateAsync: importDocuments } = $api.useMutation(
    "post",
    "/documents/import"
  );

  async function handleFile(file: File) {
    if (!file.name.toLowerCase().endsWith(".zip")) {
      setState({ phase: "error", message: "Please select a .zip file exported from Notion." });
      return;
    }

    try {
      // 1. Parse the zip
      setState({ phase: "parsing" });
      const pages = await parseNotionZip(file);

      if (pages.length === 0) {
        setState({ phase: "error", message: "No markdown pages found in this zip." });
        return;
      }

      // 2. Convert markdown → BlockNote JSON for each page
      setState({ phase: "converting", done: 0, total: pages.length });

      const items: Array<{
        client_id: string;
        client_parent_id: string | null;
        title: string;
        source_markdown: string;
        editor_json: { blocks: Block[] } | null;
      }> = [];

      for (let i = 0; i < pages.length; i++) {
        const page = pages[i];
        let blocks: Block[] | null = null;
        try {
          blocks = editor.tryParseMarkdownToBlocks(page.markdown) as Block[];
        } catch {
          // If conversion fails, we still import with source_markdown only.
        }

        items.push({
          client_id: page.clientId,
          client_parent_id: page.clientParentId,
          title: page.title,
          source_markdown: page.markdown,
          editor_json: blocks && blocks.length > 0 ? { blocks } : null,
        });

        setState({ phase: "converting", done: i + 1, total: pages.length });
      }

      // 3. POST to API
      setState({ phase: "uploading" });

      const result = await importDocuments({
        body: { items },
      });

      qc.invalidateQueries({ queryKey: ["get", "/documents"] });

      setState({
        phase: "done",
        created: result.created,
        skipped: result.skipped,
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setState({ phase: "error", message: msg });
    }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }

  const isWorking =
    state.phase === "parsing" ||
    state.phase === "converting" ||
    state.phase === "uploading";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div
        className="bg-card text-card-foreground rounded-xl shadow-xl w-full max-w-md mx-4 p-6 flex flex-col gap-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">Import from Notion</h2>
          <button
            type="button"
            onClick={onClose}
            disabled={isWorking}
            className="text-muted-foreground hover:text-foreground p-1 rounded"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Instructions */}
        {state.phase === "idle" && (
          <p className="text-sm text-muted-foreground">
            Export your Notion pages as <strong>Markdown &amp; CSV</strong>{" "}
            (Settings → Export → Markdown &amp; CSV), then upload the zip here.
            Pages and their hierarchy are preserved.
          </p>
        )}

        {/* Drop zone */}
        {(state.phase === "idle" || state.phase === "error") && (
          <div
            className="border-2 border-dashed border-border rounded-lg p-8 flex flex-col items-center gap-3 cursor-pointer hover:border-primary/50 transition-colors"
            onClick={() => inputRef.current?.click()}
            onDrop={handleDrop}
            onDragOver={(e) => e.preventDefault()}
          >
            <Upload className="h-8 w-8 text-muted-foreground" />
            <p className="text-sm text-center text-muted-foreground">
              Drop your Notion export zip here, or click to browse
            </p>
            <input
              ref={inputRef}
              type="file"
              accept=".zip"
              className="sr-only"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleFile(file);
              }}
            />
          </div>
        )}

        {/* Error */}
        {state.phase === "error" && (
          <div className="flex items-start gap-2 text-destructive text-sm">
            <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
            <span>{state.message}</span>
          </div>
        )}

        {/* Progress states */}
        {state.phase === "parsing" && (
          <ProgressRow icon={<Loader2 className="h-4 w-4 animate-spin" />} label="Reading zip…" />
        )}

        {state.phase === "converting" && (
          <ProgressRow
            icon={<Loader2 className="h-4 w-4 animate-spin" />}
            label={`Converting pages… ${state.done} / ${state.total}`}
          />
        )}

        {state.phase === "uploading" && (
          <ProgressRow icon={<Loader2 className="h-4 w-4 animate-spin" />} label="Saving to your library…" />
        )}

        {/* Done */}
        {state.phase === "done" && (
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2 text-sm text-green-600">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              <span>
                Import complete — {state.created} page{state.created !== 1 ? "s" : ""} added
                {state.skipped > 0 ? `, ${state.skipped} skipped` : ""}.
              </span>
            </div>
            <Button size="sm" onClick={onClose}>
              Done
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

function ProgressRow({
  icon,
  label,
}: {
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground">
      {icon}
      <span>{label}</span>
    </div>
  );
}
