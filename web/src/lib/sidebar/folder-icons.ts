/**
 * Curated icon set for sidebar folders.
 *
 * Icons are keyed by their Lucide export name (PascalCase string). The key is
 * what gets stored in SidebarFolder.icon, so it must be stable — don't rename
 * existing keys. Adding new ones is always safe.
 *
 * Emoji strings are still accepted as a fallback (for any folders saved before
 * this feature landed) and render as plain text when no Lucide key matches.
 */

import type { LucideIcon } from "lucide-react";
import {
  // Health & Fitness
  Heart, Activity, Dumbbell, Apple, Pill, Bike, Footprints,
  // Work & Productivity
  Briefcase, Laptop, Code2, Target, CheckSquare, ClipboardList,
  Layers, BarChart2, PenTool, Layout, Package,
  // Finance
  DollarSign, TrendingUp, CreditCard, PiggyBank, Wallet, Receipt,
  // Home & Life
  Home, Coffee, Utensils, Sofa, Bed, Key, ShoppingBag,
  // Social
  Users, MessageCircle, Phone, Mail, Globe, HandHeart,
  // Nature
  Trees, Leaf, Sun, Moon, Star, Cloud, Flower2,
  // Travel
  Map, Plane, Car, Train, Compass,
  // Learning
  Book, BookOpen, GraduationCap, Pencil, Brain, Lightbulb,
  // Creative
  Music, Film, Gamepad2, Palette, Camera,
  // General
  Folder, Tag, Flag, Bell, Sparkles, Zap, Gift, Smile,
} from "lucide-react";

export const FOLDER_ICONS: Record<string, LucideIcon> = {
  // Health & Fitness
  Heart, Activity, Dumbbell, Apple, Pill, Bike, Footprints,
  // Work & Productivity
  Briefcase, Laptop, Code2, Target, CheckSquare, ClipboardList,
  Layers, BarChart2, PenTool, Layout, Package,
  // Finance
  DollarSign, TrendingUp, CreditCard, PiggyBank, Wallet, Receipt,
  // Home & Life
  Home, Coffee, Utensils, Sofa, Bed, Key, ShoppingBag,
  // Social
  Users, MessageCircle, Phone, Mail, Globe, HandHeart,
  // Nature
  Trees, Leaf, Sun, Moon, Star, Cloud, Flower2,
  // Travel
  Map, Plane, Car, Train, Compass,
  // Learning
  Book, BookOpen, GraduationCap, Pencil, Brain, Lightbulb,
  // Creative
  Music, Film, Gamepad2, Palette, Camera,
  // General
  Folder, Tag, Flag, Bell, Sparkles, Zap, Gift, Smile,
};

/** Grouped list for the picker UI. */
export const FOLDER_ICON_GROUPS: { label: string; icons: string[] }[] = [
  {
    label: "Health & Fitness",
    icons: ["Heart", "Activity", "Dumbbell", "Apple", "Pill", "Bike", "Footprints"],
  },
  {
    label: "Work",
    icons: ["Briefcase", "Laptop", "Code2", "Target", "CheckSquare", "ClipboardList",
            "Layers", "BarChart2", "PenTool", "Layout", "Package"],
  },
  {
    label: "Finance",
    icons: ["DollarSign", "TrendingUp", "CreditCard", "PiggyBank", "Wallet", "Receipt"],
  },
  {
    label: "Home & Life",
    icons: ["Home", "Coffee", "Utensils", "Sofa", "Bed", "Key", "ShoppingBag"],
  },
  {
    label: "Social",
    icons: ["Users", "MessageCircle", "Phone", "Mail", "Globe", "HandHeart"],
  },
  {
    label: "Nature",
    icons: ["Trees", "Leaf", "Sun", "Moon", "Star", "Cloud", "Flower2"],
  },
  {
    label: "Travel",
    icons: ["Map", "Plane", "Car", "Train", "Compass"],
  },
  {
    label: "Learning",
    icons: ["Book", "BookOpen", "GraduationCap", "Pencil", "Brain", "Lightbulb"],
  },
  {
    label: "Creative",
    icons: ["Music", "Film", "Gamepad2", "Palette", "Camera"],
  },
  {
    label: "General",
    icons: ["Folder", "Tag", "Flag", "Bell", "Sparkles", "Zap", "Gift", "Smile"],
  },
];

/**
 * Resolve a stored icon string to a Lucide component.
 * Returns null if the string is an emoji or any unknown key — callers should
 * fall back to rendering it as text.
 */
export function resolveFolderIcon(name: string): LucideIcon | null {
  return FOLDER_ICONS[name] ?? null;
}

/** The default icon name for new folders. */
export const DEFAULT_FOLDER_ICON = "Folder";
