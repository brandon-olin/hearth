"use client";

import { useState } from "react";
import { $api } from "@/lib/api/query";
import { cn } from "@/lib/utils";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import {
  CheckSquare,
  Repeat,
  Target,
  FolderKanban,
  ChevronLeft,
  Sparkles,
  Check,
  CalendarDays,
  CalendarRange,
  Wallet,
} from "lucide-react";
import {
  WIDGET_META,
  COACH_TONE_LABELS,
  type WidgetType,
  type WidgetInstance,
  type GoalProgressConfig,
  type ProjectProgressConfig,
  type AiCoachWidgetConfig,
  type CoachTone,
} from "@/lib/dashboard/types";

const WIDGET_ICONS: Record<WidgetType, React.ElementType> = {
  todos: CheckSquare,
  habits: Repeat,
  goal_progress: Target,
  project_progress: FolderKanban,
  ai_coach: Sparkles,
  calendar_today: CalendarDays,
  calendar_week: CalendarRange,
  budget: Wallet,
};

// ── Step 1: pick widget type ───────────────────────────────────────────────────

function TypePicker({
  onPick,
}: {
  onPick: (type: WidgetType) => void;
}) {
  const types = Object.keys(WIDGET_META) as WidgetType[];

  return (
    <div className="grid grid-cols-2 gap-3 pt-2">
      {types.map((type) => {
        const meta = WIDGET_META[type];
        const Icon = WIDGET_ICONS[type];
        return (
          <button
            key={type}
            type="button"
            onClick={() => onPick(type)}
            className="flex flex-col items-start gap-2 rounded-lg border bg-card p-4 text-left hover:bg-muted/40 transition-colors cursor-pointer group"
          >
            <Icon className="h-5 w-5 text-muted-foreground group-hover:text-foreground transition-colors" />
            <div>
              <p className="text-sm font-medium">{meta.label}</p>
              <p className="text-xs text-muted-foreground mt-0.5">{meta.description}</p>
            </div>
          </button>
        );
      })}
    </div>
  );
}

// ── Step 2: configure goal ─────────────────────────────────────────────────────

function GoalPicker({
  onSelect,
}: {
  onSelect: (goalId: string) => void;
}) {
  const { data, isLoading } = $api.useQuery("get", "/goals", {
    params: { query: { limit: 100 } },
  });

  const goals = (data?.items ?? []).filter(
    (g) => g.status === "active" || g.status === "paused"
  );

  if (isLoading) return <p className="text-sm text-muted-foreground py-4">Loading goals…</p>;
  if (goals.length === 0)
    return <p className="text-sm text-muted-foreground py-4">No active goals found.</p>;

  return (
    <div className="space-y-2 pt-2">
      {goals.map((goal) => (
        <button
          key={goal.id}
          type="button"
          onClick={() => onSelect(goal.id)}
          className="w-full flex items-center gap-3 rounded-lg border bg-card px-4 py-3 text-left hover:bg-muted/40 transition-colors cursor-pointer"
        >
          <Target className="h-4 w-4 shrink-0 text-muted-foreground" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate">{goal.title}</p>
            {goal.description && (
              <p className="text-xs text-muted-foreground truncate">{goal.description}</p>
            )}
          </div>
        </button>
      ))}
    </div>
  );
}

// ── Step 2: configure project ─────────────────────────────────────────────────

