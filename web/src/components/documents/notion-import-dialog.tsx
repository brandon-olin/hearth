"use client";

/**
 * Markdown + HTML import dialog.
 *
 * Accepts a zip of markdown or HTML files (Notion, Obsidian, Bear, Logseq, …),
 * reconstructs page hierarchy from the folder structure, strips unresolvable
 * image references, and bulk-POSTs to POST /documents/bulk-import.
 *
 * Prefers .html files over .md when both exist for the same page stem (as in
 * Notion's HTML export), because the HTML export preserves toggle lists.
 *
 * Notion-specific fixes applied during parse:
 *   1. Database-row pages (every line is "key: value") are converted to stubs.
 *   2. Stub parent pages are auto-created for folders with no matching file.
 *   3. Inter-page links ([text](Page hexid.md)) are rewritten to internal
 *      /documents/{uuid} links via a post-import PATCH pass (MD only).
 *   4. Page icons (emoji) are extracted from HTML or MD and stored on the doc.
 *
 * Notion export structures:
 *   "Markdown & CSV" → Page Title <32-hex>.md
 *   "HTML"           → Page Title <32-hex>.html  (preserves toggles, icons)
 */

import { useRef, useState } from "react";
import JSZip from "jszip";
import { BlockNoteEditor, type Block } from "@blocknote/core";
import { useQueryClient } from "@tanstack/react-query";
import { getAccessToken } from "@/lib/auth/token";
import { apiBaseUrl } from "@/lib/api/client";
import { Upload, Loader2, CheckCircle2, AlertCircle, X, ChevronLeft } from "lucide-react";
import { Button } from "@/components/ui/button";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ParsedPage {
  clientId: string;
  clientParentId: string | null;
  title: string;
  /** source_markdown content; empty string for stubs or HTML-only pages. */
  markdown: string;
  /** editor_json blocks from BlockNote HTML parsing. */
  editorJson?: unknown;
  /** Emoji icon from the page header, if present. */
  icon?: string | null;
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

// ── Emoji helpers ─────────────────────────────────────────────────────────────

// Matches a single emoji codepoint (or ZWJ sequence). Used to detect icon lines.
const EMOJI_RE =
  /^(?:\p{Emoji_Presentation}|\p{Emoji}️)(?:‍(?:\p{Emoji_Presentation}|\p{Emoji}️))*\s*$/u;

function isEmojiOnly(text: string): boolean {
  return EMOJI_RE.test(text.trim());
}

// ── Markdown helpers ──────────────────────────────────────────────────────────

function stripLocalImages(md: string): string {
  return md.replace(/!\[[^\]]*\]\((?!https?:\/\/|data:|ftp:\/\/)[^)]*\)/g, "");
}

/**
 * Returns true when the entire file content looks like a Notion database row
 * (every non-blank line follows "Key: value" format with no prose content).
 */
function isDatabaseRow(markdown: string): boolean {
  const lines = markdown.split("\n").map((l) => l.trim()).filter(Boolean);
  if (lines.length < 2) return false;
  const kvRe = /^[^:]+:\s+\S/;
  return lines.every((l) => kvRe.test(l));
}

/**
 * Rewrites Notion inter-page links to DOCREF: placeholders for post-import
 * resolution to real /documents/{uuid} URLs.
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

/**
 * Try to extract a leading emoji icon from a markdown file.
 * Notion MD exports sometimes begin with just an emoji line before the heading.
 */
function parseIconFromMarkdown(md: string): string | null {
  const firstLine = md.split("\n").find((l) => l.trim().length > 0);
  if (!firstLine) return null;
  const trimmed = firstLine.trim();
  // Must be an emoji-only line (not a heading or paragraph)
  if (!trimmed.startsWith("#") && isEmojiOnly(trimmed)) return trimmed;
  return null;
}

// ── HTML helpers ──────────────────────────────────────────────────────────────

/**
 * Extracts the page icon emoji from Notion HTML.
 * Notion puts the icon in elements with class containing "page-icon" or "icon".
 */
function parseIconFromHtml(html: string): string | null {
  // Try <p class="page-icon">🔥</p> or <figure class="page-icon">🔥</figure>
  const iconEl = html.match(
    /<(?:p|figure|div|span)[^>]+class="[^"]*(?:page[-_]icon|icon)[^"]*"[^>]*>\s*([^\n<]{1,10})\s*<\/(?:p|figure|div|span)>/i,
  );
  if (iconEl) {
    const candidate = iconEl[1].trim();
    if (isEmojiOnly(candidate)) return candidate;
  }

  // Fallback: check for <link rel="icon" ...> with emoji-like content
  const linkIcon = html.match(/<link[^>]+rel="icon"[^>]+href="([^"]+)"/i);
  if (linkIcon) {
    const href = linkIcon[1];
    // emoji are sometimes base64-encoded SVG or plain text — skip non-emoji
    if (isEmojiOnly(href)) return href.trim();
  }
  return null;
}

