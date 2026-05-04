"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { $api } from "@/lib/api/query";
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
import type { components } from "@/lib/api/schema";

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

const DOMAINS = {
  todo: { label: "To-do", icon: CheckSquare, href: "/todos" },
  goal: { label: "Goal", icon: Target, href: "/goals" },
  note: { label: "Note", icon: FileText, href: "/notes" },
  habit: { label: "Habit", icon: Repeat, href: "/habits" },
} as const;

type Domain = keyof typeof DOMAINS;

type Result = {
  id: string;
  title: string;
  subtitle: string;
  domain: Domain;
};

function toResults(
  domain: Domain,
  items: { id: string; title?: string | null; name?: string; status?: string; type?: string }[]
): Result[] {
  return items.map((item) => ({
    id: item.id,
    title: item.title ?? item.name ?? "(untitled)",
    subtitle: item.type ?? item.status ?? "",
    domain,
  }));
}

// ── result row ────────────────────────────────────────────────────────────────

function ResultRow({
  result,
  highlighted,
  onSelect,
}: {
  result: Result;
  highlighted: boolean;
  onSelect: () => void;
}) {
  const { icon: Icon, label } = DOMAINS[result.domain];
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "flex items-center gap-3 w-full px-4 py-2.5 text-left transition-colors cursor-pointer",
        highlighted ? "bg-muted" : "hover:bg-muted/60"
      )}
    >
      <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
      <span className="flex-1 min-w-0 text-sm truncate">{result.title}</span>
      <span className="text-xs text-muted-foreground shrink-0">{label}</span>
    </button>
  );
}

// ── section header ────────────────────────────────────────────────────────────

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

  // Parallel search queries
  const { data: todosData, isFetching: loadingTodos } = $api.useQuery(
    "get",
    "/todos",
    { params: { query: { search: dq, limit: 5 } } },
    { enabled }
  );
  const { data: goalsData, isFetching: loadingGoals } = $api.useQuery(
    "get",
    "/goals",
    { params: { query: { search: dq, limit: 5 } } },
    { enabled }
  );
  const { data: notesData, isFetching: loadingNotes } = $api.useQuery(
    "get",
    "/notes",
    { params: { query: { search: dq, limit: 5 } } },
    { enabled }
  );
  const { data: habitsData, isFetching: loadingHabits } = $api.useQuery(
    "get",
    "/habits",
    { params: { query: { search: dq, limit: 5 } } },
    { enabled }
  );

  const isLoading =
    enabled && (loadingTodos || loadingGoals || loadingNotes || loadingHabits);

  // Collate results into labelled groups
  type Group = { domain: Domain; results: Result[] };
  const groups: Group[] = [];
  if (todosData?.items.length)
    groups.push({ domain: "todo", results: toResults("todo", todosData.items) });
  if (goalsData?.items.length)
    groups.push({ domain: "goal", results: toResults("goal", goalsData.items) });
  if (notesData?.items.length)
    groups.push({ domain: "note", results: toResults("note", notesData.items) });
  if (habitsData?.items.length)
    groups.push({ domain: "habit", results: toResults("habit", habitsData.items) });

  const allResults = groups.flatMap((g) => g.results);

  // Arrow key navigation
  useEffect(() => {
    if (!open) return;
    function handle(e: KeyboardEvent) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlightIdx((i) => Math.min(i + 1, allResults.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlightIdx((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter" && allResults[highlightIdx]) {
        navigate(allResults[highlightIdx]);
      }
    }
    document.addEventListener("keydown", handle);
    return () => document.removeEventListener("keydown", handle);
  }, [open, allResults, highlightIdx]); // eslint-disable-line react-hooks/exhaustive-deps

  // Reset highlight when results change
  useEffect(() => setHighlightIdx(0), [dq]);

  function navigate(result: Result) {
    const base = DOMAINS[result.domain].href;
    // For todos, pass the ID so the page can auto-open the edit sheet
    const url = result.domain === "todo" ? `${base}?edit=${result.id}` : base;
    router.push(url);
    onClose();
  }

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
            placeholder="Search todos, notes, goals, habits…"
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
        <div className="max-h-[50vh] overflow-y-auto">
          {!enabled && (
            <p className="px-4 py-8 text-sm text-center text-muted-foreground">
              Type at least 2 characters to search.
            </p>
          )}

          {enabled && !isLoading && allResults.length === 0 && (
            <p className="px-4 py-8 text-sm text-center text-muted-foreground">
              No results for &ldquo;{dq}&rdquo;
            </p>
          )}

          {groups.map((group) => {
            const { label } = DOMAINS[group.domain];
            return (
              <div key={group.domain}>
                <SectionHeader label={label + "s"} />
                {group.results.map((result) => {
                  const idx = allResults.indexOf(result);
                  return (
                    <ResultRow
                      key={result.id}
                      result={result}
                      highlighted={idx === highlightIdx}
                      onSelect={() => navigate(result)}
                    />
                  );
                })}
              </div>
            );
          })}
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
