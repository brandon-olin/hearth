// ── Theme system ──────────────────────────────────────────────────────────────
//
// Two-level system:
//   1. Base theme  — controls background, card, border, text, muted surfaces
//   2. Accent color — controls primary, ring, sidebar-primary
//
// Themes are categorized as Light or Dark. The separate dark/light OS toggle
// is removed; pick the theme that suits you.
//
// All values use CSS oklch(L C H) for perceptually-uniform color.

// ── Base themes ───────────────────────────────────────────────────────────────

export type BaseTheme = {
  id: string;
  label: string;
  category: "light" | "dark";
  swatch: string; // used in the picker
  vars: Record<string, string>; // CSS custom properties
};

export const BASE_THEMES: BaseTheme[] = [
  // ── Light ──────────────────────────────────────────────────────────────────
  {
    id: "clean",
    label: "Clean",
    category: "light",
    swatch: "oklch(1 0 0)",
    vars: {
      "--background":        "oklch(1 0 0)",
      "--foreground":        "oklch(0.145 0 0)",
      "--card":              "oklch(1 0 0)",
      "--card-foreground":   "oklch(0.145 0 0)",
      "--popover":           "oklch(1 0 0)",
      "--popover-foreground":"oklch(0.145 0 0)",
      "--secondary":         "oklch(0.97 0 0)",
      "--secondary-foreground":"oklch(0.205 0 0)",
      "--muted":             "oklch(0.97 0 0)",
      "--muted-foreground":  "oklch(0.556 0 0)",
      "--accent":            "oklch(0.97 0 0)",
      "--accent-foreground": "oklch(0.205 0 0)",
      "--destructive":       "oklch(0.577 0.245 27.325)",
      "--border":            "oklch(0.922 0 0)",
      "--input":             "oklch(0.922 0 0)",
      "--sidebar":           "oklch(0.985 0 0)",
      "--sidebar-foreground":"oklch(0.145 0 0)",
      "--sidebar-accent":    "oklch(0.97 0 0)",
      "--sidebar-accent-foreground":"oklch(0.205 0 0)",
      "--sidebar-border":    "oklch(0.922 0 0)",
      "--sidebar-ring":      "oklch(0.708 0 0)",
    },
  },
  {
    id: "warm",
    label: "Warm",
    category: "light",
    swatch: "oklch(0.97 0.015 80)",
    vars: {
      "--background":        "oklch(0.985 0.012 80)",
      "--foreground":        "oklch(0.18 0.025 60)",
      "--card":              "oklch(0.995 0.008 80)",
      "--card-foreground":   "oklch(0.18 0.025 60)",
      "--popover":           "oklch(0.995 0.008 80)",
      "--popover-foreground":"oklch(0.18 0.025 60)",
      "--secondary":         "oklch(0.94 0.02 80)",
      "--secondary-foreground":"oklch(0.25 0.025 60)",
      "--muted":             "oklch(0.94 0.02 80)",
      "--muted-foreground":  "oklch(0.52 0.03 60)",
      "--accent":            "oklch(0.94 0.02 80)",
      "--accent-foreground": "oklch(0.25 0.025 60)",
      "--destructive":       "oklch(0.577 0.245 27.325)",
      "--border":            "oklch(0.88 0.025 80)",
      "--input":             "oklch(0.88 0.025 80)",
      "--sidebar":           "oklch(0.975 0.015 80)",
      "--sidebar-foreground":"oklch(0.18 0.025 60)",
      "--sidebar-accent":    "oklch(0.94 0.02 80)",
      "--sidebar-accent-foreground":"oklch(0.25 0.025 60)",
      "--sidebar-border":    "oklch(0.88 0.025 80)",
      "--sidebar-ring":      "oklch(0.65 0.04 60)",
    },
  },
  {
    id: "stone",
    label: "Stone",
    category: "light",
    swatch: "oklch(0.96 0.008 250)",
    vars: {
      "--background":        "oklch(0.975 0.006 250)",
      "--foreground":        "oklch(0.15 0.015 255)",
      "--card":              "oklch(0.99 0.004 250)",
      "--card-foreground":   "oklch(0.15 0.015 255)",
      "--popover":           "oklch(0.99 0.004 250)",
      "--popover-foreground":"oklch(0.15 0.015 255)",
      "--secondary":         "oklch(0.94 0.01 250)",
      "--secondary-foreground":"oklch(0.2 0.015 255)",
      "--muted":             "oklch(0.94 0.01 250)",
      "--muted-foreground":  "oklch(0.52 0.015 255)",
      "--accent":            "oklch(0.94 0.01 250)",
      "--accent-foreground": "oklch(0.2 0.015 255)",
      "--destructive":       "oklch(0.577 0.245 27.325)",
      "--border":            "oklch(0.88 0.012 250)",
      "--input":             "oklch(0.88 0.012 250)",
      "--sidebar":           "oklch(0.965 0.009 250)",
      "--sidebar-foreground":"oklch(0.15 0.015 255)",
      "--sidebar-accent":    "oklch(0.94 0.01 250)",
      "--sidebar-accent-foreground":"oklch(0.2 0.015 255)",
      "--sidebar-border":    "oklch(0.88 0.012 250)",
      "--sidebar-ring":      "oklch(0.6 0.02 255)",
    },
  },

  // ── Dark ───────────────────────────────────────────────────────────────────
  {
    id: "slate",
    label: "Slate",
    category: "dark",
    swatch: "oklch(0.22 0.025 255)",
    vars: {
      "--background":        "oklch(0.17 0.02 255)",
      "--foreground":        "oklch(0.95 0.005 255)",
      "--card":              "oklch(0.21 0.022 255)",
      "--card-foreground":   "oklch(0.95 0.005 255)",
      "--popover":           "oklch(0.21 0.022 255)",
      "--popover-foreground":"oklch(0.95 0.005 255)",
      "--secondary":         "oklch(0.27 0.025 255)",
      "--secondary-foreground":"oklch(0.92 0.005 0)",
      "--muted":             "oklch(0.27 0.025 255)",
      "--muted-foreground":  "oklch(0.65 0.015 255)",
      "--accent":            "oklch(0.27 0.025 255)",
      "--accent-foreground": "oklch(0.92 0.005 0)",
      "--destructive":       "oklch(0.704 0.191 22.216)",
      "--border":            "oklch(1 0 0 / 10%)",
      "--input":             "oklch(1 0 0 / 15%)",
      "--sidebar":           "oklch(0.19 0.022 255)",
      "--sidebar-foreground":"oklch(0.95 0.005 255)",
      "--sidebar-accent":    "oklch(0.27 0.025 255)",
      "--sidebar-accent-foreground":"oklch(0.92 0.005 0)",
      "--sidebar-border":    "oklch(1 0 0 / 10%)",
      "--sidebar-ring":      "oklch(0.55 0.02 255)",
    },
  },
  {
    id: "midnight",
    label: "Midnight",
    category: "dark",
    swatch: "oklch(0.15 0 0)",
    vars: {
      "--background":        "oklch(0.13 0 0)",
      "--foreground":        "oklch(0.97 0 0)",
      "--card":              "oklch(0.17 0 0)",
      "--card-foreground":   "oklch(0.97 0 0)",
      "--popover":           "oklch(0.17 0 0)",
      "--popover-foreground":"oklch(0.97 0 0)",
      "--secondary":         "oklch(0.22 0 0)",
      "--secondary-foreground":"oklch(0.97 0 0)",
      "--muted":             "oklch(0.22 0 0)",
      "--muted-foreground":  "oklch(0.64 0 0)",
      "--accent":            "oklch(0.22 0 0)",
      "--accent-foreground": "oklch(0.97 0 0)",
      "--destructive":       "oklch(0.704 0.191 22.216)",
      "--border":            "oklch(1 0 0 / 10%)",
      "--input":             "oklch(1 0 0 / 15%)",
      "--sidebar":           "oklch(0.15 0 0)",
      "--sidebar-foreground":"oklch(0.97 0 0)",
      "--sidebar-accent":    "oklch(0.22 0 0)",
      "--sidebar-accent-foreground":"oklch(0.97 0 0)",
      "--sidebar-border":    "oklch(1 0 0 / 10%)",
      "--sidebar-ring":      "oklch(0.5 0 0)",
    },
  },
  {
    id: "charcoal",
    label: "Charcoal",
    category: "dark",
    swatch: "oklch(0.22 0.015 60)",
    vars: {
      "--background":        "oklch(0.17 0.012 60)",
      "--foreground":        "oklch(0.94 0.008 80)",
      "--card":              "oklch(0.21 0.014 60)",
      "--card-foreground":   "oklch(0.94 0.008 80)",
      "--popover":           "oklch(0.21 0.014 60)",
      "--popover-foreground":"oklch(0.94 0.008 80)",
      "--secondary":         "oklch(0.27 0.015 60)",
      "--secondary-foreground":"oklch(0.92 0.008 80)",
      "--muted":             "oklch(0.27 0.015 60)",
      "--muted-foreground":  "oklch(0.62 0.02 70)",
      "--accent":            "oklch(0.27 0.015 60)",
      "--accent-foreground": "oklch(0.92 0.008 80)",
      "--destructive":       "oklch(0.704 0.191 22.216)",
      "--border":            "oklch(1 0 0 / 10%)",
      "--input":             "oklch(1 0 0 / 15%)",
      "--sidebar":           "oklch(0.19 0.013 60)",
      "--sidebar-foreground":"oklch(0.94 0.008 80)",
      "--sidebar-accent":    "oklch(0.27 0.015 60)",
      "--sidebar-accent-foreground":"oklch(0.92 0.008 80)",
      "--sidebar-border":    "oklch(1 0 0 / 10%)",
      "--sidebar-ring":      "oklch(0.55 0.025 60)",
    },
  },
];