/**
 * Unwraps Notion's structural wrapper divs in-place.
 *
 * Notion's HTML export wraps child blocks in two kinds of divs that produce
 * invalid BlockNote structures (blockContainer with no blockContent):
 *
 *  1. <div style="display:contents" dir="auto"> — wraps every individual
 *     to-do / toggle <ul> at each nesting level. BlockNote sees the div as a
 *     block element with no own text, creating blockContainer(blockGroup(…)).
 *
 *  2. <div class="indented"> — wraps the children of a to-do item that itself
 *     has nested children (e.g. "Work" → sub-tasks). Empty <div class="indented">
 *     appears at the end of leaf items too (harmless but noisy).
 *
 * Both must be unwrapped so BlockNote sees <ul> elements directly inside their
 * parent <li> or <details> without any intermediate div layer.
 *
 * We process innermost first (reverse document order) so each removal is safe.
 */
function unwrapNotionDivs(root: Element): void {
  // 1. display:contents divs (the outer per-item wrappers)
  const contentsDivs = [...root.querySelectorAll("div")].filter((el) => {
    const style = el.getAttribute("style") ?? "";
    return /display\s*:\s*contents/i.test(style);
  }).reverse();
  for (const div of contentsDivs) {
    while (div.firstChild) div.parentNode?.insertBefore(div.firstChild, div);
    div.remove();
  }

  // 2. class="indented" divs (the children wrappers)
  const indentedDivs = [...root.querySelectorAll("div.indented")].reverse();
  for (const div of indentedDivs) {
    while (div.firstChild) div.parentNode?.insertBefore(div.firstChild, div);
    div.remove();
  }

  // 3. Notion column-layout divs (div.column-list, div.column).
  //    These are not a BlockNote concept — unwrap them so their children become
  //    normal top-level blocks rather than producing empty blockContainers.
  const columnDivs = [...root.querySelectorAll("div.column-list, div.column")].reverse();
  for (const div of columnDivs) {
    while (div.firstChild) div.parentNode?.insertBefore(div.firstChild, div);
    div.remove();
  }
}

/**
 * Converts Notion's checkbox divs to standard <input type="checkbox"> elements
 * so BlockNote's checkListItem parser can recognise them.
 *
 * Notion HTML exports use:
 *   <div class="checkbox checkbox-on">   (checked)
 *   <div class="checkbox checkbox-off">  (unchecked)
 * instead of <input type="checkbox">.
 *
 * IMPORTANT: Only convert div.checkbox elements that are DIRECT children of
 * <li> elements which do NOT also have a direct <details> child. Toggle list
 * items (<li><details>…) must NOT get a checkbox injected — BlockNote's
 * checkListItem parser uses `querySelector("input[type=checkbox]")` (not
 * `:scope >`) so it would match any nested checkbox and steal the <li> away
 * from the toggleListItem parser.
 */
function normalizeNotionCheckboxes(root: Element): void {
  root.querySelectorAll("li").forEach((li) => {
    // Skip toggle items — they have a direct <details> child.
    if (li.querySelector(":scope > details")) return;

    // Only act on <li> elements that have a direct div.checkbox child.
    const checkboxDiv = li.querySelector(":scope > div.checkbox");
    if (!checkboxDiv) return;

    const isChecked = checkboxDiv.classList.contains("checkbox-on");
    const input = document.createElement("input");
    input.type = "checkbox";
    if (isChecked) input.checked = true;
    checkboxDiv.replaceWith(input);
  });
}

/**
 * Removes <img> elements whose src is a local relative path (not http/https/data/ftp).
 * Notion HTML exports reference image files stored alongside the HTML in the zip —
 * we never load those files, so keeping the tags just produces 404 console errors.
 */
function stripLocalImagesFromDom(root: Element): void {
  root.querySelectorAll("img").forEach((img) => {
    const src = img.getAttribute("src") ?? "";
    if (!/^(https?|data|ftp):/i.test(src)) {
      img.remove();
    }
  });
}

/**
 * Merges consecutive sibling <ul> or <ol> elements that share the same class
 * into a single list element by moving their <li> children into the first one.
 *
 * Notion's HTML export places every block-level item in its own <ul>, so after
 * unwrapping the display:contents wrapper divs we end up with many consecutive
 * same-class <ul> elements. BlockNote creates a blockContainer wrapper for each
 * separate <ul>, producing invalid blockContainer(blockGroup(…)) structures with
 * no blockContent. Collapsing them into one <ul> per group gives BlockNote a
 * single, well-formed list to parse.
 *
 * The check `!ul.parentNode` guards against elements that have already been
 * merged away in the same pass (DOM mutations are live, so previousElementSibling
 * updates immediately after a sibling is removed).
 */
