import {
  DEFAULT_LAYOUT,
  WIDGET_META,
  type DashboardLayout,
  type DashboardRow,
  type WidgetInstance,
  type WidgetType,
} from "@/lib/dashboard/types";

/**
 * The "what matters to you?" answers from the first-run wizard (onboarding-001),
 * and the two things a selection changes: which sidebar sections stay visible,
 * and which widgets the dashboard opens with.
 *
 * Icons deliberately live with the wizard rather than here — this module is
 * pure data plus two pure functions, so the layout derivation can be reasoned
 * about (and reused) without pulling React in.
 *
 * A module with no `widgets` is not an oversight: recipes, workouts, notes and
 * contacts have no dashboard widget today. Selecting them lights up the
 * sidebar and nothing else, which is the honest outcome — inventing an empty
 * widget would be worse than not having one.
 */
export interface OnboardingModule {
  id: string;
  label: string;
  description: string;
  /** Built-in nav hrefs to keep visible when this module is selected. */
  reveals: string[];
  /** Dashboard widgets to pre-add, in the order they should appear. */
  widgets: WidgetType[];
}

export const ONBOARDING_MODULES: OnboardingModule[] = [
  {
    id: "finance",
    label: "Finances & budgeting",
    description: "Track spending and household budgets",
    reveals: ["/budget"],
    widgets: ["budget"],
  },
  {
    id: "habits",
    label: "Habits & routines",
    description: "Daily streaks and weekly check-ins",
    reveals: ["/habits"],
    widgets: ["habits"],
  },
  {
    id: "meals",
    label: "Meal planning & recipes",
    description: "Recipes, groceries & what's for dinner",
    reveals: ["/recipes", "/grocery-lists"],
    widgets: [],
  },
  {
    id: "tasks",
    label: "Tasks & projects",
    description: "To-do lists, chores & bigger projects",
    reveals: ["/projects"],
    widgets: ["todos"],
  },
  {
    id: "health",
    label: "Health & fitness",
    description: "Workouts and activity tracking",
    reveals: ["/workouts"],
    widgets: [],
  },
  {
    id: "notes",
    label: "Notes & journaling",
    description: "Personal notes, documents & journaling",
    reveals: ["/notes", "/documents"],
    widgets: [],
  },
  {
    id: "planning",
    label: "Calendar & goals",
    description: "What's coming up, and what you're working toward",
    reveals: ["/calendar", "/goals"],
    widgets: ["calendar_today"],
  },
  {
    id: "contacts",
    label: "Contacts",
    description: "Household contacts & relationships",
    reveals: ["/contacts"],
    widgets: [],
  },
];

const MODULES_BY_ID = new Map(ONBOARDING_MODULES.map((m) => [m.id, m]));

/**
 * Nav hrefs to hide, given the modules the user picked.
 *
 * Selecting nothing reveals everything: "no preference" is not "hide the whole
 * app". Hidden sections stay reachable through the command palette — this
 * de-emphasises them, it does not take them away.
 */
export function hiddenSectionsForModules(
  moduleIds: string[],
  toggleableHrefs: string[],
): string[] {
  if (moduleIds.length === 0) return [];
  const revealed = new Set(
    moduleIds.flatMap((id) => MODULES_BY_ID.get(id)?.reveals ?? []),
  );
  return toggleableHrefs.filter((href) => !revealed.has(href));
}

/**
 * The dashboard the user should land on, given the modules they picked.
 *
 * Falls back to DEFAULT_LAYOUT when the selection implies no widgets — either
 * because nothing was selected, or because everything selected (recipes,
 * workouts, notes) has no widget to offer. An empty dashboard is exactly the
 * "overwhelming blank app" the wizard exists to prevent.
 *
 * Widget ids are stable and derived from the type, not random: this runs once
 * at wizard submit and the layout is then persisted, so a deterministic id
 * keeps repeated submits from producing two dashboards that differ only in
 * their keys.
 */
export function dashboardLayoutForModules(moduleIds: string[]): DashboardLayout {
  const seen = new Set<WidgetType>();
  const types: WidgetType[] = [];
  for (const id of moduleIds) {
    for (const type of MODULES_BY_ID.get(id)?.widgets ?? []) {
      if (seen.has(type)) continue;
      seen.add(type);
      types.push(type);
    }
  }
  if (types.length === 0) return DEFAULT_LAYOUT;

  const widgets: WidgetInstance[] = types.map((type) => ({
    id: `onboarding-${type}`,
    type,
    colSpan: 1,
    config: WIDGET_META[type].defaultConfig,
  }));

  // Two per row, matching the two-column grid the layout declares.
  const rows: DashboardRow[] = [];
  for (let i = 0; i < widgets.length; i += 2) {
    rows.push({ id: `onboarding-row-${i / 2}`, widgets: widgets.slice(i, i + 2) });
  }
  return { columns: 2, rows };
}
