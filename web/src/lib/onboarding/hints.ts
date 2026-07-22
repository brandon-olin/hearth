/**
 * First-visit hint copy (onboarding-003).
 *
 * Pure data, no React — the same shape as `modules.ts` from onboarding-001.
 *
 * The ids here must match `HINT_PAGES` in
 * `api/src/life_dashboard/onboarding/service.py`: the API rejects a dismissal
 * for an id it does not know, so a hint added here without its id added there
 * would show forever and never dismiss. The copy itself lives only here — it is
 * UI text.
 *
 * Rules for the copy, from the brief: one sentence, zero jargon. Note the
 * division of labour with the empty states — those say what a section *is*,
 * because they only appear when there is nothing to look at. A hint shows up
 * whether or not the page has content, so it earns its space by telling you
 * something you would not have guessed from looking. Saying the same thing
 * twice on a fresh page is the failure mode to avoid.
 */
export type HintId =
  | "todos"
  | "habits"
  | "budget"
  | "recipes"
  | "notes"
  | "calendar"
  | "goals"
  | "projects";

export interface Hint {
  id: HintId;
  /** One sentence. Shown in a dismissible banner the first time you visit. */
  text: string;
  /**
   * Optional "learn more" target. Points at somewhere real in the app rather
   * than a docs site — there isn't one yet, and a dead link is worse than no
   * link. Omit for hints where the page itself is the whole story.
   */
  link?: { href: string; label: string };
}

export const HINTS: Record<HintId, Hint> = {
  todos: {
    id: "todos",
    text: "Type straight into the quick-add box to capture a task in seconds; use New when you want a due date, priority or a repeat.",
  },
  habits: {
    id: "habits",
    text: "Check in from here or from your dashboard — daily streaks and weekly completion rates build up as you go.",
  },
  budget: {
    id: "budget",
    text: "Start by importing a bank statement or connecting your bank account.",
    link: { href: "/budget/import", label: "Import transactions" },
  },
  recipes: {
    id: "recipes",
    text: "Save a recipe once and you can push its ingredients onto a grocery list every time you cook it.",
  },
  notes: {
    id: "notes",
    text: "Notes stay searchable as they pile up, and the graph view shows how the ones you link together relate.",
  },
  calendar: {
    id: "calendar",
    text: "To-dos and habits show up here on their own, on the days they're due — you only add the events yourself.",
  },
  goals: {
    id: "goals",
    text: "Link a project to a goal and the goal's progress follows that project's to-dos as they get done.",
  },
  projects: {
    id: "projects",
    text: "Every project keeps its own to-do list, and a project can hold sub-projects when the work gets big.",
  },
};