function mergeSiblingLists(root: Element): void {
  [...root.querySelectorAll("ul, ol")].forEach((ul) => {
    if (!ul.parentNode) return; // already merged/removed
    const prev = ul.previousElementSibling;
    if (
      prev &&
      prev.tagName === ul.tagName &&
      prev.className === ul.className
    ) {
      while (ul.firstChild) prev.appendChild(ul.firstChild);
      ul.remove();
    }
  });
}

/**
 * Hoists <details> elements out of <li> elements when they appear alongside a
 * sibling <ul> or <ol>.
 *
 * BlockNote cannot parse <details> as a toggleListItem when it is a direct child
 * of a <li> that ALSO has a sibling <ul>/<ol>. In that situation the parser
 * produces an invalid blockContainer(blockGroup(…)) with no blockContent node,
 * which throws a hard error. Moving the <details> to after the parent list makes
 * it a standalone sibling block that BlockNote can parse correctly as a
 * toggleListItem.
 *
 * The hoist is applied in a loop until no <details> remain inside any <li>,
 * because a single pass only moves <details> one DOM level up. When <details>
 * blocks are deeply nested (e.g. a Recipe toggle inside a Work sub-item inside
 * a Week toggle), multiple passes are needed to fully extract them.
 *
 * Example (Notion "Chores:" with a nested "Completed:" toggle):
 *   Before: <li><input>Chores:<ul>…</ul><details>Completed:…</details></li>
 *   After:  <li><input>Chores:<ul>…</ul></li> [then] <details>Completed:…</details>
 */
function hoistDetailsFromListItems(root: Element): void {
  // Loop until no <details> remain as direct children of any <li>.
  // A single pass with parentList.after() moves <details> one level up, but if
  // the <li> itself was deeply nested (e.g. inside another <li> → <ul> → <li>),
  // the hoisted <details> may still be inside an outer <li>. Repeating until
  // stable fully extracts every <details> from all list-item ancestors.
  let changed = true;
  while (changed) {
    changed = false;
    // Reverse so DOM mutations from later hoists don't invalidate earlier refs.
    [...root.querySelectorAll("li > details")].reverse().forEach((details) => {
      const li = details.parentElement;
      if (!li) return;
      const parentList = li.parentElement;
      if (!parentList) return;
      // Place the <details> after the entire parent list so it becomes a sibling
      // block at the same level as the list, not a child inside it.
      parentList.after(details);
      changed = true;
    });
  }
}

/**
 * Converts Notion's <ul class="toggle"><li><details>…</details></li></ul>
 * wrapper into bare <details> elements.
 *
 * Root cause: BlockNote's checkListItem HTML parser uses
 *   li.querySelector("input[type=checkbox]")
 * which finds checkboxes ANYWHERE in the subtree, including nested deep inside
 * the toggle's <details> content (the task items). This causes every toggle <li>
 * that contains to-do children to be misidentified as a checkListItem instead of
 * a toggleListItem.
 *
 * BlockNote's toggleListItem parser has a clean, unambiguous rule:
 *   if (e.tagName === "DETAILS") return …
 * By stripping the <ul.toggle><li> wrapper and leaving bare <details> elements,
 * we ensure toggleListItem always wins over checkListItem for toggles.
 *
 * Processed innermost-first so nested toggles (week → day) are handled correctly.
 */
function unwrapToggleLists(root: Element): void {
  [...root.querySelectorAll("ul.toggle")].reverse().forEach((ul) => {
    [...ul.children].forEach((li) => {
      const details = li.querySelector(":scope > details");
      if (details) {
        ul.before(details);
      } else {
        // Non-toggle <li> — promote its content directly
        while (li.firstChild) ul.before(li.firstChild);
      }
    });
    ul.remove();
  });
}

/**
 * Unwraps <p> elements that are direct children of <li> elements.
 * Notion HTML exports often wrap list-item text in a <p> tag:
 *   <li><div class="checkbox …"/><p>Task text</p></li>
 * BlockNote treats <p> as a block-level element, so it creates a new paragraph
 * block for the text instead of recognising it as the list item's inline content.
 * Unwrapping puts the text nodes directly inside the <li> where BlockNote
 * correctly identifies them as inline content.
 */
function unwrapParagraphsInListItems(root: Element): void {
  root.querySelectorAll("li > p").forEach((p) => {
    while (p.firstChild) {
      p.parentNode?.insertBefore(p.firstChild, p);
    }
    p.remove();
  });
}

/**
 * Rewrites <a href="…PageTitle 32hex.html"> links to DOCREF:{clientId} so they
 * can be resolved to real /documents/{uuid} paths after the bulk-import completes.
 * Links not matching a known Notion hex ID are left untouched.
 */
