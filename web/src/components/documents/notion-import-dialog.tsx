"use client";

/**
 * Markdown import dialog.
 *
 * Accepts a zip of markdown files (Notion, Obsidian, Bear, Logseq, …),
 * reconstructs page hierarchy from the folder structure, strips unresolvable
 * image references, and bulk-POSTs to POST /documents/import.
 *
 * Markdown→BlockNote conversion is intentionally deferred to first open so
 * that the import is fast and doesn't trigger hundreds of image fetch attempts.
 *
 * Notion export structure:
 *   Export-<date>/
 *     Page Title <32-hex>.md
 *     Page Title <32-hex>/
 *       Sub Page <32-hex>.md
 */

import { useRef, useState } from "react";
import JSZip from "jszip";
import { useQueryClient } from "@tanstack/react-query";
import { getAccessToken } from "@/lib/auth/token";
import { Upload, Loader2, CheckCircle2, AlertCircle, X } from "lucide-react";
import { Button } from "@/components/ui/button";

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
  | { phase: "uploading" }
  | { phase: "done"; created: number; skipped: number }
  | { phase: "error"; message: string };

// ── Markdown cleanup ──────────────────────────────────────────────────────────

/**
 * Remove image tags whose src is a local path (no http/https scheme).
 * Notion embeds images as relative paths like `![](image.png)` or
 * `![alt](Folder/image.jpeg)` that will never resolve outside the export.
 * Keeping them causes the browser to fire hundreds of failing fetches when
 * BlockNote later parses the markdown.
 */
function stripLocalImages(md: string): string {
  // Matches ![alt](src) where src does NOT start with http/https/data/ftp.
  return md.replace(/!\[[^\]]*\]\((?!https?:\/\/|data:|ftp:\/\/)[^)]*\)/g, "");
}

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

/**
 * Recursively collects all .md entries from a JSZip instance.
 * Notion wraps large exports as a zip-of-zips (Part-1.zip, Part-2.zip …
 * inside an outer zip). We unpack those inner zips transparently.
 */
async function collectMdFiles(
  zip: JSZip,
  acc: Array<{ path: string; file: JSZip.JSZipObject }>,
): Promise<void> {
  const innerZips: JSZip.JSZipObject[] = [];

  zip.forEach((relativePath, zipEntry) => {
    if (zipEntry.dir || relativePath.startsWith("__MACOSX")) return;

    if (relativePath.toLowerCase().endsWith(".zip")) {
      innerZips.push(zipEntry);
    } else if (relativePath.toLowerCase().endsWith(".md")) {
      acc.push({ path: relativePath, file: zipEntry });
    }
  });

  // Recurse into any nested zips (e.g. Notion's Part-1.zip wrapper).
  for (const innerEntry of innerZips) {
    const innerData = await innerEntry.async("arraybuffer");
    const innerZip = await JSZip.loadAsync(innerData);
    await collectMdFiles(innerZip, acc);
  }
}

async function parseNotionZip(file: File): Promise<ParsedPage[]> {
  const zip = await JSZip.loadAsync(file);
  const pages: ParsedPage[] = [];

  const mdFiles: Array<{ path: string; file: JSZip.JSZipObject }> = [];
  await collectMdFiles(zip, mdFiles);

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

    const raw = await file.async("string");
    const markdown = stripLocalImages(raw);
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
  const qc = useQueryClient();

  async function handleFile(file: File) {
    if (!file.name.toLowerCase().endsWith(".zip")) {
      setState({ phase: "error", message: "Please select a .zip file containing markdown pages." });
      return;
    }

    try {
      // 1. Parse the zip
      setState({ phase: "parsing" });
      const pages = await parseNotionZip(file);

      if (pages.length === 0) {
        setState({
          phase: "error",
          message:
            "No markdown (.md) files found in this zip. Open the browser console (⌘⌥J) to see what paths were detected.",
        });
        return;
      }

      // 2. POST to API — plain fetch so we control method/headers exactly.
      //    markdown→BlockNote conversion is deferred to first open.
      setState({ phase: "uploading" });

      const token = getAccessToken();
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const res = await fetch("/api/documents/bulk-import", {
        method: "POST",
        headers,
        credentials: "same-origin",
        body: JSON.stringify({
          items: pages.map((p) => ({
            client_id: p.clientId,
            client_parent_id: p.clientParentId,
            title: p.title,
            source_markdown: p.markdown,
            editor_json: null,
          })),
        }),
      });

      if (!res.ok) {
        const text = await res.text().catch(() => res.statusText);
        throw new Error(`Import failed (${res.status}): ${text}`);
      }

      const result = await res.json() as { created: number; skipped: number };

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
    state.phase === "uploading";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div
        className="bg-card text-card-foreground rounded-xl shadow-xl w-full max-w-md mx-4 p-6 flex flex-col gap-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">Import pages</h2>
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
          <div className="text-sm text-muted-foreground space-y-2">
            <p>
              Upload a zip of markdown files. Page hierarchy is inferred from
              folder structure. Works with exports from:
            </p>
            <ul className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs pl-1">
              <li>• Notion <span className="text-muted-foreground/60">(Markdown &amp; CSV)</span></li>
              <li>• Obsidian</li>
              <li>• Logseq</li>
              <li>• Bear</li>
              <li>• Craft</li>
              <li>• Any markdown zip</li>
            </ul>
          </div>
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
              Drop your export zip here, or click to browse
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
