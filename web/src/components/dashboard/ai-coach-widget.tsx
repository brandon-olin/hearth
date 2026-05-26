"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { RefreshCw, Sparkles, Sun, Moon, Settings2, X, Check, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import { apiClient, apiBaseUrl } from "@/lib/api/client";
import {
  type AiCoachWidgetConfig,
  type CoachTone,
  COACH_TONE_LABELS,
} from "@/lib/dashboard/types";
import { $api } from "@/lib/api/query";

// ── Types ─────────────────────────────────────────────────────────────────────

interface CoachDigest {
  id: string;
  date: string;
  kind: string;
  content: string;
  tone: string;
  created_at: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function todayStr() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function isFriday(): boolean {
  return new Date().getDay() === 5;
}

function resolveKind(showKind: AiCoachWidgetConfig["show_kind"]): "morning" | "evening" | "weekly" {
  if (showKind === "morning") return "morning";
  if (showKind === "evening") return "evening";
  if (showKind === "weekly") return "weekly";
  // auto: morning before noon, evening after noon; weekly tab available on Fridays separately
  return new Date().getHours() < 12 ? "morning" : "evening";
}

// ── Settings panel (shown in edit mode) ───────────────────────────────────────

interface SettingsPanelProps {
  config: AiCoachWidgetConfig;
  onConfigChange: (partial: Partial<AiCoachWidgetConfig>) => void;
}

function SettingsPanel({ config, onConfigChange }: SettingsPanelProps) {
  const tones = Object.entries(COACH_TONE_LABELS) as [CoachTone, { label: string; description: string }][];
  const kinds = [
    { value: "auto", label: "Auto", description: "Morning before noon, evening after" },
    { value: "morning", label: "Morning", description: "Always show the morning digest" },
    { value: "evening", label: "Evening", description: "Always show the evening digest" },
    { value: "weekly", label: "Weekly", description: "Always show the Friday week-in-review" },
  ] as const;

  // Fetch goals and projects for the pinned-items pickers
  const { data: goalsData } = $api.useQuery("get", "/goals", {
    params: { query: { limit: 100 } },
  });
  const { data: projectsData } = $api.useQuery("get", "/projects", {
    params: { query: { root_only: false, include_archived: false } },
  });
  const { data: habitsData } = $api.useQuery("get", "/habits", {});

  const goals = (goalsData?.items ?? []).filter(
    (g) => g.status === "active" || g.status === "paused"
  );
  const projects = (projectsData?.items ?? []).filter(
    (p) => p.status !== "complete" && p.status !== "archived" && !p.is_system
  );
  const habits = (habitsData?.items ?? []).filter((h) => h.status !== "archived");

  function toggleId(
    list: string[],
    id: string,
    key: "pinned_project_ids" | "pinned_goal_ids" | "pinned_habit_ids"
  ) {
    const next = list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
    onConfigChange({ [key]: next });
  }

  return (
    <div className="space-y-4 text-sm">
      {/* Tone */}
      <div>
        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
          Coach tone
        </p>
        <div className="grid grid-cols-2 gap-1.5">
          {tones.map(([key, meta]) => (
            <button
              key={key}
              type="button"
              onClick={() => onConfigChange({ tone: key })}
              className={cn(
                "flex flex-col gap-0.5 rounded-md border px-3 py-2 text-left transition-colors cursor-pointer",
                config.tone === key
                  ? "border-primary bg-primary/5 text-foreground"
                  : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/30"
              )}
            >
              <span className="text-xs font-medium">{meta.label}</span>
              <span className="text-[10px] leading-tight opacity-70">{meta.description}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Show kind */}
      <div>
        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
          Which session to show
        </p>
        <div className="flex gap-1.5">
          {kinds.map((k) => (
            <button
              key={k.value}
              type="button"
              onClick={() => onConfigChange({ show_kind: k.value })}
              className={cn(
                "flex-1 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer",
                config.show_kind === k.value
                  ? "border-primary bg-primary/5 text-foreground"
                  : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/30"
              )}
              title={k.description}
            >
              {k.label}
            </button>
          ))}
        </div>
      </div>

      {/* Pinned items */}
      {goals.length > 0 && (
        <PinnedSection
          title="Focus goals"
          subtitle="Leave empty to include all active goals"
          items={goals.map((g) => ({ id: g.id, name: g.title }))}
          selected={config.pinned_goal_ids}
          onToggle={(id) => toggleId(config.pinned_goal_ids, id, "pinned_goal_ids")}
        />
      )}

      {projects.length > 0 && (
        <PinnedSection
          title="Focus projects"
          subtitle="Leave empty to include all active projects"
          items={projects.map((p) => ({ id: p.id, name: p.name }))}
          selected={config.pinned_project_ids}
          onToggle={(id) => toggleId(config.pinned_project_ids, id, "pinned_project_ids")}
        />
      )}

      {habits.length > 0 && (
        <PinnedSection
          title="Focus habits"
          subtitle="Leave empty to include all habits"
          items={habits.map((h) => ({ id: h.id, name: h.name }))}
          selected={config.pinned_habit_ids}
          onToggle={(id) => toggleId(config.pinned_habit_ids, id, "pinned_habit_ids")}
        />
      )}

      {/* coach-004: free-text focus. Goes beyond the structured pinned-id
          selectors above — useful when what you want is context the
          checkboxes can't express ('preparing for a hard conversation',
          'recovering from a rough weekend, go easy', etc.). */}
      <div>
        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
          Focus for this coach
        </p>
        <p className="text-xs text-muted-foreground mb-2">
          Free-text guidance the coach should weight above the standard
          briefing. Leave empty to use defaults.
        </p>
        <textarea
          value={config.focus ?? ""}
          onChange={(e) => onConfigChange({ focus: e.target.value })}
          rows={3}
          maxLength={1000}
          spellCheck
          placeholder="e.g. I'm preparing for a hard conversation today — help me think through it. Go easy on the productivity nudges."
          className="w-full text-sm bg-background border border-border rounded-md px-3 py-2 outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary resize-none"
        />
        <p className="text-[10px] text-muted-foreground mt-1 text-right">
          {(config.focus ?? "").length} / 1000
        </p>
      </div>
    </div>
  );
}

function PinnedSection({
  title,
  subtitle,
  items,
  selected,
  onToggle,
}: {
  title: string;
  subtitle: string;
  items: { id: string; name: string }[];
  selected: string[];
  onToggle: (id: string) => void;
}) {
  // Layout decision: when there are ≤8 items the old chip-grid is the
  // friendliest UI (everything visible, one click to toggle). Above 8
  // we switch to a chip-list of selected items + a search combobox for
  // adding more — the screen no longer scrolls past usefulness when a
  // user has many projects/habits.
  const COMBOBOX_THRESHOLD = 8;
  const useCombobox = items.length > COMBOBOX_THRESHOLD;

  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-0.5">
        {title}
      </p>
      <p className="text-[10px] text-muted-foreground mb-2">{subtitle}</p>
      {useCombobox ? (
        <PinnedCombobox items={items} selected={selected} onToggle={onToggle} />
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {items.map((item) => {
            const active = selected.includes(item.id);
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => onToggle(item.id)}
                className={cn(
                  "flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors cursor-pointer",
                  active
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/30"
                )}
              >
                {active && <Check className="h-3 w-3" />}
                {item.name}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}


// ── Inline searchable combobox for large item lists ──────────────────────────

function PinnedCombobox({
  items,
  selected,
  onToggle,
}: {
  items: { id: string; name: string }[];
  selected: string[];
  onToggle: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (!containerRef.current?.contains(e.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const selectedItems = items.filter((i) => selected.includes(i.id));
  const filteredItems = items.filter((i) =>
    query.trim() === "" ? true : i.name.toLowerCase().includes(query.toLowerCase()),
  );

  return (
    <div ref={containerRef} className="relative">
      {/* Selected chips — clicking removes */}
      {selectedItems.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {selectedItems.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => onToggle(item.id)}
              className="flex items-center gap-1 rounded-full border border-primary bg-primary/10 text-primary px-2.5 py-1 text-[11px] font-medium cursor-pointer hover:bg-primary/20 transition-colors"
              title="Click to remove"
            >
              {item.name}
              <X className="h-3 w-3 opacity-60" />
            </button>
          ))}
        </div>
      )}

      {/* Trigger button */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-md border border-dashed border-border px-2.5 py-1.5 text-[11px] font-medium text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors cursor-pointer"
      >
        <Plus className="h-3 w-3" />
        {selectedItems.length > 0 ? "Add another" : `Pick from ${items.length}`}
      </button>

      {/* Popover */}
      {open && (
        <div className="absolute z-20 mt-1 w-full max-w-sm rounded-md border border-border bg-popover shadow-lg overflow-hidden">
          <input
            type="text"
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type to filter…"
            className="w-full text-sm bg-background border-b border-border px-3 py-2 outline-none"
          />
          <div className="max-h-56 overflow-y-auto">
            {filteredItems.length === 0 ? (
              <div className="px-3 py-3 text-xs text-muted-foreground">
                No matches
              </div>
            ) : (
              filteredItems.map((item) => {
                const active = selected.includes(item.id);
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => onToggle(item.id)}
                    className={cn(
                      "w-full text-left px-3 py-2 text-sm flex items-center gap-2 hover:bg-muted/50 cursor-pointer",
                      active && "bg-primary/5 text-primary",
                    )}
                  >
                    {active && <Check className="h-3.5 w-3.5 shrink-0" />}
                    <span className={cn(!active && "ml-[1.125rem]")}>{item.name}</span>
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Inline markdown parser ────────────────────────────────────────────────────

/**
 * Converts **bold** and *italic* spans into React elements.
 * Handles the most common LLM output patterns without pulling in a markdown lib.
 */
function parseInline(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  // Match **bold** before *italic* so the longer pattern wins
  const regex = /\*\*(.+?)\*\*|\*(.+?)\*/g;
  let last = 0;
  let key = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    if (match[1] !== undefined) {
      nodes.push(<strong key={key++} className="font-semibold">{match[1]}</strong>);
    } else {
      nodes.push(<em key={key++}>{match[2]}</em>);
    }
    last = match.index + match[0].length;
  }

  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

// ── Digest display ─────────────────────────────────────────────────────────────

function DigestContent({ content }: { content: string }) {
  // Strip markdown headings — the widget header already provides title/date context
  const stripped = content
    .split("\n")
    .filter((line) => !line.trimStart().startsWith("#"))
    .join("\n");

  // Split into blocks on blank lines
  const blocks = stripped.split(/\n{2,}/).map((b) => b.trim()).filter(Boolean);

  return (
    <div className="space-y-3 text-sm leading-relaxed text-foreground/90">
      {blocks.map((block, i) => {
        const lines = block.split("\n").map((l) => l.trim()).filter(Boolean);

        // Bullet list block — every line starts with - or *
        if (lines.length > 0 && lines.every((l) => /^[-*]\s/.test(l))) {
          return (
            <ul key={i} className="list-disc list-inside space-y-1">
              {lines.map((line, j) => (
                <li key={j}>{parseInline(line.replace(/^[-*]\s+/, ""))}</li>
              ))}
            </ul>
          );
        }

        // Numbered list block — every line starts with a digit and dot
        if (lines.length > 0 && lines.every((l) => /^\d+\.\s/.test(l))) {
          return (
            <ol key={i} className="list-decimal list-inside space-y-1">
              {lines.map((line, j) => (
                <li key={j}>{parseInline(line.replace(/^\d+\.\s+/, ""))}</li>
              ))}
            </ol>
          );
        }

        // Regular paragraph
        return <p key={i}>{parseInline(block)}</p>;
      })}
    </div>
  );
}

// ── Main widget ───────────────────────────────────────────────────────────────

interface AiCoachWidgetProps {
  config: AiCoachWidgetConfig;
  isEditMode: boolean;
  onConfigChange: (partial: Partial<AiCoachWidgetConfig>) => void;
}

export function AiCoachWidget({ config, isEditMode, onConfigChange }: AiCoachWidgetProps) {
  const [digest, setDigest] = useState<CoachDigest | null | undefined>(undefined); // undefined = loading
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  // On Fridays, allow toggling between the regular digest and the weekly review
  const [showWeekly, setShowWeekly] = useState(false);

  const friday = isFriday();
  const baseKind = resolveKind(config.show_kind);
  // If the user has "weekly" pinned, or it's Friday and they've toggled to weekly
  const kind: "morning" | "evening" | "weekly" =
    baseKind === "weekly" ? "weekly" : (friday && showWeekly ? "weekly" : baseKind);
  const today = todayStr();

  // ── Fetch stored digest ────────────────────────────────────────────────────
  const fetchDigest = useCallback(async () => {
    setDigest(undefined);
    setError(null);
    try {
      const res = await fetch(
        `/api/ai/coach/digest?kind=${kind}&for_date=${today}`,
        { headers: { Authorization: `Bearer ${(await import("@/lib/auth/token")).getAccessToken() ?? ""}` } }
      );
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text);
      }
      const data: CoachDigest | null = await res.json();
      setDigest(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load digest");
      setDigest(null);
    }
  }, [kind, today]);

  useEffect(() => {
    fetchDigest();
  }, [fetchDigest]);

  // ── Generate digest ────────────────────────────────────────────────────────
  async function handleGenerate() {
    setIsGenerating(true);
    setError(null);
    try {
      const { getAccessToken } = await import("@/lib/auth/token");
      const res = await fetch(`${apiBaseUrl}/ai/coach/digest/generate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${getAccessToken() ?? ""}`,
        },
        body: JSON.stringify({
          kind,
          tone: config.tone,
          pinned_project_ids: config.pinned_project_ids,
          pinned_goal_ids: config.pinned_goal_ids,
          pinned_habit_ids: config.pinned_habit_ids,
          // coach-004: pass user-supplied focus through to /ai/coach/digest/generate.
          ...(config.focus && config.focus.trim()
            ? { focus: config.focus.trim() }
            : {}),
          for_date: today,
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text);
      }
      const data: CoachDigest = await res.json();
      setDigest(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate digest");
    } finally {
      setIsGenerating(false);
    }
  }

  // ── Header ─────────────────────────────────────────────────────────────────
  const KindIcon = kind === "morning" ? Sun : kind === "weekly" ? Sparkles : Moon;
  const kindLabel = kind === "morning" ? "Morning briefing" : kind === "weekly" ? "Week in review" : "Day in review";

  return (
    <div className="space-y-3">
      {/* Widget header */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className={cn(
            "flex items-center justify-center h-7 w-7 rounded-md shrink-0",
            kind === "morning" ? "bg-amber-500/10 text-amber-500" : "bg-indigo-500/10 text-indigo-400"
          )}>
            <KindIcon className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium truncate">{kindLabel}</p>
            <p className="text-[10px] text-muted-foreground truncate">
              {today}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1 shrink-0">
          {/* Friday weekly review toggle */}
          {friday && baseKind !== "weekly" && (
            <button
              type="button"
              onClick={() => setShowWeekly((w) => !w)}
              className={cn(
                "px-2 py-1 rounded text-[10px] font-medium transition-colors cursor-pointer",
                showWeekly
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted"
              )}
              title={showWeekly ? "Show daily digest" : "Show week in review"}
            >
              {showWeekly ? "Daily" : "Weekly"}
            </button>
          )}

          {/* Settings toggle — always visible */}
          <button
            type="button"
            onClick={() => setShowSettings((s) => !s)}
            className={cn(
              "p-1.5 rounded transition-colors cursor-pointer",
              showSettings
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:text-foreground hover:bg-muted"
            )}
            aria-label="Widget settings"
          >
            <Settings2 className="h-3.5 w-3.5" />
          </button>

          {/* Regenerate */}
          <button
            type="button"
            onClick={handleGenerate}
            disabled={isGenerating}
            className="p-1.5 rounded text-muted-foreground hover:text-foreground hover:bg-muted transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            aria-label="Regenerate digest"
            title="Regenerate"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", isGenerating && "animate-spin")} />
          </button>
        </div>
      </div>

      {/* Settings panel */}
      {showSettings && (
        <div className="rounded-lg border bg-muted/30 p-3">
          <SettingsPanel config={config} onConfigChange={onConfigChange} />
        </div>
      )}

      {/* Content area */}
      {!showSettings && (
        <>
          {/* Loading */}
          {digest === undefined && (
            <div className="py-6 flex items-center justify-center">
              <div className="flex items-center gap-2 text-muted-foreground text-sm">
                <Sparkles className="h-4 w-4 animate-pulse" />
                <span>Loading…</span>
              </div>
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="rounded-md bg-destructive/10 border border-destructive/20 px-3 py-2.5">
              <p className="text-xs text-destructive">{error}</p>
            </div>
          )}

          {/* No digest yet */}
          {digest === null && !error && !isGenerating && (
            <div className="py-6 flex flex-col items-center gap-3 text-center">
              <div className="flex items-center justify-center h-10 w-10 rounded-full bg-muted">
                <Sparkles className="h-5 w-5 text-muted-foreground" />
              </div>
              <div>
                <p className="text-sm font-medium">No {kind} digest yet</p>
                <p className="text-xs text-muted-foreground mt-1">
                  The scheduler generates these automatically, or you can trigger one now.
                </p>
              </div>
              <button
                type="button"
                onClick={handleGenerate}
                disabled={isGenerating}
                className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors cursor-pointer disabled:opacity-50"
              >
                <Sparkles className="h-3.5 w-3.5" />
                Generate now
              </button>
            </div>
          )}

          {/* Generating spinner */}
          {isGenerating && (
            <div className="py-6 flex items-center justify-center">
              <div className="flex items-center gap-2 text-muted-foreground text-sm">
                <Sparkles className="h-4 w-4 animate-pulse" />
                <span>Generating your digest…</span>
              </div>
            </div>
          )}

          {/* Digest content */}
          {digest !== null && digest !== undefined && !isGenerating && (
            <DigestContent content={digest.content} />
          )}
        </>
      )}
    </div>
  );
}
