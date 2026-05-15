"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { setAccessToken } from "@/lib/auth/token";
import { apiClient } from "@/lib/api/client";
import { BUILTIN_NAV_ITEMS } from "@/lib/sidebar/nav-items";
import { useThemeCustomizer } from "@/lib/theme/context";
import {
  BASE_THEMES,
  ACCENT_COLORS,
  DEFAULT_CONFIG,
  applyThemeConfig,
  type ThemeConfig,
} from "@/lib/theme/presets";
import {
  LayoutGrid,
  User,
  Home,
  Palette,
  LayoutDashboard,
  Check,
  Loader2,
  Eye,
  EyeOff,
  PartyPopper,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

type WizardData = {
  display_name: string;
  email: string;
  password: string;
  confirm_password: string;
  household_name: string;
  themeConfig: ThemeConfig;
  hidden_sections: string[];
};

const DEFAULT_DATA: WizardData = {
  display_name: "",
  email: "",
  password: "",
  confirm_password: "",
  household_name: "",
  themeConfig: DEFAULT_CONFIG,
  hidden_sections: [],
};

// ── Steps ─────────────────────────────────────────────────────────────────────

const STEPS = [
  { id: "welcome",   label: "Welcome"   },
  { id: "account",   label: "Account"   },
  { id: "household", label: "Household" },
  { id: "theme",     label: "Look"      },
  { id: "sections",  label: "Dashboard" },
  { id: "done",      label: "Done"      },
] as const;

type StepId = (typeof STEPS)[number]["id"];

// ── Step progress dots ────────────────────────────────────────────────────────

// Only show dots for the "real" steps — not welcome or done.
const DOT_STEPS = STEPS.filter((s) => s.id !== "welcome" && s.id !== "done");

function StepDots({ currentId }: { currentId: StepId }) {
  const currentIndex = DOT_STEPS.findIndex((s) => s.id === currentId);
  if (currentIndex === -1) return null;
  return (
    <div className="flex items-center gap-2 mb-8">
      {DOT_STEPS.map((_, i) => (
        <div
          key={i}
          className={cn(
            "h-1.5 rounded-full transition-all duration-300",
            i === currentIndex
              ? "w-6 bg-primary"
              : i < currentIndex
              ? "w-4 bg-primary/40"
              : "w-4 bg-muted-foreground/20",
          )}
        />
      ))}
    </div>
  );
}

// ── Step: Welcome ─────────────────────────────────────────────────────────────

function WelcomeStep({ onNext }: { onNext: () => void }) {
  return (
    <div className="text-center">
      <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-primary/10 mb-6">
        <LayoutGrid className="h-8 w-8 text-primary" />
      </div>
      <h1 className="text-2xl font-semibold mb-3">Welcome to Hearth</h1>
      <p className="text-muted-foreground text-sm leading-relaxed max-w-sm mx-auto mb-8">
        Your household operating system for tasks, habits, documents, and everything
        in between. Let's get you set up in about a minute.
      </p>
      <Button onClick={onNext} className="w-full">
        Get started
      </Button>
    </div>
  );
}

// ── Step: Account ─────────────────────────────────────────────────────────────

function AccountStep({
  data,
  onChange,
  error,
}: {
  data: WizardData;
  onChange: (patch: Partial<WizardData>) => void;
  error: string | null;
}) {
  const [showPw, setShowPw] = useState(false);

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="display_name">Your name</Label>
        <Input
          id="display_name"
          placeholder="e.g. Alex"
          value={data.display_name}
          onChange={(e) => onChange({ display_name: e.target.value })}
          autoFocus
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="email">Email address</Label>
        <Input
          id="email"
          type="email"
          placeholder="you@example.com"
          value={data.email}
          onChange={(e) => onChange({ email: e.target.value })}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="password">Password</Label>
        <div className="relative">
          <Input
            id="password"
            type={showPw ? "text" : "password"}
            placeholder="At least 8 characters"
            value={data.password}
            onChange={(e) => onChange({ password: e.target.value })}
            className="pr-10"
          />
          <button
            type="button"
            onClick={() => setShowPw((v) => !v)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            aria-label={showPw ? "Hide password" : "Show password"}
          >
            {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="confirm_password">Confirm password</Label>
        <Input
          id="confirm_password"
          type={showPw ? "text" : "password"}
          placeholder="Same password again"
          value={data.confirm_password}
          onChange={(e) => onChange({ confirm_password: e.target.value })}
        />
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}

// ── Step: Household ───────────────────────────────────────────────────────────

function HouseholdStep({
  data,
  onChange,
}: {
  data: WizardData;
  onChange: (patch: Partial<WizardData>) => void;
}) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground leading-relaxed">
        Everything in Hearth belongs to a household — a shared space for
        you and anyone you invite later.
      </p>
      <div className="space-y-1.5">
        <Label htmlFor="household_name">Household name</Label>
        <Input
          id="household_name"
          placeholder="e.g. The Smiths, Our Home, Casa Brandon"
          value={data.household_name}
          onChange={(e) => onChange({ household_name: e.target.value })}
          autoFocus
        />
      </div>
    </div>
  );
}

// ── Step: Theme ───────────────────────────────────────────────────────────────

function ThemeStep({
  data,
  onChange,
}: {
  data: WizardData;
  onChange: (patch: Partial<WizardData>) => void;
}) {
  const { setConfig } = useThemeCustomizer();

  function pickBase(id: string) {
    const next = { ...data.themeConfig, baseThemeId: id };
    onChange({ themeConfig: next });
    setConfig(next);
  }

  function pickAccent(id: string) {
    const next = { ...data.themeConfig, accentId: id };
    onChange({ themeConfig: next });
    setConfig(next);
  }

  const lightThemes = BASE_THEMES.filter((t) => t.category === "light");
  const darkThemes  = BASE_THEMES.filter((t) => t.category === "dark");

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">
        Changes apply live — you'll see them right away. Fine-tune further in Settings.
      </p>

      {/* Base theme */}
      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Light
        </p>
        <div className="flex gap-2">
          {lightThemes.map((t) => (
            <BaseThemeSwatch
              key={t.id}
              theme={t}
              selected={data.themeConfig.baseThemeId === t.id}
              onSelect={() => pickBase(t.id)}
            />
          ))}
        </div>
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground pt-1">
          Dark
        </p>
        <div className="flex gap-2">
          {darkThemes.map((t) => (
            <BaseThemeSwatch
              key={t.id}
              theme={t}
              selected={data.themeConfig.baseThemeId === t.id}
              onSelect={() => pickBase(t.id)}
            />
          ))}
        </div>
      </div>

      {/* Accent color */}
      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Accent
        </p>
        <div className="flex flex-wrap gap-2">
          {ACCENT_COLORS.map((a) => (
            <AccentSwatch
              key={a.id}
              accent={a}
              selected={data.themeConfig.accentId === a.id}
              onSelect={() => pickAccent(a.id)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function BaseThemeSwatch({
  theme,
  selected,
  onSelect,
}: {
  theme: (typeof BASE_THEMES)[number];
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      title={theme.label}
      className={cn(
        "flex flex-col items-center gap-1.5 group",
      )}
    >
      <div
        className={cn(
          "w-10 h-10 rounded-lg border-2 transition-all",
          selected ? "border-primary scale-110 shadow-md" : "border-transparent hover:border-muted-foreground/40",
        )}
        style={{ background: theme.swatch }}
      />
      <span className={cn(
        "text-[10px] font-medium transition-colors",
        selected ? "text-foreground" : "text-muted-foreground",
      )}>
        {theme.label}
      </span>
    </button>
  );
}

function AccentSwatch({
  accent,
  selected,
  onSelect,
}: {
  accent: (typeof ACCENT_COLORS)[number];
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      title={accent.label}
      className={cn(
        "flex flex-col items-center gap-1.5",
      )}
    >
      <div
        className={cn(
          "w-8 h-8 rounded-full border-2 flex items-center justify-center transition-all",
          selected ? "border-foreground scale-110 shadow-md" : "border-transparent hover:border-muted-foreground/40",
        )}
        style={{ background: accent.swatch }}
      >
        {selected && <Check className="h-3.5 w-3.5 text-white drop-shadow" />}
      </div>
      <span className={cn(
        "text-[10px] font-medium transition-colors",
        selected ? "text-foreground" : "text-muted-foreground",
      )}>
        {accent.label}
      </span>
    </button>
  );
}

// ── Step: Sections ────────────────────────────────────────────────────────────

const TOGGLEABLE_SECTIONS = BUILTIN_NAV_ITEMS.filter((item) => item.href !== "/");

function SectionsStep({
  data,
  onChange,
}: {
  data: WizardData;
  onChange: (patch: Partial<WizardData>) => void;
}) {
  function toggle(href: string) {
    const hidden = data.hidden_sections.includes(href)
      ? data.hidden_sections.filter((h) => h !== href)
      : [...data.hidden_sections, href];
    onChange({ hidden_sections: hidden });
  }

  return (
    <div className="space-y-2">
      <p className="text-sm text-muted-foreground mb-3">
        Choose which sections appear in your sidebar. You can change this any time in Settings.
      </p>
      {TOGGLEABLE_SECTIONS.map((item) => {
        const Icon = item.icon as LucideIcon;
        const visible = !data.hidden_sections.includes(item.href);
        return (
          <button
            key={item.href}
            type="button"
            onClick={() => toggle(item.href)}
            className={cn(
              "w-full flex items-center gap-3 px-4 py-2.5 rounded-lg border text-left transition-colors",
              visible
                ? "border-primary/40 bg-primary/5"
                : "border-border hover:bg-muted/40 opacity-60",
            )}
          >
            <div
              className={cn(
                "h-5 w-5 rounded border-2 flex items-center justify-center shrink-0 transition-colors",
                visible ? "border-primary bg-primary" : "border-muted-foreground/30 bg-transparent",
              )}
            >
              {visible && <Check className="h-3 w-3 text-primary-foreground" />}
            </div>
            <Icon className="h-4 w-4 text-muted-foreground shrink-0" />
            <span className="text-sm font-medium">{item.label}</span>
          </button>
        );
      })}
    </div>
  );
}

// ── Step: Done ────────────────────────────────────────────────────────────────

function DoneStep({
  data,
  onSubmit,
  submitting,
  error,
}: {
  data: WizardData;
  onSubmit: () => void;
  submitting: boolean;
  error: string | null;
}) {
  const visibleCount = TOGGLEABLE_SECTIONS.length - data.hidden_sections.length;
  const baseTheme = BASE_THEMES.find((t) => t.id === data.themeConfig.baseThemeId);
  const accent    = ACCENT_COLORS.find((a) => a.id === data.themeConfig.accentId);

  return (
    <div className="text-center">
      <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-primary/10 mb-6">
        <PartyPopper className="h-8 w-8 text-primary" />
      </div>
      <h2 className="text-xl font-semibold mb-2">You're all set, {data.display_name.split(" ")[0]}!</h2>
      <p className="text-sm text-muted-foreground mb-6">
        Here's what we've got:
      </p>

      <div className="text-left rounded-lg border bg-muted/30 divide-y divide-border mb-6">
        <SummaryRow label="Household" value={data.household_name} />
        <SummaryRow label="Email" value={data.email} />
        <SummaryRow
          label="Theme"
          value={`${baseTheme?.label ?? "—"} · ${accent?.label ?? "—"}`}
        />
        <SummaryRow
          label="Sections"
          value={`${visibleCount} of ${TOGGLEABLE_SECTIONS.length} visible`}
        />
      </div>

      {error && <p className="text-sm text-destructive mb-4">{error}</p>}

      <Button onClick={onSubmit} disabled={submitting} className="w-full">
        {submitting ? (
          <><Loader2 className="h-4 w-4 animate-spin mr-2" />Creating your account…</>
        ) : (
          "Open the app"
        )}
      </Button>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between px-4 py-2.5 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

// ── Validation ────────────────────────────────────────────────────────────────

function validateStep(step: StepId, data: WizardData): string | null {
  if (step === "account") {
    if (!data.display_name.trim()) return "Please enter your name.";
    if (!data.email.trim() || !data.email.includes("@")) return "Please enter a valid email address.";
    if (data.password.length < 8) return "Password must be at least 8 characters.";
    if (data.password !== data.confirm_password) return "Passwords don't match.";
  }
  if (step === "household") {
    if (!data.household_name.trim()) return "Please name your household.";
  }
  return null;
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SetupPage() {
  const { setConfig } = useThemeCustomizer();

  const [stepIndex, setStepIndex] = useState(0);
  const [data, setData] = useState<WizardData>(DEFAULT_DATA);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const currentStep = STEPS[stepIndex];
  const isWelcome = currentStep.id === "welcome";
  const isDone    = currentStep.id === "done";

  function patch(update: Partial<WizardData>) {
    setData((prev) => ({ ...prev, ...update }));
    setError(null);
  }

  function handleBack() {
    if (stepIndex > 0) {
      setError(null);
      setStepIndex((i) => i - 1);
    }
  }

  function handleNext() {
    const validationError = validateStep(currentStep.id, data);
    if (validationError) {
      setError(validationError);
      return;
    }
    setError(null);
    setStepIndex((i) => i + 1);
  }

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);
    try {
      const preferences = {
        theme: data.themeConfig,
        sidebar: { hidden: data.hidden_sections, order: [], folders: [] },
      };

      // apiClient uses the correct base URL for both web (/api proxy) and
      // Tauri (http://localhost:1338) builds — raw fetch("/api/…") doesn't
      // work in Tauri's static export where there's no Next.js proxy.
      const { data: result, error } = await apiClient.POST("/setup", {
        body: {
          display_name: data.display_name.trim(),
          email: data.email.trim(),
          password: data.password,
          household_name: data.household_name.trim(),
          preferences,
        },
      });

      if (error || !result) {
        const detail = (error as { detail?: string } | undefined)?.detail;
        throw new Error(detail ?? "Setup failed. Please try again.");
      }

      setAccessToken(result.access_token);

      // Apply theme and sidebar locally so the app feels instant on first load.
      setConfig(data.themeConfig);
      applyThemeConfig(data.themeConfig, false);

      // Hard redirect so SetupGuard re-mounts fresh and re-checks /setup/status.
      // router.replace() keeps React state alive, leaving SetupGuard stuck on
      // "needs_setup" and showing the spinner indefinitely.
      window.location.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setSubmitting(false);
    }
  }

  const STEP_TITLES: Partial<Record<StepId, string>> = {
    account:   "Create your account",
    household: "Name your household",
    theme:     "Choose your look",
    sections:  "Customize your dashboard",
  };

  return (
    <div className="w-full max-w-sm">
      {/* Progress dots — only for account/household/theme/sections */}
      {!isWelcome && !isDone && <StepDots currentId={currentStep.id} />}

      {/* Step title */}
      {STEP_TITLES[currentStep.id] && (
        <div className="mb-6">
          <h2 className="text-xl font-semibold">{STEP_TITLES[currentStep.id]}</h2>
        </div>
      )}

      {/* Step content */}
      <div className="mb-8">
        {currentStep.id === "welcome"   && <WelcomeStep onNext={() => setStepIndex(1)} />}
        {currentStep.id === "account"   && <AccountStep   data={data} onChange={patch} error={error} />}
        {currentStep.id === "household" && <HouseholdStep data={data} onChange={patch} />}
        {currentStep.id === "theme"     && <ThemeStep     data={data} onChange={patch} />}
        {currentStep.id === "sections"  && <SectionsStep  data={data} onChange={patch} />}
        {currentStep.id === "done"      && (
          <DoneStep
            data={data}
            onSubmit={handleSubmit}
            submitting={submitting}
            error={error}
          />
        )}
      </div>

      {/* Error for non-account, non-done steps */}
      {error && currentStep.id !== "account" && currentStep.id !== "done" && (
        <p className="text-sm text-destructive mb-4">{error}</p>
      )}

      {/* Back/Continue nav — shown for account, household, theme, sections only */}
      {!isWelcome && !isDone && (
        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            onClick={handleBack}
            className="flex-1"
          >
            Back
          </Button>
          <Button onClick={handleNext} className="flex-1">
            Continue
          </Button>
        </div>
      )}
    </div>
  );
}
