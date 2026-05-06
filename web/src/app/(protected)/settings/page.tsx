"use client";

import { useEffect, useState } from "react";
import { Settings, Eye, EyeOff, ChevronUp, ChevronDown, Palette, Layout } from "lucide-react";
import { cn } from "@/lib/utils";
import { useThemeCustomizer } from "@/lib/theme/context";
import {
  BASE_THEMES,
  ACCENT_COLORS,
  RADIUS_OPTIONS,
  FONT_OPTIONS,
  type ThemeConfig,
} from "@/lib/theme/presets";
import {
  ALL_NAV_ITEMS,
  loadSidebarConfig,
  saveSidebarConfig,
  type SidebarConfig,
} from "@/components/shell/shell";

// ── Section wrapper ───────────────────────────────────────────────────────────

function Section({ title, icon: Icon, children }: {
  title: string;
  icon: React.ElementType;
  children: React.ReactNode;
}) {
  return (
    <div className="border rounded-lg bg-card">
      <div className="flex items-center gap-2 px-5 py-4 border-b">
        <Icon className="h-4 w-4 text-muted-foreground" />
        <h2 className="font-semibold text-sm">{title}</h2>
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

// ── Sidebar customizer ────────────────────────────────────────────────────────

function SidebarCustomizer() {
  const [config, setConfig] = useState<SidebarConfig>({ hidden: [], order: [] });

  useEffect(() => {
    setConfig(loadSidebarConfig());
  }, []);

  function save(next: SidebarConfig) {
    setConfig(next);
    saveSidebarConfig(next);
    window.dispatchEvent(new Event("ld-sidebar-update"));
  }

  const allHrefs = ALL_NAV_ITEMS.map((n) => n.href);
  const orderedHrefs =
    config.order.length > 0
      ? [
          ...config.order.filter((h) => allHrefs.includes(h as (typeof allHrefs)[number])),
          ...allHrefs.filter((h) => !config.order.includes(h)),
        ]
      : [...allHrefs];

  const orderedItems = orderedHrefs
    .map((href) => ALL_NAV_ITEMS.find((n) => n.href === href))
    .filter((n): n is (typeof ALL_NAV_ITEMS)[number] => !!n);

  function toggleHidden(href: string) {
    const hidden = config.hidden.includes(href)
      ? config.hidden.filter((h) => h !== href)
      : [...config.hidden, href];
    save({ ...config, hidden });
  }

  function moveItem(href: string, direction: "up" | "down") {
    const idx = orderedHrefs.indexOf(href);
    if (idx === -1) return;
    const next = [...orderedHrefs];
    const swap = direction === "up" ? idx - 1 : idx + 1;
    if (swap < 0 || swap >= next.length) return;
    [next[idx], next[swap]] = [next[swap], next[idx]];
    save({ ...config, order: next });
  }

  return (
    <div className="space-y-1">
      <p className="text-xs text-muted-foreground mb-3">
        Show or hide sections in the sidebar. Use the arrows to reorder.
      </p>
      {orderedItems.map((item, idx) => {
        const isHidden = config.hidden.includes(item.href);
        const Icon = item.icon;
        return (
          <div
            key={item.href}
            className={cn(
              "flex items-center gap-3 px-3 py-2.5 rounded-md border bg-background transition-opacity",
              isHidden && "opacity-40"
            )}
          >
            <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
            <span className="flex-1 text-sm font-medium">{item.label}</span>

            <div className="flex flex-col">
              <button type="button" onClick={() => moveItem(item.href, "up")} disabled={idx === 0}
                className="text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed" aria-label="Move up">
                <ChevronUp className="h-3.5 w-3.5" />
              </button>
              <button type="button" onClick={() => moveItem(item.href, "down")} disabled={idx === orderedItems.length - 1}
                className="text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed" aria-label="Move down">
                <ChevronDown className="h-3.5 w-3.5" />
              </button>
            </div>

            <button type="button" onClick={() => toggleHidden(item.href)}
              className="text-muted-foreground hover:text-foreground ml-1"
              aria-label={isHidden ? "Show in sidebar" : "Hide from sidebar"}>
              {isHidden ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        );
      })}
    </div>
  );
}

// ── Theme customizer ──────────────────────────────────────────────────────────

function Label({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">
      {children}
    </p>
  );
}

function ThemeCustomizer() {
  const { config, setConfig } = useThemeCustomizer();

  function update(partial: Partial<ThemeConfig>) {
    setConfig({ ...config, ...partial });
  }

  const lightThemes = BASE_THEMES.filter((t) => t.category === "light");
  const darkThemes  = BASE_THEMES.filter((t) => t.category === "dark");
  const activeBase  = BASE_THEMES.find((t) => t.id === config.baseThemeId);

  return (
    <div className="space-y-7">

      {/* Base theme — Light */}
      <div>
        <Label>Light themes</Label>
        <div className="grid grid-cols-3 gap-2">
          {lightThemes.map((theme) => {
            const active = config.baseThemeId === theme.id;
            return (
              <button key={theme.id} type="button" onClick={() => update({ baseThemeId: theme.id })}
                className={cn(
                  "flex flex-col items-center gap-2 p-3 rounded-lg border-2 transition-all cursor-pointer",
                  active ? "border-primary" : "border-transparent hover:border-muted-foreground/30"
                )}
              >
                {/* Mini preview */}
                <span className="w-full h-10 rounded-md border border-border/60 relative overflow-hidden"
                  style={{ background: theme.vars["--background"] }}>
                  <span className="absolute inset-x-2 top-2 h-1.5 rounded-full"
                    style={{ background: theme.vars["--foreground"], opacity: 0.5 }} />
                  <span className="absolute inset-x-2 bottom-2 h-1.5 rounded-full"
                    style={{ background: theme.vars["--muted"] }} />
                </span>
                <span className="text-xs text-muted-foreground">{theme.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Base theme — Dark */}
      <div>
        <Label>Dark themes</Label>
        <div className="grid grid-cols-3 gap-2">
          {darkThemes.map((theme) => {
            const active = config.baseThemeId === theme.id;
            return (
              <button key={theme.id} type="button" onClick={() => update({ baseThemeId: theme.id })}
                className={cn(
                  "flex flex-col items-center gap-2 p-3 rounded-lg border-2 transition-all cursor-pointer",
                  active ? "border-primary" : "border-transparent hover:border-muted-foreground/30"
                )}
              >
                <span className="w-full h-10 rounded-md border border-white/10 relative overflow-hidden"
                  style={{ background: theme.vars["--background"] }}>
                  <span className="absolute inset-x-2 top-2 h-1.5 rounded-full opacity-70"
                    style={{ background: theme.vars["--foreground"] }} />
                  <span className="absolute inset-x-2 bottom-2 h-1.5 rounded-full opacity-40"
                    style={{ background: theme.vars["--muted-foreground"] }} />
                </span>
                <span className="text-xs text-muted-foreground">{theme.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Accent color */}
      <div>
        <Label>Accent color</Label>
        <div className="grid grid-cols-6 gap-2">
          {ACCENT_COLORS.map((accent) => {
            const active = config.accentId === accent.id;
            const isDark = activeBase?.category === "dark";
            const accentVars = isDark ? accent.dark : accent.light;
            return (
              <button key={accent.id} type="button" onClick={() => update({ accentId: accent.id })}
                className={cn(
                  "flex flex-col items-center gap-1.5 p-2 rounded-lg border-2 transition-all cursor-pointer",
                  active ? "border-primary" : "border-transparent hover:border-muted-foreground/30"
                )}
              >
                <span className="w-8 h-8 rounded-full border border-border/40"
                  style={{ background: accentVars["--primary"] }} />
                <span className="text-[10px] text-muted-foreground leading-none">{accent.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Border radius */}
      <div>
        <Label>Border radius</Label>
        <div className="flex gap-2">
          {RADIUS_OPTIONS.map((opt) => {
            const active = config.radius === opt.value;
            return (
              <button key={opt.value} type="button" onClick={() => update({ radius: opt.value })}
                className={cn(
                  "flex-1 flex flex-col items-center gap-2 py-3 px-2 border-2 transition-all cursor-pointer",
                  active ? "border-primary" : "border-border hover:border-muted-foreground/40"
                )}
                style={{ borderRadius: opt.value === "0rem" ? "0" : `calc(${opt.value} + 4px)` }}
              >
                <span className="w-8 h-8 border-2"
                  style={{
                    borderRadius: opt.value === "0rem" ? "0" : opt.value === "1rem" ? "9999px" : opt.value,
                    borderColor: active ? "var(--primary)" : "var(--muted-foreground)",
                    opacity: active ? 1 : 0.5,
                  }}
                />
                <span className="text-xs text-muted-foreground">{opt.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Font */}
      <div>
        <Label>Font</Label>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {FONT_OPTIONS.map((opt) => {
            const active = config.fontFamily === opt.value;
            return (
              <button key={opt.value} type="button" onClick={() => update({ fontFamily: opt.value })}
                className={cn(
                  "flex flex-col items-center gap-1.5 py-3 px-3 border-2 rounded-lg transition-all cursor-pointer",
                  active ? "border-primary bg-primary/5" : "border-border hover:border-muted-foreground/40"
                )}
              >
                <span className="text-xl font-medium leading-none" style={{ fontFamily: opt.value }}>Aa</span>
                <span className="text-xs text-muted-foreground">{opt.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Live preview */}
      <div>
        <Label>Preview</Label>
        <div className="border rounded-lg p-4 space-y-3">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center text-primary-foreground text-xs font-bold shrink-0">L</div>
            <div>
              <p className="text-sm font-semibold">Life Dashboard</p>
              <p className="text-xs text-muted-foreground">Your household OS</p>
            </div>
          </div>
          <div className="flex gap-2">
            <span className="px-3 py-1.5 text-xs font-medium rounded-md bg-primary text-primary-foreground">Primary</span>
            <span className="px-3 py-1.5 text-xs font-medium rounded-md border bg-card">Secondary</span>
            <span className="px-3 py-1.5 text-xs font-medium rounded-md bg-muted text-muted-foreground">Muted</span>
          </div>
          <p className="text-xs text-muted-foreground">
            The quick brown fox jumps over the lazy dog. 1234567890
          </p>
        </div>
      </div>

      {/* Reset */}
      <div>
        <button type="button"
          onClick={() => setConfig({ baseThemeId: "clean", accentId: "neutral", radius: "0.625rem", fontFamily: "var(--font-geist-sans), sans-serif" })}
          className="text-xs text-muted-foreground hover:text-foreground underline underline-offset-2"
        >
          Reset to defaults
        </button>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  return (
    <div className="p-6 max-w-2xl space-y-6">
      <div className="flex items-center gap-2 mb-2">
        <Settings className="h-5 w-5 text-muted-foreground" />
        <h1 className="text-xl font-semibold">Settings</h1>
      </div>

      <Section title="Appearance" icon={Palette}>
        <ThemeCustomizer />
      </Section>

      <Section title="Sidebar" icon={Layout}>
        <SidebarCustomizer />
      </Section>
    </div>
  );
}
