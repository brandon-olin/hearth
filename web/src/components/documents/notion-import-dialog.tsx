"use client";

/**
 * Markdown import dialog.
 *
 * Accepts a zip of markdown files (Notion, Obsidian, Bear, Logseq, …),
 * reconstructs page hierarchy from the folder structure, strips unresolvable
 * image references, and bulk-POSTs to POST /documents/bulk-import.
 *
 * Three Notion-specific fixes applied during parse:
 *   1. Database-row pages (every line is "key: value") are filtered out.
 *   2. Stub parent pages are auto-created for folders with no matching .md file.
 *   3. Inter-page links ([text](Page hexid.md)) are rewritten to internal
 *      /documents/{uuid} links via a post-import PATCH pass.
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
  clientId: string;
  clientParentId: string | null;
  title: string;
  markdown: string;
}

type ImportState =
  | { phase: "idle" }
  | { phase: "parsing" }
  | { phase: "uploading" }
  | { phase: "rewriting" }
  | { phase: "done"; created: number; skipped: number }
  | { phase: "error"; message: string };

interface ImportResultItem {
  id: string;
  client_id: string;
}

// ── Markdown helpers ──────────────────────────────────────────────────────────

/**
 * Remove image tags whose src is a local path (no http/https scheme).
 * Notion embeds images as relative paths like `![](image.png)` that will
 * never resolve outside the export.
 */
function stripLocalImages(md: string): string {
  return md.replace(/!\[[^\]]*\]\((?!https?:\/\/|data:|ftp:\/\/)[^)]*\)/g, "");
}

/**
 * Fix 1 — Returns true when the entire file content looks like a Notion
 * database row (every non-blank line follows "Key: value" format with no prose
 * content). These are noise from Notion's "Markdown & CSV" export format.
 */
function isDatabaseRow(markdown: string): boolean {
  const lines = markdown.split("\n").map((l) => l.trim()).filter(Boolean);
  if (lines.length < 2) return false;
  const kvRe = /^[^:]+:\s+\S/;
  return lines.every((l) => kvRe.test(l));
}

/**
 * Fix 3 — Rewrites Notion inter-page links.
 *
 * Notion exports links as `[Title](Page%20Title%20hexid.md)`. We replace
 * those with `[Title](DOCREF:clientId)` placeholders so we can resolve them
 * to real /documents/{uuid} URLs after the import API returns real IDs.
 *
 * Unresolvable links (target not in the import set) are degraded to plain
 * `[Title]` text so the page is still readable.
 */
function rewriteNotionLinks(
  md: string,
  hexToClientId: Map<string, string>,
): string {
  return md.replace(
    /\[([^\]]*)\]\(([^)]*?)([0-9a-f]{32})\.md\)/gi,
    (_match, text, _prefix, hexId) => {
      const targetClientId = hexToClientId.get(hexId.toLowerCase());
      if (!targetClientId) return `[${text}]`;
      return `[${text}](DOCREF:${targetClientId})`;
    },
  );
}

// ── Notion filename helpers ───────────────────────────────────────────────────

/**
 * Notion-generated system pages that should never be imported.
 * Matched case-insensitively against the resolved title.
 */
const NOTION_SYSTEM_PAGE_TITLES = new Set([
  "home",
  "teamspace home",
]);

const NOTION_UUID_RE = /\s+[0-9a-f]{32}$/i;

function stripNotionId(name: string): string {
  return name.replace(NOTION_UUID_RE, "").trim();
}

function parseTitleFromPath(filePath: string): string {
  const segments = filePath.split("/");
  const filename = segments[segments.length - 1];
  const withoutExt = filename.replace(/\.md$/i, "");
  return stripNotionId(withoutExt) || "Untitled";
}