function ProjectPicker({
  onSelect,
}: {
  onSelect: (projectId: string) => void;
}) {
  const [query, setQuery] = useState("");

  // Fetch all projects (root + subprojects) in one call so we can search across both
  const { data, isLoading } = $api.useQuery("get", "/projects", {
    params: { query: { root_only: false, include_archived: false } },
  });

  const allProjects = (data?.items ?? []).filter(
    (p) => p.status !== "complete" && p.status !== "archived" && !p.is_system
  );

  const trimmed = query.trim().toLowerCase();

  // When the search field is empty, show only root-level projects.
  // When typing, search across all projects (root + subprojects) by name.
  const displayed = trimmed
    ? allProjects.filter((p) => p.name.toLowerCase().includes(trimmed))
    : allProjects.filter((p) => p.parent_id === null);

  if (isLoading)
    return <p className="text-sm text-muted-foreground py-4">Loading projects…</p>;

  return (
    <div className="space-y-3 pt-2">
      {/* Search field */}
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search projects…"
        className="w-full rounded-md border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
        autoFocus
      />

      {/* Results */}
      {displayed.length === 0 ? (
        <p className="text-sm text-muted-foreground py-2">
          {trimmed ? "No projects match that search." : "No active projects found."}
        </p>
      ) : (
        <div className="space-y-1.5">
          {!trimmed && (
            <p className="text-xs text-muted-foreground px-1">
              Top-level projects — type to search subprojects
            </p>
          )}
          {displayed.map((project) => (
            <button
              key={project.id}
              type="button"
              onClick={() => onSelect(project.id)}
              className="w-full flex items-center gap-3 rounded-lg border bg-card px-4 py-3 text-left hover:bg-muted/40 transition-colors cursor-pointer"
            >
              <FolderKanban className="h-4 w-4 shrink-0 text-muted-foreground" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{project.name}</p>
                {project.description && (
                  <p className="text-xs text-muted-foreground truncate">{project.description}</p>
                )}
                {trimmed && project.parent_id && (
                  <p className="text-[10px] text-muted-foreground/60 mt-0.5">Subproject</p>
                )}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Step 2: configure coach (tone) ────────────────────────────────────────────

function CoachTonePicker({
  onSelect,
}: {
  onSelect: (tone: CoachTone) => void;
}) {
  const [selected, setSelected] = useState<CoachTone>("supportive");
  const tones = Object.entries(COACH_TONE_LABELS) as [CoachTone, { label: string; description: string }][];

  return (
    <div className="space-y-3 pt-2">
      <p className="text-xs text-muted-foreground">
        Choose how your coach talks to you. You can change this later.
      </p>
      <div className="space-y-2">
        {tones.map(([key, meta]) => (
          <button
            key={key}
            type="button"
            onClick={() => setSelected(key)}
            className={cn(
              "w-full flex items-start gap-3 rounded-lg border px-4 py-3 text-left transition-colors cursor-pointer",
              selected === key
                ? "border-primary bg-primary/5"
                : "bg-card hover:bg-muted/40"
            )}
          >
            <div className={cn(
              "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border-2 transition-colors",
              selected === key ? "border-primary bg-primary" : "border-muted-foreground/40"
            )}>
              {selected === key && <Check className="h-2.5 w-2.5 text-primary-foreground" />}
            </div>
            <div>
              <p className="text-sm font-medium">{meta.label}</p>
              <p className="text-xs text-muted-foreground mt-0.5">{meta.description}</p>
            </div>
          </button>
        ))}
      </div>
      <Button className="w-full mt-2" onClick={() => onSelect(selected)}>
        Add AI Coach widget
      </Button>
    </div>
  );
}

// ── Main sheet ─────────────────────────────────────────────────────────────────

interface AddWidgetSheetProps {
  open: boolean;
  onClose: () => void;
  onAdd: (widget: Omit<WidgetInstance, "id">) => void;
}

type Step = { kind: "pick" } | { kind: "configure"; type: WidgetType };

export function AddWidgetSheet({ open, onClose, onAdd }: AddWidgetSheetProps) {
  const [step, setStep] = useState<Step>({ kind: "pick" });

  function handleClose() {
    setStep({ kind: "pick" });
    onClose();
  }

  function handlePickType(type: WidgetType) {
    const meta = WIDGET_META[type];
    if (!meta.needsConfig) {
      // No config needed — add immediately
      onAdd({ type, colSpan: 1, config: meta.defaultConfig });
      handleClose();
    } else {
      setStep({ kind: "configure", type });
    }
  }

  function handleGoalSelect(goalId: string) {
    onAdd({
      type: "goal_progress",
      colSpan: 1,
      config: { goal_id: goalId } satisfies GoalProgressConfig,
    });
    handleClose();
  }

  function handleProjectSelect(projectId: string) {
    onAdd({
      type: "project_progress",
      colSpan: 1,
      config: { project_id: projectId } satisfies ProjectProgressConfig,
    });
    handleClose();
  }

  function handleCoachToneSelect(tone: CoachTone) {
    onAdd({
      type: "ai_coach",
      colSpan: 1,
      config: {
        tone,
        show_kind: "auto",
        pinned_project_ids: [],
        pinned_goal_ids: [],
        pinned_habit_ids: [],
      } satisfies AiCoachWidgetConfig,
    });
    handleClose();
  }

  const configTitles: Partial<Record<WidgetType, string>> = {
    goal_progress: "Select a goal",
    project_progress: "Select a project",
    ai_coach: "Choose your coach style",
  };

  const title =
    step.kind === "pick"
      ? "Add widget"
      : configTitles[step.type] ?? "Configure widget";

  return (
    <Sheet open={open} onOpenChange={(v) => !v && handleClose()}>
      <SheetContent side="right" className="w-full sm:max-w-md overflow-y-auto px-4">
        <SheetHeader className="mb-4">
          <div className="flex items-center gap-2">
            {step.kind !== "pick" && (
              <button
                type="button"
                onClick={() => setStep({ kind: "pick" })}
                className={cn(
                  "p-1 -ml-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted transition-colors cursor-pointer"
                )}
                aria-label="Back"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
            )}
            <SheetTitle>{title}</SheetTitle>
          </div>
        </SheetHeader>

        {step.kind === "pick" && <TypePicker onPick={handlePickType} />}

        {step.kind === "configure" && step.type === "goal_progress" && (
          <GoalPicker onSelect={handleGoalSelect} />
        )}

        {step.kind === "configure" && step.type === "project_progress" && (
          <ProjectPicker onSelect={handleProjectSelect} />
        )}

        {step.kind === "configure" && step.type === "ai_coach" && (
          <CoachTonePicker onSelect={handleCoachToneSelect} />
        )}

        <div className="mt-6">
          <Button variant="outline" className="w-full" onClick={handleClose}>
            Cancel
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
