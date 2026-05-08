import {
  LayoutDashboard,
  CheckSquare,
  Target,
  Repeat,
  FileText,
  BookOpen,
  Calendar,
  Users,
  ChefHat,
  ShoppingCart,
  Dumbbell,
  Settings,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
};

// Primary nav items — shown in the sidebar and available as search targets.
// Settings lives in the sidebar footer and is excluded here so it doesn't
// appear in the sidebar customizer, but it IS included in ALL_NAVIGABLE below
// so users can reach it via the command palette.
export const ALL_NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/documents", label: "Documents", icon: FileText },
  { href: "/notes", label: "Notes", icon: BookOpen },
  { href: "/todos", label: "Tasks", icon: CheckSquare },
  { href: "/habits", label: "Habits", icon: Repeat },
  { href: "/goals", label: "Goals", icon: Target },
  { href: "/calendar", label: "Calendar", icon: Calendar },
  { href: "/recipes", label: "Recipes", icon: ChefHat },
  { href: "/grocery-lists", label: "Grocery Lists", icon: ShoppingCart },
  { href: "/workouts", label: "Workouts", icon: Dumbbell },
  { href: "/contacts", label: "Contacts", icon: Users },
];

// All destinations reachable via the command palette (nav items + settings).
export const ALL_NAVIGABLE: NavItem[] = [
  ...ALL_NAV_ITEMS,
  { href: "/settings", label: "Settings", icon: Settings },
];