/**
 * Normalises a file path by stripping Notion UUIDs from every segment.
 *
 *   "Export/My Page abc123/Sub Page def456.md"
 *   → "Export/My Page/Sub Page.md"
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
    .filter(Boolean)
    .join("/");
}

// ── Zip parser ────────────────────────────────────────────────────────────────

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

  for (const innerEntry of innerZips) {
    const innerData = await innerEntry.async("arraybuffer");
    const innerZip = await JSZip.loadAsync(innerData);
    await collectMdFiles(innerZip, acc);
  }
}

/**
 * Fix 2 — Returns all ancestor dir paths (at depth ≥ 2) that are needed as
 * parents. We skip depth-1 paths because those are always the export root
 * wrapper ("Export abc123/") — not a real page.
 */
function expandNeededAncestors(normDir: string): string[] {
  const parts = normDir.split("/");
  const result: string[] = [];
  // i=1 would be depth 1 (export root) — skip it; start from i=2 (depth 2).
  for (let i = 2; i <= parts.length; i++) {
    result.push(parts.slice(0, i).join("/"));
  }
  return result;
}

async function parseNotionZip(file: File): Promise<ParsedPage[]> {
  const zip = await JSZip.loadAsync(file);

  const mdFiles: Array<{ path: string; file: JSZip.JSZipObject }> = [];
  await collectMdFiles(zip, mdFiles);

  // Assign stable client IDs to every .md file.
  const normalised: Array<{ path: string; norm: string; id: string }> =
    mdFiles.map((f, i) => ({
      path: f.path,
      norm: normalisePath(f.path),
      id: `import-${i}`,
    }));

  // dirToId: normalised dir stem → clientId
  // Seeded from .md files — "Export/My Page.md" contributes stem "Export/My Page".
  const dirToId = new Map<string, string>();
  for (const entry of normalised) {
    const stem = entry.norm.replace(/\.md$/i, "");
    dirToId.set(stem, entry.id);
  }

  // Fix 2 — Collect all ancestor dirs that files need as parents, then create
  // stub pages for any that aren't already covered by a real .md file.
  const allNeeded = new Set<string>();
  for (const entry of normalised) {
    const parts = entry.norm.split("/");
    parts.pop(); // remove filename segment
    const parentDir = parts.join("/");
    if (parentDir) {
      for (const ancestor of expandNeededAncestors(parentDir)) {
        allNeeded.add(ancestor);
      }
    }
  }

  // Sort shallow-first so parent stubs are added to dirToId before children.
  const sortedNeeded = [...allNeeded].sort(
    (a, b) => a.split("/").length - b.split("/").length,
  );

  let stubIdx = mdFiles.length;
  const stubPages: ParsedPage[] = [];

  for (const normDir of sortedNeeded) {
    if (dirToId.has(normDir)) continue; // already covered by a real .md file

    const stubId = `import-stub-${stubIdx++}`;
    const title = normDir.split("/").pop() || "Untitled";

    const normParts = normDir.split("/");
    normParts.pop();
    const parentNorm = normParts.join("/");
    // Depth-1 parent ("Export") won't be in dirToId — resolves to null (root).
    const clientParentId = parentNorm ? (dirToId.get(parentNorm) ?? null) : null;

    dirToId.set(normDir, stubId);
    stubPages.push({ clientId: stubId, clientParentId, title, markdown: "" });
  }

  // Fix 3 — Build hexId → clientId map for link rewriting.
  const hexToClientId = new Map<string, string>();
  for (const entry of normalised) {
    const hexMatch = entry.path.match(/([0-9a-f]{32})\.md$/i);
    if (hexMatch) hexToClientId.set(hexMatch[1].toLowerCase(), entry.id);
  }

  // Read and process each .md file.
  const pages: ParsedPage[] = [];
  for (let i = 0; i < mdFiles.length; i++) {
    const { path, file } = mdFiles[i];
    const { norm, id } = normalised[i];

    // Resolve parent before any filtering so stubs get the correct clientParentId.
    const normParts = norm.split("/");
    normParts.pop();
    const parentDir = normParts.join("/");
    const clientParentId = parentDir ? (dirToId.get(parentDir) ?? null) : null;

    const title = parseTitleFromPath(path);

    // Filter Notion-generated system pages entirely (Home, Teamspace Home, etc.).
    // Their children are reparented to root because these containers aren't part
    // of the user's content tree.
    if (NOTION_SYSTEM_PAGE_TITLES.has(title.toLowerCase())) continue;

    const raw = await file.async("string");
    const stripped = stripLocalImages(raw);

    // Fix 1 — database-row pages become empty stubs instead of being skipped.
    // Skipping would leave their clientId in dirToId without a corresponding
    // upload entry, causing all children of that page to land at root.
    if (isDatabaseRow(stripped)) {
      pages.push({ clientId: id, clientParentId, title, markdown: "" });
      continue;
    }

    // Fix 3 — rewrite Notion inter-page links to DOCREF: placeholders.
    const markdown = rewriteNotionLinks(stripped, hexToClientId);

    pages.push({ clientId: id, clientParentId, title, markdown });
  }

  // Stubs first so parent rows exist before children in the upload payload.
  return [...stubPages, ...pages];
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
      setState({
        phase: "error",
        message: "Please select a .zip file containing markdown pages.",
      });
      return;
    }

    try {
      // 1. Parse the zip.
      setState({ phase: "parsing" });
      const pages = await parseNotionZip(file);

      const realPages = pages.filter((p) => p.markdown !== "" || p.clientId.startsWith("import-stub"));
      if (realPages.length === 0) {
        setState({
          phase: "error",
          message:
            "No markdown pages found in this zip. Check the browser console (⌘⌥J) for detected paths.",
        });
        return;
      }

      // 2. POST to bulk-import API.
      setState({ phase: "uploading" });

      const token = getAccessToken();
      const authHeaders: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (token) authHeaders["Authorization"] = `Bearer ${token}`;

      const res = await fetch("/api/documents/bulk-import", {
        method: "POST",
        headers: authHeaders,
        credentials: "same-origin",
        body: JSON.stringify({
          items: pages.map((p) => ({
            client_id: p.clientId,
            client_parent_id: p.clientParentId,
            title: p.title,
            source_markdown: p.markdown || null,
            editor_json: null,
          })),
        }),
      });

      if (!res.ok) {
        const text = await res.text().catch(() => res.statusText);
        throw new Error(`Import failed (${res.status}): ${text}`);
      }

      const result = (await res.json()) as {
        created: number;
        skipped: number;
        items: ImportResultItem[];
      };

      // 3. Fix 3 — Resolve DOCREF: placeholders in pages that had links.
      const pagesWithLinks = pages.filter((p) => p.markdown.includes("DOCREF:"));

      if (pagesWithLinks.length > 0) {
        setState({ phase: "rewriting" });

        const clientIdToRealId = new Map<string, string>();
        for (const item of result.items) {
          clientIdToRealId.set(item.client_id, item.id);
        }

        await Promise.all(
          pagesWithLinks.map(async (p) => {
            const realId = clientIdToRealId.get(p.clientId);
            if (!realId) return;

            const resolved = p.markdown.replace(
              /\(DOCREF:([^)]+)\)/g,
              (_match, targetClientId: string) => {
                const targetRealId = clientIdToRealId.get(targetClientId);
                return targetRealId
                  ? `(/documents/${targetRealId})`
                  : "(broken-link)";
              },
            );

            await fetch(`/api/documents/${realId}`, {
              method: "PATCH",
              headers: authHeaders,
              credentials: "same-origin",
              body: JSON.stringify({ source_markdown: resolved }),
            });
          }),
        );
      }

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
    state.phase === "uploading" ||
    state.phase === "rewriting";

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
        {state.phase === "rewriting" && (
          <ProgressRow icon={<Loader2 className="h-4 w-4 animate-spin" />} label="Resolving page links…" />
        )}

        {/* Done */}
        {state.phase === "done" && (
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2 text-sm text-green-600">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              <span>
                Import complete — {state.created} page
                {state.created !== 1 ? "s" : ""} added
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