// ── Accent colors ─────────────────────────────────────────────────────────────

export type AccentColor = {
  id: string;
  label: string;
  swatch: string;
  // Applied in light base themes
  light: Record<string, string>;
  // Applied in dark base themes
  dark: Record<string, string>;
};

export const ACCENT_COLORS: AccentColor[] = [
  {
    id: "neutral",
    label: "Neutral",
    swatch: "oklch(0.205 0 0)",
    light: {
      "--primary":                     "oklch(0.205 0 0)",
      "--primary-foreground":          "oklch(0.985 0 0)",
      "--ring":                        "oklch(0.708 0 0)",
      "--sidebar-primary":             "oklch(0.205 0 0)",
      "--sidebar-primary-foreground":  "oklch(0.985 0 0)",
    },
    dark: {
      "--primary":                     "oklch(0.922 0 0)",
      "--primary-foreground":          "oklch(0.145 0 0)",
      "--ring":                        "oklch(0.556 0 0)",
      "--sidebar-primary":             "oklch(0.85 0 0)",
      "--sidebar-primary-foreground":  "oklch(0.145 0 0)",
    },
  },
  {
    id: "blue",
    label: "Blue",
    swatch: "oklch(0.546 0.175 250)",
    light: {
      "--primary":                     "oklch(0.546 0.175 250)",
      "--primary-foreground":          "oklch(0.985 0 0)",
      "--ring":                        "oklch(0.67 0.14 250)",
      "--sidebar-primary":             "oklch(0.546 0.175 250)",
      "--sidebar-primary-foreground":  "oklch(0.985 0 0)",
    },
    dark: {
      "--primary":                     "oklch(0.72 0.15 250)",
      "--primary-foreground":          "oklch(0.1 0 0)",
      "--ring":                        "oklch(0.546 0.175 250)",
      "--sidebar-primary":             "oklch(0.65 0.18 250)",
      "--sidebar-primary-foreground":  "oklch(0.985 0 0)",
    },
  },
  {
    id: "green",
    label: "Green",
    swatch: "oklch(0.5 0.14 145)",
    light: {
      "--primary":                     "oklch(0.5 0.14 145)",
      "--primary-foreground":          "oklch(0.985 0 0)",
      "--ring":                        "oklch(0.65 0.12 145)",
      "--sidebar-primary":             "oklch(0.5 0.14 145)",
      "--sidebar-primary-foreground":  "oklch(0.985 0 0)",
    },
    dark: {
      "--primary":                     "oklch(0.7 0.14 145)",
      "--primary-foreground":          "oklch(0.1 0 0)",
      "--ring":                        "oklch(0.5 0.14 145)",
      "--sidebar-primary":             "oklch(0.62 0.16 145)",
      "--sidebar-primary-foreground":  "oklch(0.985 0 0)",
    },
  },
  {
    id: "amber",
    label: "Amber",
    swatch: "oklch(0.72 0.17 75)",
    light: {
      "--primary":                     "oklch(0.62 0.18 75)",
      "--primary-foreground":          "oklch(0.985 0 0)",
      "--ring":                        "oklch(0.75 0.14 75)",
      "--sidebar-primary":             "oklch(0.62 0.18 75)",
      "--sidebar-primary-foreground":  "oklch(0.985 0 0)",
    },
    dark: {
      "--primary":                     "oklch(0.78 0.17 75)",
      "--primary-foreground":          "oklch(0.1 0 0)",
      "--ring":                        "oklch(0.62 0.18 75)",
      "--sidebar-primary":             "oklch(0.72 0.19 75)",
      "--sidebar-primary-foreground":  "oklch(0.1 0 0)",
    },
  },
  {
    id: "rose",
    label: "Rose",
    swatch: "oklch(0.59 0.22 10)",
    light: {
      "--primary":                     "oklch(0.59 0.22 10)",
      "--primary-foreground":          "oklch(0.985 0 0)",
      "--ring":                        "oklch(0.72 0.17 10)",
      "--sidebar-primary":             "oklch(0.59 0.22 10)",
      "--sidebar-primary-foreground":  "oklch(0.985 0 0)",
    },
    dark: {
      "--primary":                     "oklch(0.75 0.19 10)",
      "--primary-foreground":          "oklch(0.1 0 0)",
      "--ring":                        "oklch(0.59 0.22 10)",
      "--sidebar-primary":             "oklch(0.68 0.21 10)",
      "--sidebar-primary-foreground":  "oklch(0.985 0 0)",
    },
  },
  {
    id: "violet",
    label: "Violet",
    swatch: "oklch(0.55 0.23 295)",
    light: {
      "--primary":                     "oklch(0.55 0.23 295)",
      "--primary-foreground":          "oklch(0.985 0 0)",
      "--ring":                        "oklch(0.68 0.18 295)",
      "--sidebar-primary":             "oklch(0.55 0.23 295)",
      "--sidebar-primary-foreground":  "oklch(0.985 0 0)",
    },
    dark: {
      "--primary":                     "oklch(0.73 0.19 295)",
      "--primary-foreground":          "oklch(0.1 0 0)",
      "--ring":                        "oklch(0.55 0.23 295)",
      "--sidebar-primary":             "oklch(0.65 0.22 295)",
      "--sidebar-primary-foreground":  "oklch(0.985 0 0)",
    },
  },
];

