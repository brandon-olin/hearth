"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { $api } from "@/lib/api/query";
import { getAccessToken } from "@/lib/auth/token";
import { cn } from "@/lib/utils";
import {
  Search,
  X,
  CheckSquare,
  Target,
  Repeat,
  FileText,
  Loader2,
} from "lucide-react";

// ── debounce hook ─────────────────────────────────────────────────────────────

function useDebounced(value: string, delay: number) {
  const [d, setD] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setD(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return d;
}

// ── domain config ─────────────────────────────────────────────────────────────

const NON_DOC_DOMAINS = {
  todo: { label: "To-do", icon: CheckSquare, href: "/todos" },
  goal: { label: "Goal", icon: Target, href: "/goals" },
  habit: { label: "Habit", icon: Repeat, href: "/habits" },
} as const;

type NonDocDomain = keyof typeof NON_DOC_DOMAINS;

// ── types ─────────────────────────────────────────────────────────────────────

interface DocResult {
  id: string;
  title: string;
  match_type: "title" | "body";
  snippet?: string | null;
}

interface NonDocResult {
  id: string;
  title: string;
  subtitle: string;
  domain: NonDocDomain;
}

// ── document search hook ──────────────────────────────────────────────────────

interface DocSearchPage {
  items: DocResult[];
  has_more: boolean;
}

const PAGE_SIZE = 20;

function useDocumentSearch(q: string) {
  const [pages, setPages] = useState<DocResult[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // Reset when query changes
  useEffect(() => {
    setPages([]);
    setOffset(0);
    setHasMore(false);
  }, [q]);

  // Fetch whenever q or offset changes
  useEffect(() => {
    if (q.length < 2) {
      setPages([]);
      setHasMore(false);
      return;
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setIsLoading(true);

    const token = getAccessToken();
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;

    fetch(
      `/api/documents/search?q=${encodeURIComponent(q)}&limit=${PAGE_SIZE}&offset=${offset}`,
      { headers, credentials: "same-origin", signal: controller.signal },
    )
      .then((r) => r.json() as Promise<DocSearchPage>)
      .then((data) => {
        if (offset === 0) {
          setPages(data.items);
        } else {
          setPages((prev) => [...prev, ...data.items]);
        }
        setHasMore(data.has_more);
      })
      .catch(() => {/* aborted or error — ignore */})
      .finally(() => setIsLoading(false));

    return () => controller.abort();
  }, [q, offset]);

  const loadMore = useCallback(() => {
    if (!isLoading && hasMore) setOffset((o) => o + PAGE_SIZE);
  }, [isLoading, hasMore]);

  return { pages, hasMore, isLoading, loadMore };
}

// ── result rows ───────────────────────────────────────────────────────────────

function DocResultRow({
  result,
  highlighted,
  onSelect,
}: {
  result: DocResult;
  highlighted: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "flex items-start gap-3 w-full px-4 py-2 text-left transition-colors cursor-pointer",
        highlighted ? "bg-muted" : "hover:bg-muted/60",
      )}
    >
      <FileText className="h-4 w-4 shrink-0 text-muted-foreground mt-0.5" />
      <div className="flex-1 min-w-0">
        <div className="text-sm truncate">{result.title}</div>
        {result.snippet && (
          <div className="text-xs text-muted-foreground truncate mt-0.5">
            {result.snippet}
          </div>
        )}
      </div>
      {result.match_type === "body" && (
        <span className="text-xs text-muted-foreground shrink-0 mt-0.5">body</span>
      )}
    </button>
  );
}

function NonDocResultRow({
  result,
  highlighted,
  onSelect,
}: {
  result: NonDocResult;
  highlighted: boolean;
  onSelect: () => void;
}) {
  const { icon: Icon, label } = NON_DOC_DOMAINS[result.domain];
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "flex items-center gap-3 w-full px-4 py-2.5 text-left transition-colors cursor-pointer",
        highlighted ? "bg-muted" : "hover:bg-muted/60",
      )}
    >
      <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
      <span className="flex-1 min-w-0 text-sm truncate">{result.title}</span>
      <span className="text-xs text-muted-foreground shrink-0">{label}</span>
    </button>
  );
}