function rewriteNotionHtmlLinks(
  root: Element,
  hexToClientId: Map<string, string>,
): void {
  root.querySelectorAll("a[href]").forEach((a) => {
    const href = a.getAttribute("href") ?? "";
    // Notion inter-page hrefs: relative paths ending in 32-hex.html[#anchor]
    const m = href.match(/([0-9a-f]{32})\.html?(?:#[^"]*)?$/i);
    if (!m) return;
    const targetClientId = hexToClientId.get(m[1].toLowerCase());
    if (targetClientId) {
      a.setAttribute("href", `DOCREF:${targetClientId}`);
    }
  });
}

/**
 * Extracts the body content from a Notion HTML page for BlockNote parsing.
 * Strips the title heading so it doesn't duplicate the page title.
 *
 * Uses DOMParser so nested divs don't confuse the extraction — the old regex
 * approach truncated at the first inner </div> inside the page-body element.
 *
 * If hexToClientId is provided, inter-page links are rewritten to DOCREF:
 * placeholders for post-import resolution.
 */
function extractNotionHtmlBody(
  html: string,
  hexToClientId?: Map<string, string>,
): string {
  const doc = new DOMParser().parseFromString(html, "text/html");

  // Prefer the dedicated page-body div (Notion HTML export)
  const pageBody =
    doc.querySelector("[class*='page-body']") ??
    doc.querySelector("article");

  if (pageBody) {
    pageBody.querySelector("h1")?.remove();
    // 1. Remove structural wrappers so genuine toggle <li> items (which still
    //    have <details> as a direct child) are visible to step 2.
    unwrapNotionDivs(pageBody);
    // 1b. Merge consecutive same-class <ul>/<ol> siblings that were split by
    //     the now-removed structural wrappers (e.g. each Notion to-do item
    //     lives in its own <ul class="to-do-list">; after unwrapping they're
    //     adjacent siblings and BlockNote wraps each in a blockContainer, which
    //     produces invalid blockContainer(blockGroup(checkListItem)) nodes).
    mergeSiblingLists(pageBody);
    unwrapParagraphsInListItems(pageBody);
    // 2. Convert div.checkbox → <input> BEFORE unwrapToggleLists so that
    //    to-do items whose children include a toggle (e.g. "Chores:" → "Completed:"
    //    sub-toggle) are correctly identified. After unwrapToggleLists the toggle
    //    <details> becomes a direct child of the to-do <li>, which would make
    //    normalizeNotionCheckboxes skip it (thinking it's a toggle item itself).
    normalizeNotionCheckboxes(pageBody);
    // 3. Strip <ul class="toggle"><li> wrappers, leaving bare <details> elements
    //    so BlockNote's unambiguous DETAILS→toggleListItem rule wins over the
    //    greedy checkListItem querySelector("input[type=checkbox]") rule.
    unwrapToggleLists(pageBody);
    // 3b. Merge again: unwrapToggleLists may expose sibling <ul> elements that
    //     were previously nested inside toggle wrappers (e.g. each to-do item
    //     inside a "Completed:" toggle is in its own <ul class="to-do-list">
    //     that only becomes a sibling after the toggle wrapper is removed).
    mergeSiblingLists(pageBody);
    // 3c. Hoist <details> that ended up as a direct child of a <li> alongside a
    //     sibling <ul>. BlockNote cannot parse that combination and throws an
    //     invalid blockContainer error. Moving <details> after the parent list
    //     makes it a standalone block that BlockNote handles correctly.
    hoistDetailsFromListItems(pageBody);
    stripLocalImagesFromDom(pageBody);
    if (hexToClientId) rewriteNotionHtmlLinks(pageBody, hexToClientId);
    return pageBody.innerHTML.trim();
  }

  // Fallback: use the full <body>, strip first <h1>
  const body = doc.body;
  body.querySelector("h1")?.remove();
  unwrapNotionDivs(body);
  mergeSiblingLists(body);
  unwrapParagraphsInListItems(body);
  normalizeNotionCheckboxes(body);
  unwrapToggleLists(body);
  mergeSiblingLists(body);
  hoistDetailsFromListItems(body);
  stripLocalImagesFromDom(body);
  if (hexToClientId) rewriteNotionHtmlLinks(body, hexToClientId);
  return body.innerHTML.trim();
}

/**
 * Post-processes the block tree returned by BlockNote's HTML parser.
 *
 * Problem: Notion wraps child content in structural elements (<div class="indented">,
 * <p>, etc.) that BlockNote turns into blocks with EMPTY content but non-empty
 * children — e.g. blockContainer(blockGroup(tasks)) with no blockContent. BlockNote
 * throws "blockContainer node does not contain a blockContent node" when it encounters
 * this structure.
 *
 * Fix: recursively scan the block tree. Any block whose inline content array is empty
 * but which has children is a spurious wrapper — promote its children one level up
 * and discard the wrapper block itself.
 */
function flattenEmptyContentBlocks(blocks: Block[]): Block[] {
  const result: Block[] = [];
  for (const block of blocks) {
    const content = block.content;
    const isEmptyInline =
      Array.isArray(content) && content.length === 0;

    if (isEmptyInline && block.children.length > 0) {
      // Wrapper with no text — promote its children into the current list
      result.push(...flattenEmptyContentBlocks(block.children as Block[]));
    } else {
      result.push({
        ...block,
        children:
          block.children.length > 0
            ? flattenEmptyContentBlocks(block.children as Block[])
            : block.children,
      } as Block);
    }
  }
  return result;
}

/**
 * Writes `localStorage.setItem("toggle-${id}", "false")` for every toggle
 * block in the tree so that the editor's preOpenToggleBlocks helper — which
 * only sets keys that are missing — leaves them collapsed on first open.
 *
 * This mirrors the same key format used in document-editor.tsx and must stay
 * in sync if that key format ever changes.
 */
function collapseAllToggles(blocks: Block[]): void {
  for (const block of blocks) {
    const isToggle =
      block.type === "toggleListItem" ||
      (block.type === "heading" &&
        (block.props as Record<string, unknown>).isToggleable === true);
    if (isToggle) {
      localStorage.setItem(`toggle-${block.id}`, "false");
    }
    if (block.children?.length) {
      collapseAllToggles(block.children as Block[]);
    }
  }
}

// Singleton parser editor — created lazily, reused across all pages.
// BlockNoteEditor.create() is safe to call in the browser without mounting.
let _parseEditor: BlockNoteEditor | null = null;

function getParseEditor(): BlockNoteEditor {
  if (!_parseEditor) {
    _parseEditor = BlockNoteEditor.create();
  }
  return _parseEditor;
}

async function parseHtmlPage(
  html: string,
  hexToClientId?: Map<string, string>,
): Promise<{ editorJson: unknown; icon: string | null }> {
  const icon = parseIconFromHtml(html);
  const bodyHtml = extractNotionHtmlBody(html, hexToClientId);
  const editor = getParseEditor();
  let rawBlocks: Block[];
  try {
    rawBlocks = editor.tryParseHTMLToBlocks(bodyHtml) as Block[];
  } catch (parseErr) {
    // HTML preprocessing didn't fully resolve all BlockNote schema violations.
    // Log and fall back to an empty block list so the rest of the import
    // continues. The page will be blank but won't crash the whole batch.
    console.error("[notion-import] tryParseHTMLToBlocks failed — page will be empty:", parseErr);
    console.error("[notion-import] failing bodyHtml:", bodyHtml);
    rawBlocks = [];
  }
  // Remove structural wrapper blocks that BlockNote creates from Notion's
  // <div class="indented"> / <p>-in-li constructs. These have empty inline
  // content arrays but non-empty children and cause a hard error when loaded.
  const blocks = flattenEmptyContentBlocks(rawBlocks);
  // Pre-write collapsed state to localStorage so imported toggles open collapsed
  // on first view (preOpenToggleBlocks in document-editor only sets missing keys).
  collapseAllToggles(blocks);
  return { editorJson: { blocks }, icon };
}

// ── Notion filename helpers ───────────────────────────────────────────────────

const NOTION_SYSTEM_PAGE_TITLES = new Set([
  "home",
  "teamspace home",
  "people",
  "index",
]);

/**
 * Returns true if any path segment (folder or file name) matches a system
 * page title. This filters both the root system page AND everything nested
 * inside it (e.g. "People/John Doe").
 */
function isSystemPath(stem: string): boolean {
  return stem
    .split("/")
    .some((seg) => NOTION_SYSTEM_PAGE_TITLES.has(seg.toLowerCase()));
}

const NOTION_UUID_RE = /\s+[0-9a-f]{32}$/i;

function stripNotionId(name: string): string {
  return name.replace(NOTION_UUID_RE, "").trim();
}

function parseTitleFromPath(filePath: string): string {
  const segments = filePath.split("/");
  const filename = segments[segments.length - 1];
  // Strip any known extension
  const withoutExt = filename.replace(/\.(md|html?)$/i, "");
  return stripNotionId(withoutExt) || "Untitled";
}

/**
 * Normalises a file path by stripping Notion UUIDs from every segment.
 * Preserves the file extension (.md or .html) on the last segment.
 */
function normalisePath(filePath: string): string {
  return filePath
    .split("/")
    .map((seg, i, arr) => {
      const isLast = i === arr.length - 1;
      if (isLast) {
        const htmlMatch = seg.match(/^(.+)(\.html?)$/i);
        if (htmlMatch) return stripNotionId(htmlMatch[1]) + htmlMatch[2].toLowerCase();
        const mdMatch = seg.match(/^(.+)(\.md)$/i);
        if (mdMatch) return stripNotionId(mdMatch[1]) + ".md";
      }
      return stripNotionId(seg);
    })
    .filter(Boolean)
    .join("/");
}

// ── Zip file collector ────────────────────────────────────────────────────────

interface ZipFile {
  path: string;
  file: JSZip.JSZipObject;
}

async function collectFiles(
  zip: JSZip,
  md: ZipFile[],
  html: ZipFile[],
): Promise<void> {
  const innerZips: JSZip.JSZipObject[] = [];

  zip.forEach((relativePath, zipEntry) => {
    if (zipEntry.dir || relativePath.startsWith("__MACOSX")) return;
    const lower = relativePath.toLowerCase();
    if (lower.endsWith(".zip")) {
      innerZips.push(zipEntry);
    } else if (lower.endsWith(".md")) {
      md.push({ path: relativePath, file: zipEntry });
    } else if (lower.endsWith(".html") || lower.endsWith(".htm")) {
      html.push({ path: relativePath, file: zipEntry });
    }
  });

  for (const innerEntry of innerZips) {
    const innerData = await innerEntry.async("arraybuffer");
    const innerZip = await JSZip.loadAsync(innerData);
    await collectFiles(innerZip, md, html);
  }
}

// ── Ancestor stub helpers ─────────────────────────────────────────────────────

function expandNeededAncestors(normDir: string): string[] {
  const parts = normDir.split("/");
  const result: string[] = [];
  for (let i = 2; i <= parts.length; i++) {
    result.push(parts.slice(0, i).join("/"));
  }
  return result;
}

// ── Main parser ───────────────────────────────────────────────────────────────

async function parseNotionZip(file: File): Promise<ParsedPage[]> {
  const zip = await JSZip.loadAsync(file);

  const mdFiles: ZipFile[] = [];
  const htmlFiles: ZipFile[] = [];
  await collectFiles(zip, mdFiles, htmlFiles);

  // ── Normalise all files and build stem maps ────────────────────────────────
  // normalised stem (without extension) → file entry, preferring HTML over MD
  // when both exist for the same page.

  interface FileEntry {
    path: string;
    file: JSZip.JSZipObject;
    ext: "md" | "html";
    id: string;
  }

  // Build normalised entries for MD files
  const mdEntries: FileEntry[] = mdFiles.map((f, i) => ({
    path: f.path,
    file: f.file,
    ext: "md",
    id: `import-${i}`,
  }));

  // Build normalised entries for HTML files (offset IDs past MD range)
  const htmlEntries: FileEntry[] = htmlFiles.map((f, i) => ({
    path: f.path,
    file: f.file,
    ext: "html",
    id: `import-h-${i}`,
  }));

  // For each normalised stem, prefer HTML entry over MD entry.
  // stemToEntry maps: normStem → winning FileEntry
  const stemToEntry = new Map<string, FileEntry>();

  for (const entry of mdEntries) {
    const norm = normalisePath(entry.path);
    const stem = norm.replace(/\.md$/i, "");
    if (isSystemPath(stem)) continue;
    stemToEntry.set(stem, { ...entry, id: `import-${mdEntries.indexOf(entry)}` });
  }
  for (const entry of htmlEntries) {
    const norm = normalisePath(entry.path);
    const stem = norm.replace(/\.html?$/i, "");
    if (isSystemPath(stem)) continue;
    // HTML wins over MD — always overwrite
    stemToEntry.set(stem, { ...entry });
  }

  // Final ordered list: re-assign sequential IDs for determinism
  const entries: Array<FileEntry & { norm: string; stem: string }> = [];
  let idx = 0;
  for (const [stem, entry] of stemToEntry) {
    const norm = stem + (entry.ext === "html" ? ".html" : ".md");
    entries.push({ ...entry, id: `import-${idx++}`, norm, stem });
  }

  // ── Build dirToId and hexToClientId ───────────────────────────────────────
  const dirToId = new Map<string, string>();
  const hexToClientId = new Map<string, string>(); // for MD link rewriting

  for (const entry of entries) {
    dirToId.set(entry.stem, entry.id);
  }

  // Hex IDs from original MD paths (for link rewriting)
  for (const f of mdFiles) {
    const hexMatch = f.path.match(/([0-9a-f]{32})\.md$/i);
    if (!hexMatch) continue;
    const norm = normalisePath(f.path);
    const stem = norm.replace(/\.md$/i, "");
    const clientId = dirToId.get(stem);
    if (clientId) hexToClientId.set(hexMatch[1].toLowerCase(), clientId);
  }

  // Hex IDs from original HTML paths (for inter-page link rewriting in HTML exports)
  for (const f of htmlFiles) {
    const hexMatch = f.path.match(/([0-9a-f]{32})\.html?$/i);
    if (!hexMatch) continue;
    const norm = normalisePath(f.path);
    const stem = norm.replace(/\.html?$/i, "");
    const clientId = dirToId.get(stem);
    if (clientId) hexToClientId.set(hexMatch[1].toLowerCase(), clientId);
  }

  // ── Stub ancestors ────────────────────────────────────────────────────────
  const allNeeded = new Set<string>();
  for (const entry of entries) {
    const parts = entry.stem.split("/");
    parts.pop();
    const parentDir = parts.join("/");
    if (parentDir) {
      for (const ancestor of expandNeededAncestors(parentDir)) {
        allNeeded.add(ancestor);
      }
    }
  }

  const sortedNeeded = [...allNeeded].sort(
    (a, b) => a.split("/").length - b.split("/").length,
  );

  let stubIdx = entries.length;
  const stubPages: ParsedPage[] = [];

  for (const normDir of sortedNeeded) {
    if (dirToId.has(normDir)) continue;
    if (isSystemPath(normDir)) continue;
    const stubId = `import-stub-${stubIdx++}`;
    const title = normDir.split("/").pop() || "Untitled";
    const normParts = normDir.split("/");
    normParts.pop();
    const parentNorm = normParts.join("/");
    const clientParentId = parentNorm ? (dirToId.get(parentNorm) ?? null) : null;
    dirToId.set(normDir, stubId);
    stubPages.push({ clientId: stubId, clientParentId, title, markdown: "" });
  }

  // ── Process each page ─────────────────────────────────────────────────────
  const pages: ParsedPage[] = [];

  for (const entry of entries) {
    // Resolve parent
    const stemParts = entry.stem.split("/");
    stemParts.pop();
    const parentStem = stemParts.join("/");
    const clientParentId = parentStem ? (dirToId.get(parentStem) ?? null) : null;

    const title = parseTitleFromPath(entry.path);

    if (entry.ext === "html") {
      // ── HTML page ──────────────────────────────────────────────────────────
      const raw = await entry.file.async("string");
      const { editorJson, icon } = await parseHtmlPage(raw, hexToClientId);
      pages.push({
        clientId: entry.id,
        clientParentId,
        title,
        markdown: "",
        editorJson,
        icon,
      });
    } else {
      // ── Markdown page ──────────────────────────────────────────────────────
      const raw = await entry.file.async("string");
      const stripped = stripLocalImages(raw);

      if (isDatabaseRow(stripped)) {
        pages.push({ clientId: entry.id, clientParentId, title, markdown: "" });
        continue;
      }

      const icon = parseIconFromMarkdown(stripped);
      const markdown = rewriteNotionLinks(stripped, hexToClientId);
      pages.push({ clientId: entry.id, clientParentId, title, markdown, icon });
    }
  }

  return [...stubPages, ...pages];
}

// ── Platform configs ──────────────────────────────────────────────────────────

type Platform = "notion" | "obsidian" | "bear" | "logseq" | "generic";

interface PlatformConfig {
  id: Platform;
  name: string;
  emoji: string;
  /** One-line export hint shown above the drop zone. */
  tip: string;
}

const PLATFORMS: PlatformConfig[] = [
  {
    id: "notion",
    name: "Notion",
    emoji: "📝",
    tip: 'Settings → Export content → "HTML". Preserves toggles and icons — Markdown exports lose toggle blocks.',
  },
  {
    id: "obsidian",
    name: "Obsidian",
    emoji: "💎",
    tip: "Zip your vault folder and upload it here. All markdown files and subfolders are imported.",
  },
  {
    id: "bear",
    name: "Bear",
    emoji: "🐻",
    tip: "File → Export Notes → Markdown, then zip the exported folder.",
  },
  {
    id: "logseq",
    name: "Logseq",
    emoji: "🔗",
    tip: '... menu → Export graph → "Export as standard Markdown", then zip the output.',
  },
  {
    id: "generic",
    name: "Other",
    emoji: "📁",
    tip: "Any zip of .md or .html files. Folder structure becomes page hierarchy.",
  },
];

// ── Component ─────────────────────────────────────────────────────────────────

interface Props {
  onClose: () => void;
}

export function NotionImportDialog({ onClose }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<ImportState>({ phase: "idle" });
  const [platform, setPlatform] = useState<Platform | null>(null);
  const qc = useQueryClient();

  const selectedPlatform = PLATFORMS.find((p) => p.id === platform);

  async function handleFile(file: File) {
    if (!file.name.toLowerCase().endsWith(".zip")) {
      setState({
        phase: "error",
        message: "Please select a .zip file containing pages.",
      });
      return;
    }

    try {
      setState({ phase: "parsing" });
      const pages = await parseNotionZip(file);

      const realPages = pages.filter(
        (p) => p.markdown !== "" || p.editorJson !== undefined || p.clientId.startsWith("import-stub"),
      );
      if (realPages.length === 0) {
        setState({
          phase: "error",
          message:
            "No pages found in this zip. Check the browser console (⌘⌥J) for detected paths.",
        });
        return;
      }

      setState({ phase: "uploading" });

      const token = getAccessToken();
      const authHeaders: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (token) authHeaders["Authorization"] = `Bearer ${token}`;

      const res = await fetch(`${apiBaseUrl}/documents/bulk-import`, {
        method: "POST",
        headers: authHeaders,
        credentials: "same-origin",
        body: JSON.stringify({
          items: pages.map((p) => ({
            client_id: p.clientId,
            client_parent_id: p.clientParentId,
            title: p.title,
            icon: p.icon ?? null,
            source_markdown: p.markdown || null,
            editor_json: p.editorJson ?? null,
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

      // Fix 3 — Resolve DOCREF: placeholders in MD and HTML pages that had links.
      const pagesWithMdLinks = pages.filter((p) => p.markdown.includes("DOCREF:"));
      const pagesWithHtmlLinks = pages.filter(
        (p) => p.editorJson && JSON.stringify(p.editorJson).includes("DOCREF:"),
      );

      if (pagesWithMdLinks.length > 0 || pagesWithHtmlLinks.length > 0) {
        setState({ phase: "rewriting" });

        const clientIdToRealId = new Map<string, string>();
        for (const item of result.items) {
          clientIdToRealId.set(item.client_id, item.id);
        }

        /** Replace every DOCREF:{clientId} occurrence with /documents/{realId}. */
        function resolveDocRefs(text: string): string {
          return text.replace(/DOCREF:([^\s"'()]+)/g, (_match, targetClientId: string) => {
            const targetRealId = clientIdToRealId.get(targetClientId);
            return targetRealId ? `/documents/${targetRealId}` : "broken-link";
          });
        }

        await Promise.all([
          ...pagesWithMdLinks.map(async (p) => {
            const realId = clientIdToRealId.get(p.clientId);
            if (!realId) return;
            const resolved = resolveDocRefs(p.markdown);
            await fetch(`${apiBaseUrl}/documents/${realId}`, {
              method: "PATCH",
              headers: authHeaders,
              credentials: "same-origin",
              body: JSON.stringify({ source_markdown: resolved }),
            });
          }),
          ...pagesWithHtmlLinks.map(async (p) => {
            const realId = clientIdToRealId.get(p.clientId);
            if (!realId) return;
            // Resolve DOCREFs embedded inside the editor_json block tree.
            const resolvedJson = JSON.parse(resolveDocRefs(JSON.stringify(p.editorJson)));
            await fetch(`${apiBaseUrl}/documents/${realId}`, {
              method: "PATCH",
              headers: authHeaders,
              credentials: "same-origin",
              body: JSON.stringify({ editor_json: resolvedJson }),
            });
          }),
        ]);
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

  const showPicker = state.phase === "idle" && platform === null;
  const showUpload =
    (state.phase === "idle" || state.phase === "error") && platform !== null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div
        className="bg-card text-card-foreground rounded-xl shadow-xl w-full max-w-md mx-4 p-6 flex flex-col gap-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1">
            {platform !== null && !isWorking && (
              <button
                type="button"
                onClick={() => {
                  setPlatform(null);
                  setState({ phase: "idle" });
                }}
                className="text-muted-foreground hover:text-foreground p-1 rounded -ml-1"
                aria-label="Back to platform picker"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
            )}
            <h2 className="text-base font-semibold">
              {selectedPlatform
                ? `Import from ${selectedPlatform.name}`
                : "Import pages"}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isWorking}
            className="text-muted-foreground hover:text-foreground p-1 rounded"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Step 1 — Platform picker */}
        {showPicker && (
          <div className="flex flex-col gap-3">
            <p className="text-sm text-muted-foreground">
              Where are you importing from?
            </p>
            <div className="grid grid-cols-2 gap-2">
              {PLATFORMS.slice(0, 4).map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => setPlatform(p.id)}
                  className="flex items-center gap-3 rounded-lg border border-border px-3 py-3 text-sm text-left hover:bg-muted/60 hover:border-primary/40 transition-colors"
                >
                  <span className="text-xl leading-none">{p.emoji}</span>
                  <span className="font-medium">{p.name}</span>
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => setPlatform("generic")}
              className="flex items-center gap-3 rounded-lg border border-border px-3 py-2.5 text-sm text-left hover:bg-muted/60 hover:border-primary/40 transition-colors"
            >
              <span className="text-xl leading-none">
                {PLATFORMS[4].emoji}
              </span>
              <div>
                <span className="font-medium">{PLATFORMS[4].name}</span>
                <span className="text-muted-foreground ml-1.5 text-xs">
                  any markdown or HTML zip
                </span>
              </div>
            </button>
          </div>
        )}

        {/* Step 2 — Export hint */}
        {showUpload && selectedPlatform && (
          <div className="rounded-md bg-muted/60 px-3 py-2 text-xs text-muted-foreground">
            <span className="font-medium text-foreground">How to export: </span>
            {selectedPlatform.tip}
          </div>
        )}

        {/* Step 2 — Drop zone */}
        {showUpload && (
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

        {/* Progress */}
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