// ── Radius & font ─────────────────────────────────────────────────────────────

export const RADIUS_OPTIONS = [
  { label: "Sharp",   value: "0rem" },
  { label: "Subtle",  value: "0.375rem" },
  { label: "Rounded", value: "0.625rem" },
  { label: "Pill",    value: "1rem" },
];

export const FONT_OPTIONS = [
  { label: "System", value: "system-ui, sans-serif" },
  { label: "Geist",  value: "var(--font-geist-sans), sans-serif" },
  { label: "Serif",  value: "Georgia, 'Times New Roman', serif" },
  { label: "Mono",   value: "ui-monospace, 'Cascadia Code', monospace" },
];

// ── Config type ───────────────────────────────────────────────────────────────

export type ThemeConfig = {
  baseThemeId: string;
  accentId: string;
  radius: string;
  fontFamily: string;
  /** Per-variable overrides applied on top of the preset. Keys are CSS var names like "--background". */
  customVars?: Record<string, string>;
};

export const DEFAULT_CONFIG: ThemeConfig = {
  baseThemeId: "clean",
  accentId: "neutral",
  radius: "0.625rem",
  fontFamily: "var(--font-geist-sans), sans-serif",
  customVars: {},
};

// The CSS variables that are surfaced in the per-variable color picker.
export const CUSTOM_VAR_OPTIONS: { key: string; label: string }[] = [
  { key: "--background",       label: "Background"       },
  { key: "--foreground",       label: "Foreground"       },
  { key: "--card",             label: "Card"             },
  { key: "--primary",          label: "Primary"          },
  { key: "--primary-foreground", label: "Primary text"   },
  { key: "--muted",            label: "Muted surface"    },
  { key: "--muted-foreground", label: "Muted text"       },
  { key: "--accent",           label: "Accent surface"   },
  { key: "--border",           label: "Border"           },
  { key: "--ring",             label: "Focus ring"       },
  { key: "--sidebar",          label: "Sidebar"          },
];

