import {
  LayoutDashboard,
  Target,
  Repeat,
  FileText,
  BookOpen,
  Calendar,
  Users,
  ChefHat,
  ShoppingCart,
  Dumbbell,
  FolderKanban,
  Settings,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

/**
 * A nav item can be backed by either a Lucide icon component (built-in pages)
 * or an emoji string (user-created collections). The shell renders both cases.
 */
export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon | string;
  /** True for user-created collection nav items */
  isCollection?: boolean;
  collectionId?: string;
  collectionDomain?: "notes" | "documents";
  /** True for project nav items (show_in_nav = true) */
  isProject?: boolean;
  projectId?: string;
  /** True for individually-pinned document nav items */
  isDocument?: boolean;
  documentId?: string;
};

// Built-in nav items — code-defined, static, always present unless hidden.
// Settings lives in the sidebar footer and is excluded here so it doesn't
// appear in the sidebar customizer, but it IS included in ALL_NAVIGABLE below
// so users can reach it via the command palette.
export const BUILTIN_NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/projects", label: "Projects", icon: FolderKanban },
  { href: "/documents", label: "Documents", icon: FileText },
  { href: "/notes", label: "Notes", icon: BookOpen },
  { href: "/habits", label: "Habits", icon: Repeat },
  { href: "/goals", label: "Goals", icon: Target },
  { href: "/calendar", label: "Calendar", icon: Calendar },
  { href: "/recipes", label: "Recipes", icon: ChefHat },
  { href: "/grocery-lists", label: "Groceries", icon: ShoppingCart },
  { href: "/workouts", label: "Workouts", icon: Dumbbell },
  { href: "/contacts", label: "Contacts", icon: Users },
];

/**
 * @deprecated Use BUILTIN_NAV_ITEMS for static items, or useNavItems() for
 * the full combined list (builtins + user collections). This alias is kept
 * temporarily to avoid breaking the settings page while it's being updated.
 */
export const ALL_NAV_ITEMS = BUILTIN_NAV_ITEMS;

// All destinations reachable via the command palette (nav items + settings).
export const ALL_NAVIGABLE: NavItem[] = [
  ...BUILTIN_NAV_ITEMS,
  { href: "/settings", label: "Settings", icon: Settings },
];
