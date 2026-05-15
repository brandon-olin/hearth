"use client";

import { useEffect, useRef, useState } from "react";
import { $api } from "@/lib/api/query";
import { getAccessToken } from "@/lib/auth/token";
import { ALL_NAVIGABLE } from "@/lib/sidebar/nav-items";
import { cn } from "@/lib/utils";
import {
  Search,
  X,
  Link2,
  ArrowRight,
  Loader2,
  FileText,
  ChefHat,
  FolderKanban,
} from "lucide-react";
import type { components } from "@/lib/api/schema";

// ── types ─────────────────────────────────────────────────────────────────────

export interface AppLinkValue {
  path: string;
  label: string;
}

interface AppLinkPickerProps {
  value: AppLinkValue | null;
  onChange: (value: AppLinkValue | null) => void;
  placeholder?: string;
}

// ── debounce ──────────────────────────────────────────────────────────────────

function useDebounced(value: string, delay: number) {
  const [d, setD] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setD(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return d;
}

// ── sub-components ────────────────────────────────────────────────────────────

function SectionHeader({ label }: { label: string }) {
  return (
    <div className="px-3 py-1 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider bg-muted/30">
      {label}
    </div>
  );
}

function ResultRow({
  icon,
  label,
  onSelect,
}: {
  icon: React.ReactNode;
  label: string;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className="flex items-center gap-2.5 w-full px-3 py-2 text-left text-sm hover:bg-muted/60 transition-colors"
    >
      {icon}
      <span className="flex-1 truncate">{label}</span>
      <ArrowRight className="h-3 w-3 text-muted-foreground/40 shrink-0" />
    </button>
  );
}

// ── main component ────────────────────────────────────────────────────────────

export function AppLinkPicker({
  value,
  onChange,
  placeholder = "Link to a page…",
}: AppLinkPickerProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const dq = useDebounced(query.trim(), 250);
  const rawQ = query.trim().toLowerCase();
  const enabled = dq.length >= 2;

  // Focus input when panel opens
  useEffect(() => {
    if (open) {
      setQuery("");
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  function select(path: string, label: string) {
    onChange({ path, label });
    setOpen(false);
  }

  // ── Nav items (static, client-side filtered) ──────────────────────────────
  const matchingNav =
    rawQ === ""
      ? ALL_NAVIGABLE
      : ALL_NAVIGABLE.filter((item) =>
          item.label.toLowerCase().includes(rawQ)
        );

  // ── Document search (backend, title-only) ─────────────────────────────────
  const [docResults, setDocResults] = useState<{ id: string; title: string }[]>(
    []
  );
  const [docsLoading, setDocsLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!enabled) {
      setDocResults([]);
      return;
    }
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setDocsLoading(true);

    const token = getAccessToken();
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;

    fetch(
      `/api/documents/search?q=${encodeURIComponent(dq)}&limit=5&offset=0`,
      { headers, signal: controller.signal }
    )
      .then((r) => r.json())
      .then((data) => {
        const items = (data.items ?? []) as {
          id: string;
          title: string;
          match_type: string;
        }[];
        setDocResults(
          items.filter((r) => r.match_type === "title").slice(0, 5)
        );
      })
      .catch(() => {/* aborted or error */})
      .finally(() => setDocsLoading(false));

    return () => controller.abort();
  }, [dq, enabled]);

  // ── Projects (backend, client-side filtered) ──────────────────────────────
  // Note: /projects does not accept a limit param — it returns all projects
  const { data: projectsData } = $api.useQuery(
    "get",
    "/projects",
    {},
    { enabled }
  );
  type Project = components["schemas"]["ProjectResponse"];
  const matchingProjects: Project[] = (projectsData?.items ?? [])
    .filter((p) => p.name.toLowerCase().includes(dq.toLowerCase()))
    .slice(0, 5);

  // ── Recipes (backend, client-side filtered) ───────────────────────────────
  const { data: recipesData } = $api.useQuery(
    "get",
    "/recipes",
    { params: { query: { limit: 100 } } },
    { enabled }
  );
  type Recipe = components["schemas"]["RecipeResponse"];
  const matchingRecipes: Recipe[] = (recipesData?.items ?? [])
    .filter((r) => r.name.toLowerCase().includes(dq.toLowerCase()))
    .slice(0, 5);

  const hasResults =
    matchingNav.length > 0 ||
    docResults.length > 0 ||
    matchingProjects.length > 0 ||
    matchingRecipes.length > 0;
  const showEmpty = rawQ.length > 1 && !docsLoading && !hasResults;

  return (
    <div className="space-y-2">
      {/* Current value display / trigger */}
      {value ? (
        <div className="flex items-center gap-2 px-3 py-2 rounded-md border bg-muted/30 text-sm">
          <Link2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <span className="flex-1 truncate text-foreground">{value.label}</span>
          <button
            type="button"
            aria-label="Remove link"
            onClick={() => onChange(null)}
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className={cn(
            "flex items-center gap-2 w-full px-3 py-2 rounded-md border text-sm transition-colors text-left",
            "border-input bg-background hover:bg-muted/50 text-muted-foreground",
            open && "border-ring ring-1 ring-ring"
          )}
        >
          <Link2 className="h-3.5 w-3.5 shrink-0" />
          <span>{placeholder}</span>
        </button>
      )}

      {/* Inline search panel */}
      {open && !value && (
        <div className="rounded-md border bg-background shadow-md overflow-hidden">
          {/* Input */}
          <div className="flex items-center gap-2 px-3 py-2 border-b">
            {docsLoading ? (
              <Loader2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground animate-spin" />
            ) : (
              <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            )}
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search pages…"
              className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
            <button
              type="button"
              aria-label="Close"
              onClick={() => setOpen(false)}
              className="text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>

          {/* Results */}
          <div className="max-h-60 overflow-y-auto">
            {/* Nav / sections */}
            {matchingNav.length > 0 && (
              <div>
                <SectionHeader label={rawQ === "" ? "Go to" : "Pages"} />
                {matchingNav.map((item) => {
                  const Icon =
                    typeof item.icon === "string" ? null : item.icon;
                  return (
                    <ResultRow
                      key={item.href}
                      icon={
                        Icon ? (
                          <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                        ) : (
                          <span className="text-sm leading-none">
                            {item.icon as string}
                          </span>
                        )
                      }
                      label={item.label}
                      onSelect={() => select(item.href, item.label)}
                    />
                  );
                })}
              </div>
            )}

            {/* Documents */}
            {enabled && docResults.length > 0 && (
              <div>
                <SectionHeader label="Documents" />
                {docResults.map((doc) => (
                  <ResultRow
                    key={doc.id}
                    icon={
                      <FileText className="h-3.5 w-3.5 text-muted-foreground" />
                    }
                    label={doc.title || "(untitled)"}
                    onSelect={() =>
                      select(`/documents/${doc.id}`, doc.title || "(untitled)")
                    }
                  />
                ))}
              </div>
            )}

            {/* Projects */}
            {enabled && matchingProjects.length > 0 && (
              <div>
                <SectionHeader label="Projects" />
                {matchingProjects.map((p) => (
                  <ResultRow
                    key={p.id}
                    icon={
                      <FolderKanban className="h-3.5 w-3.5 text-muted-foreground" />
                    }
                    label={p.name}
                    onSelect={() => select(`/projects/${p.id}`, p.name)}
                  />
                ))}
              </div>
            )}

            {/* Recipes */}
            {enabled && matchingRecipes.length > 0 && (
              <div>
                <SectionHeader label="Recipes" />
                {matchingRecipes.map((r) => (
                  <ResultRow
                    key={r.id}
                    icon={
                      <ChefHat className="h-3.5 w-3.5 text-muted-foreground" />
                    }
                    label={r.name}
                    onSelect={() => select(`/recipes/${r.id}`, r.name)}
                  />
                ))}
              </div>
            )}

            {/* Empty */}
            {showEmpty && (
              <p className="px-3 py-6 text-sm text-center text-muted-foreground">
                No results for &ldquo;{rawQ}&rdquo;
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