// ── Persistence ───────────────────────────────────────────────────────────────

const STORAGE_KEY = "ld-theme-config";

export function loadThemeConfig(): ThemeConfig {
  if (typeof window === "undefined") return DEFAULT_CONFIG;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_CONFIG;
    return { ...DEFAULT_CONFIG, ...JSON.parse(raw) };
  } catch {
    return DEFAULT_CONFIG;
  }
}

export function saveThemeConfig(config: ThemeConfig): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
}

// ── Apply ─────────────────────────────────────────────────────────────────────
// Sets ALL CSS custom properties as inline styles on <html>.
// Inline styles override both :root {} and .dark {} stylesheet rules.

export function applyThemeConfig(config: ThemeConfig, animate = true): void {
  const root = document.documentElement;

  // Add transition class for smooth 300ms color animations
  if (animate) {
    root.classList.add("theme-switching");
    setTimeout(() => root.classList.remove("theme-switching"), 400);
  }

  const base = BASE_THEMES.find((t) => t.id === config.baseThemeId) ?? BASE_THEMES[0];
  const accent = ACCENT_COLORS.find((a) => a.id === config.accentId) ?? ACCENT_COLORS[0];

  // Toggle .dark class so components that check it (BlockNote, etc.) stay in sync.
  root.classList.toggle("dark", base.category === "dark");
  const accentVars = base.category === "dark" ? accent.dark : accent.light;

  // Apply base vars
  for (const [k, v] of Object.entries(base.vars)) {
    root.style.setProperty(k, v);
  }
  // Apply accent vars (overrides any base-defined primary/ring)
  for (const [k, v] of Object.entries(accentVars)) {
    root.style.setProperty(k, v);
  }
  // Radius and font
  root.style.setProperty("--radius", config.radius);
  root.style.setProperty("--font-sans", config.fontFamily);
  // Per-variable overrides — applied last so they win over preset + accent
  for (const [k, v] of Object.entries(config.customVars ?? {})) {
    if (v) root.style.setProperty(k, v);
  }
}

/** Returns true when the currently-selected base palette is a dark theme. */
export function isThemeDark(config: ThemeConfig): boolean {
  const base = BASE_THEMES.find((t) => t.id === config.baseThemeId) ?? BASE_THEMES[0];
  return base.category === "dark";
}