function SectionHeader({ label }: { label: string }) {
  return (
    <div className="px-4 py-1.5 text-xs font-semibold text-muted-foreground uppercase tracking-wide">
      {label}
    </div>
  );
}

// ── palette ───────────────────────────────────────────────────────────────────

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState("");
  const [highlightIdx, setHighlightIdx] = useState(0);
  const dq = useDebounced(query.trim(), 250);
  const enabled = dq.length >= 2;

  // Focus + reset on open
  useEffect(() => {
    if (open) {
      setQuery("");
      setHighlightIdx(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  // ESC to close
  useEffect(() => {
    if (!open) return;
    function handle(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handle);
    return () => document.removeEventListener("keydown", handle);
  }, [open, onClose]);

  // ── Document search (backend, title + body) ────────────────────────────────
  const {
    pages: docResults,
    hasMore: docsHasMore,
    isLoading: docsLoading,
    loadMore: loadMoreDocs,
  } = useDocumentSearch(enabled ? dq : "");

  // ── Non-doc domains (client-side title filter) ─────────────────────────────
  const { data: todosData, isFetching: loadingTodos } = $api.useQuery(
    "get",
    "/todos",
    { params: { query: { limit: 200 } } },
    { enabled },
  );
  const { data: goalsData, isFetching: loadingGoals } = $api.useQuery(
    "get",
    "/goals",
    { params: { query: { limit: 200 } } },
    { enabled },
  );
  const { data: habitsData, isFetching: loadingHabits } = $api.useQuery(
    "get",
    "/habits",
    { params: { query: { limit: 200 } } },
    { enabled },
  );

  const isLoading =
    enabled && (docsLoading || loadingTodos || loadingGoals || loadingHabits);

  function matchesQuery(text: string | null | undefined) {
    return text?.toLowerCase().includes(dq.toLowerCase()) ?? false;
  }

  const matchingTodos: NonDocResult[] = (todosData?.items ?? [])
    .filter((t) => matchesQuery(t.title))
    .slice(0, 5)
    .map((t) => ({ id: t.id, title: t.title ?? "(untitled)", subtitle: t.status ?? "", domain: "todo" }));

  const matchingGoals: NonDocResult[] = (goalsData?.items ?? [])
    .filter((g) => matchesQuery(g.title))
    .slice(0, 5)
    .map((g) => ({ id: g.id, title: g.title ?? "(untitled)", subtitle: "", domain: "goal" }));

  const matchingHabits: NonDocResult[] = (habitsData?.items ?? [])
    .filter((h) => matchesQuery(h.name))
    .slice(0, 5)
    .map((h) => ({ id: h.id, title: h.name ?? "(untitled)", subtitle: "", domain: "habit" }));

  // Flatten all results for keyboard navigation
  type FlatResult =
    | { kind: "doc"; result: DocResult }
    | { kind: "nondoc"; result: NonDocResult };

  const flat: FlatResult[] = [
    ...docResults.map((r) => ({ kind: "doc" as const, result: r })),
    ...matchingTodos.map((r) => ({ kind: "nondoc" as const, result: r })),
    ...matchingGoals.map((r) => ({ kind: "nondoc" as const, result: r })),
    ...matchingHabits.map((r) => ({ kind: "nondoc" as const, result: r })),
  ];

  // Arrow key navigation + enter
  useEffect(() => {
    if (!open) return;
    function handle(e: KeyboardEvent) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlightIdx((i) => Math.min(i + 1, flat.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlightIdx((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter" && flat[highlightIdx]) {
        navigate(flat[highlightIdx]);
      }
    }
    document.addEventListener("keydown", handle);
    return () => document.removeEventListener("keydown", handle);
  }, [open, flat, highlightIdx]); // eslint-disable-line react-hooks/exhaustive-deps

  // Reset highlight when results change
  useEffect(() => setHighlightIdx(0), [dq]);

  // Scroll pagination — load more docs when user scrolls near the bottom
  function handleResultsScroll(e: React.UIEvent<HTMLDivElement>) {
    const el = e.currentTarget;
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 60) {
      loadMoreDocs();
    }
  }

  function navigate(item: FlatResult) {
    if (item.kind === "doc") {
      router.push(`/documents/${item.result.id}`);
    } else {
      const { href } = NON_DOC_DOMAINS[item.result.domain];
      const url =
        item.result.domain === "todo" ? `${href}?edit=${item.result.id}` : href;
      router.push(url);
    }
    onClose();
  }

  const hasAnyResults = flat.length > 0;
  let flatIdx = 0;

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[18vh] bg-black/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-xl border bg-background shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b">
          {isLoading ? (
            <Loader2 className="h-4 w-4 shrink-0 text-muted-foreground animate-spin" />
          ) : (
            <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
          )}
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search documents, todos, goals, habits…"
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
          {query && (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => setQuery("")}
              className="cursor-pointer text-muted-foreground hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* Results */}
        <div
          ref={resultsRef}
          className="max-h-[52vh] overflow-y-auto"
          onScroll={handleResultsScroll}
        >
          {!enabled && (
            <p className="px-4 py-8 text-sm text-center text-muted-foreground">
              Type at least 2 characters to search.
            </p>
          )}

          {enabled && !isLoading && !hasAnyResults && (
            <p className="px-4 py-8 text-sm text-center text-muted-foreground">
              No results for &ldquo;{dq}&rdquo;
            </p>
          )}

          {/* Documents — title matches then body matches */}
          {docResults.length > 0 && (() => {
            const titleMatches = docResults.filter((r) => r.match_type === "title");
            const bodyMatches = docResults.filter((r) => r.match_type === "body");
            return (
              <>
                {titleMatches.length > 0 && (
                  <div>
                    <SectionHeader label="Documents" />
                    {titleMatches.map((r) => {
                      const idx = flatIdx++;
                      return (
                        <DocResultRow
                          key={r.id}
                          result={r}
                          highlighted={idx === highlightIdx}
                          onSelect={() => navigate({ kind: "doc", result: r })}
                        />
                      );
                    })}
                  </div>
                )}
                {bodyMatches.length > 0 && (
                  <div>
                    <SectionHeader label="Document content" />
                    {bodyMatches.map((r) => {
                      const idx = flatIdx++;
                      return (
                        <DocResultRow
                          key={r.id}
                          result={r}
                          highlighted={idx === highlightIdx}
                          onSelect={() => navigate({ kind: "doc", result: r })}
                        />
                      );
                    })}
                  </div>
                )}
                {docsHasMore && (
                  <div className="px-4 py-2 text-xs text-muted-foreground text-center">
                    {docsLoading ? (
                      <Loader2 className="h-3 w-3 animate-spin inline-block" />
                    ) : (
                      "Scroll for more…"
                    )}
                  </div>
                )}
              </>
            );
          })()}

          {/* Todos */}
          {matchingTodos.length > 0 && (
            <div>
              <SectionHeader label="To-dos" />
              {matchingTodos.map((r) => {
                const idx = flatIdx++;
                return (
                  <NonDocResultRow
                    key={r.id}
                    result={r}
                    highlighted={idx === highlightIdx}
                    onSelect={() => navigate({ kind: "nondoc", result: r })}
                  />
                );
              })}
            </div>
          )}

          {/* Goals */}
          {matchingGoals.length > 0 && (
            <div>
              <SectionHeader label="Goals" />
              {matchingGoals.map((r) => {
                const idx = flatIdx++;
                return (
                  <NonDocResultRow
                    key={r.id}
                    result={r}
                    highlighted={idx === highlightIdx}
                    onSelect={() => navigate({ kind: "nondoc", result: r })}
                  />
                );
              })}
            </div>
          )}

          {/* Habits */}
          {matchingHabits.length > 0 && (
            <div>
              <SectionHeader label="Habits" />
              {matchingHabits.map((r) => {
                const idx = flatIdx++;
                return (
                  <NonDocResultRow
                    key={r.id}
                    result={r}
                    highlighted={idx === highlightIdx}
                    onSelect={() => navigate({ kind: "nondoc", result: r })}
                  />
                );
              })}
            </div>
          )}
        </div>

        {/* Footer hint */}
        <div className="px-4 py-2 border-t flex items-center gap-3 text-xs text-muted-foreground">
          <span><kbd className="font-mono">↑↓</kbd> navigate</span>
          <span><kbd className="font-mono">↵</kbd> go</span>
          <span><kbd className="font-mono">esc</kbd> close</span>
        </div>
      </div>
    </div>
  );
}
