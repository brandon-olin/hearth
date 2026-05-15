// ── AI coach types ─────────────────────────────────────────────────────────────

export type CoachTone = "supportive" | "stoic" | "drill_sergeant" | "gentle_mentor";

export const COACH_TONE_LABELS: Record<CoachTone, { label: string; description: string }> = {
  supportive: {
    label: "Supportive",
    description: "Warm, believes in you unconditionally (Ted Lasso energy)",
  },
  stoic: {
    label: "Direct (Stoic)",
    description: "Calm, no-frills, focused on what's in your control",
  },
  drill_sergeant: {
    label: "Drill Sergeant",
    description: "Hard-nosed, no excuses, pushes you harder",
  },
  gentle_mentor: {
    label: "Gentle Mentor",
    description: "Thoughtful, reflective, like a wise friend who also tracks your todos",
  },
};

// ── Widget config types ────────────────────────────────────────────────────────

export type TodoFilter = "overdue" | "today_overdue" | "this_week" | "all";

export interface TodosWidgetConfig {
  filter: TodoFilter;
}

export interface HabitsWidgetConfig {
  // No config needed — always shows today's habits
}

export interface GoalProgressConfig {
  goal_id: string;
}

export interface ProjectProgressConfig {
  project_id: string;
}

export interface AiCoachWidgetConfig {
  tone: CoachTone;
  /**
   * "auto" = show morning digest before noon, evening digest after noon.
   * "morning" / "evening" = always show that session's digest.
   */
  show_kind: "auto" | "morning" | "evening";
  pinned_project_ids: string[];
  pinned_goal_ids: string[];
  pinned_habit_ids: string[];
}

export interface CalendarTodayWidgetConfig {
  // No config — always shows today's events
}

export interface CalendarWeekWidgetConfig {
  // No config — always shows the current Mon–Sun week
}

// ── Widget instance ────────────────────────────────────────────────────────────

export type WidgetType =
  | "todos"
  | "habits"
  | "goal_progress"
  | "project_progress"
  | "ai_coach"
  | "calendar_today"
  | "calendar_week";

export type WidgetConfig =
  | TodosWidgetConfig
  | HabitsWidgetConfig
  | GoalProgressConfig
  | ProjectProgressConfig
  | AiCoachWidgetConfig
  | CalendarTodayWidgetConfig
  | CalendarWeekWidgetConfig;

export interface WidgetInstance {
  /** Stable random ID — used as dnd-kit sort key and React key */
  id: string;
  type: WidgetType;
  /** Column span in the grid (1–4). Defaults to 1. */
  colSpan: number;
  /**
   * Explicit CSS grid column-start (1–4).
   * Undefined / null = auto-placement (flows from the previous widget).
   * Set this to position a widget in a specific column — e.g. colStart=2 in a
   * 3-column grid with colSpan=1 places it in the centre with empty columns
   * on each side.  Drag the left-edge handle in edit mode to adjust.
   */
  colStart?: number | null;
  config: WidgetConfig;
}

// ── Dashboard row ─────────────────────────────────────────────────────────────

export interface DashboardRow {
  /** Stable random ID — used as droppable key */
  id: string;
  widgets: WidgetInstance[];
}

// ── Dashboard layout ───────────────────────────────────────────────────────────

export interface DashboardLayout {
  /** Number of columns on desktop (1–4). Mobile is always 1 column. */
  columns: 1 | 2 | 3 | 4;
  rows: DashboardRow[];
}

// ── Defaults ───────────────────────────────────────────────────────────────────

export const DEFAULT_LAYOUT: DashboardLayout = {
  columns: 2,
  rows: [
    {
      id: "default-row-1",
      widgets: [
        {
          id: "default-todos",
          type: "todos",
          colSpan: 1,
          config: { filter: "today_overdue" } satisfies TodosWidgetConfig,
        },
        {
          id: "default-habits",
          type: "habits",
          colSpan: 1,
          config: {} satisfies HabitsWidgetConfig,
        },
      ],
    },
  ],
};

// ── Layout migration ──────────────────────────────────────────────────────────

/**
 * Handles both the current row-based format and the legacy flat widgets[] format.
 * Returns a validated DashboardLayout or DEFAULT_LAYOUT if the data is missing/malformed.
 */
export function migrateLayout(
  prefs: Record<string, unknown> | null | undefined
): DashboardLayout {
  if (!prefs?.dashboard) return DEFAULT_LAYOUT;
  const d = prefs.dashboard as Record<string, unknown>;

  // ── New format: has rows[] ────────────────────────────────────────────────
  if (Array.isArray(d.rows) && d.columns) {
    const rows = d.rows as DashboardRow[];
    if (rows.every((r) => r.id && Array.isArray(r.widgets))) {
      return d as unknown as DashboardLayout;
    }
  }

  // ── Legacy format: has flat widgets[] ────────────────────────────────────
  if (Array.isArray(d.widgets) && d.columns) {
    const columns = (d.columns as number) ?? 2;
    // Group widgets into rows. We use the colStart/colSpan info to reconstruct
    // the visual rows as best we can, but as a safe fallback each widget gets
    // its own row so nothing is lost.
    const rows: DashboardRow[] = (d.widgets as WidgetInstance[]).map((w) => ({
      id: `migrated-${w.id}`,
      widgets: [{ id: w.id, type: w.type, colSpan: w.colSpan ?? 1, config: w.config }],
    }));
    return { columns: columns as DashboardLayout["columns"], rows };
  }

  return DEFAULT_LAYOUT;
}

// ── Widget registry metadata ───────────────────────────────────────────────────

export interface WidgetMeta {
  label: string;
  description: string;
  /** Whether the user must select an entity (goal / project) when adding */
  needsConfig: boolean;
  defaultConfig: WidgetConfig;
}

export const WIDGET_META: Record<WidgetType, WidgetMeta> = {
  todos: {
    label: "To-dos",
    description: "Tasks due today, overdue, or in a custom time window",
    needsConfig: false,
    defaultConfig: { filter: "today_overdue" } satisfies TodosWidgetConfig,
  },
  habits: {
    label: "Habits",
    description: "Today's habit check-ins with completion toggle",
    needsConfig: false,
    defaultConfig: {} satisfies HabitsWidgetConfig,
  },
  goal_progress: {
    label: "Goal Progress",
    description: "Progress bar for a single goal with a link to the detail page",
    needsConfig: true,
    defaultConfig: { goal_id: "" } satisfies GoalProgressConfig,
  },
  project_progress: {
    label: "Project",
    description: "Status card for a project with a link to the detail page",
    needsConfig: true,
    defaultConfig: { project_id: "" } satisfies ProjectProgressConfig,
  },
  ai_coach: {
    label: "AI Coach",
    description: "Morning & evening digests: what you did, what's ahead, and a pep talk",
    needsConfig: true,
    defaultConfig: {
      tone: "supportive",
      show_kind: "auto",
      pinned_project_ids: [],
      pinned_goal_ids: [],
      pinned_habit_ids: [],
    } satisfies AiCoachWidgetConfig,
  },
  calendar_today: {
    label: "Calendar — Today",
    description: "Today's events at a glance",
    needsConfig: false,
    defaultConfig: {} satisfies CalendarTodayWidgetConfig,
  },
  calendar_week: {
    label: "Calendar — Week",
    description: "Mon–Sun overview of the current week's events (best at full width)",
    needsConfig: false,
    defaultConfig: {} satisfies CalendarWeekWidgetConfig,
  },
};
