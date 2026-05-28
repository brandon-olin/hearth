"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { apiClient } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/context";
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
  Check,
  Loader2,
  PartyPopper,
  ChefHat,
  Dumbbell,
  Wallet,
  FolderKanban,
  BookOpen,
  Calendar,
  Users,
  CheckSquare,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

type OnboardingData = {
  display_name: string;
  household_name: string;
  themeConfig: ThemeConfig;
  hidden_sections: string[];
  selectedPurposes: string[];
};

// ── Steps ─────────────────────────────────────────────────────────────────────

const STEPS = [
  { id: "household", label: "Home"      },
  { id: "purpose",   label: "Goals"     },
  { id: "sections",  label: "Nav"       },
  { id: "theme",     label: "Look"      },
  { id: "done",      label: "Done"      },
] as const;

type StepId = (typeof STEPS)[number]["id"];
const DOT_STEPS = STEPS.filter((s) => s.id !== "done");

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

// ── Step: Household ───────────────────────────────────────────────────────────

function HouseholdStep({
  data,
  onChange,
}: {
  data: OnboardingData;
  onChange: (patch: Partial<OnboardingData>) => void;
}) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground leading-relaxed">
        Everything in Hearth belongs to a household — a shared space for you and anyone you invite later.
      </p>
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
        <Label htmlFor="household_name">Household name</Label>
        <Input
          id="household_name"
          placeholder="e.g. The Smiths, Our Home, Casa Brandon"
          value={data.household_name}
          onChange={(e) => onChange({ household_name: e.target.value })}
        />
      </div>
    </div>
  );
}

// ── Step: Purpose ─────────────────────────────────────────────────────────────

type PurposeOption = {
  id: string;
  label: string;
  icon: LucideIcon;
  description: string;
  /** Built-in nav hrefs to reveal when this purpose is selected */
  reveals: string[];
};

const PURPOSE_OPTIONS: PurposeOption[] = [
  {
    id: "kitchen",
    label: "Kitchen & Cooking",
    icon: ChefHat,
    description: "Recipes, groceries & meal planning",
    reveals: ["/recipes", "/grocery-lists"],
  },
  {
    id: "health",
    label: "Health & Fitness",
    icon: Dumbbell,
    description: "Workouts and activity tracking",
    reveals: ["/workouts"],
  },
  {
    id: "finance",
    label: "Budget & Finance",
    icon: Wallet,
    description: "Track spending and household budgets",
    reveals: ["/budget"],
  },
  {
    id: "projects",
    label: "House Projects",
    icon: FolderKanban,
    description: "Renovations, repairs & long-term projects",
    reveals: ["/projects"],
  },
  {
    id: "notes",
    label: "Notes & Journaling",
    icon: BookOpen,
    description: "Personal notes, documents & journaling",
    reveals: ["/notes", "/documents"],
  },
  {
    id: "planning",
    label: "Planning & Goals",
    icon: Calendar,
    description: "Calendar, goals & habit tracking",
    reveals: ["/calendar", "/goals", "/habits"],
  },
  {
    id: "tasks",
    label: "Chores & Tasks",
    icon: CheckSquare,
    description: "To-do lists and household chores",
    // To-dos is a system project, not a built-in nav item — handled separately
    // in handleSubmit via the projects API.
    reveals: [],
  },
  {
    id: "contacts",
    label: "Contacts",
    icon: Users,
    description: "Manage household contacts & relationships",
    reveals: ["/contacts"],
  },
];

function PurposeStep({
  data,
  onChange,
}: {
  data: OnboardingData;
  onChange: (patch: Partial<OnboardingData>) => void;
}) {
  function toggle(id: string) {
    const next = data.selectedPurposes.includes(id)
      ? data.selectedPurposes.filter((p) => p !== id)
      : [...data.selectedPurposes, id];
    onChange({ selectedPurposes: next });
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Select everything that applies — we&apos;ll set up your navigation accordingly.
      </p>
      <div className="grid grid-cols-2 gap-2">
        {PURPOSE_OPTIONS.map((opt) => {
          const Icon = opt.icon;
          const selected = data.selectedPurposes.includes(opt.id);
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => toggle(opt.id)}
              className={cn(
                "flex flex-col items-start gap-2 p-3 rounded-lg border-2 text-left transition-all",
                selected
                  ? "border-primary bg-primary/5"
                  : "border-border hover:border-muted-foreground/40 hover:bg-muted/30",
              )}
            >
              <div className="flex items-center justify-between w-full">
                <div className={cn(
                  "h-8 w-8 rounded-md flex items-center justify-center transition-colors",
                  selected ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground",
                )}>
                  <Icon className="h-4 w-4" />
                </div>
                <div className={cn(
                  "h-4 w-4 rounded border-2 flex items-center justify-center transition-colors shrink-0",
                  selected
                    ? "border-primary bg-primary"
                    : "border-muted-foreground/30 bg-transparent",
                )}>
                  {selected && <Check className="h-2.5 w-2.5 text-primary-foreground" />}
                </div>
              </div>
              <div>
                <p className="text-xs font-semibold leading-tight">{opt.label}</p>
                <p className="text-[11px] text-muted-foreground leading-tight mt-0.5">{opt.description}</p>
              </div>
            </button>
          );
        })}
      </div>
      {data.selectedPurposes.length === 0 && (
        <p className="text-xs text-muted-foreground text-center pt-1">
          Skip to show all sections, or select the ones that fit you.
        </p>
      )}
    </div>
  );
}

// ── Step: Theme ───────────────────────────────────────────────────────────────

function ThemeStep({
  data,
  onChange,
}: {
  data: OnboardingData;
  onChange: (patch: Partial<OnboardingData>) => void;
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
  const activeBase  = BASE_THEMES.find((t) => t.id === data.themeConfig.baseThemeId);

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">
        Changes apply live. Fine-tune further in Settings.
      </p>

      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Light</p>
        <div className="grid grid-cols-3 gap-2">
          {lightThemes.map((t) => (
            <BaseThemeCard
              key={t.id}
              theme={t}
              selected={data.themeConfig.baseThemeId === t.id}
              onSelect={() => pickBase(t.id)}
            />
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Dark</p>
        <div className="grid grid-cols-3 gap-2">
          {darkThemes.map((t) => (
            <BaseThemeCard
              key={t.id}
              theme={t}
              selected={data.themeConfig.baseThemeId === t.id}
              onSelect={() => pickBase(t.id)}
            />
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Accent</p>
        <div className="flex flex-wrap gap-2">
          {ACCENT_COLORS.map((a) => {
            const isDark = activeBase?.category === "dark";
            const accentVars = isDark ? a.dark : a.light;
            return (
              <AccentSwatch
                key={a.id}
                accent={a}
                primaryColor={accentVars["--primary"]}
                selected={data.themeConfig.accentId === a.id}
                onSelect={() => pickAccent(a.id)}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}

function BaseThemeCard({
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
      className={cn(
        "flex flex-col items-center gap-2 p-2 rounded-lg border-2 transition-all cursor-pointer",
        selected
          ? "border-primary"
          : "border-transparent hover:border-muted-foreground/30",
      )}
    >
      <span
        className="w-full h-10 rounded-md relative overflow-hidden"
        style={{
          background: theme.vars["--background"],
          border: `1px solid ${theme.category === "dark" ? "rgba(255,255,255,0.1)" : theme.vars["--border"]}`,
        }}
      >
        {/* Sidebar strip */}
        <span
          className="absolute inset-y-0 left-0 w-[28%]"
          style={{ background: theme.vars["--sidebar"] }}
        />
        {/* Foreground "text" line */}
        <span
          className="absolute h-1 rounded-full"
          style={{
            background: theme.vars["--foreground"],
            opacity: theme.category === "dark" ? 0.6 : 0.45,
            left: "36%",
            right: "10%",
            top: "28%",
          }}
        />
        {/* Muted "secondary text" line */}
        <span
          className="absolute h-1 rounded-full"
          style={{
            background: theme.category === "dark"
              ? theme.vars["--muted-foreground"]
              : theme.vars["--muted-foreground"],
            opacity: theme.category === "dark" ? 0.35 : 0.4,
            left: "36%",
            right: "22%",
            top: "56%",
          }}
        />
      </span>
      <span
        className={cn(
          "text-[10px] font-medium transition-colors",
          selected ? "text-foreground" : "text-muted-foreground",
        )}
      >
        {theme.label}
      </span>
    </button>
  );
}

function AccentSwatch({
  accent,
  primaryColor,
  selected,
  onSelect,
}: {
  accent: (typeof ACCENT_COLORS)[number];
  primaryColor: string;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button type="button" onClick={onSelect} title={accent.label} className="flex flex-col items-center gap-1.5">
      <div
        className={cn(
          "w-8 h-8 rounded-full border-2 flex items-center justify-center transition-all",
          selected ? "border-foreground scale-110 shadow-md" : "border-transparent hover:border-muted-foreground/40",
        )}
        style={{ background: primaryColor }}
      >
        {selected && <Check className="h-3.5 w-3.5 text-white drop-shadow" />}
      </div>
      <span className={cn("text-[10px] font-medium transition-colors", selected ? "text-foreground" : "text-muted-foreground")}>
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
  fromPurpose,
}: {
  data: OnboardingData;
  onChange: (patch: Partial<OnboardingData>) => void;
  fromPurpose: boolean;
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
        {fromPurpose
          ? "Here's your customized navigation — adjust as you like."
          : "Choose which sections appear in your sidebar."}
        {" "}
        <span className="text-muted-foreground/70">
          You can always change this in Settings, and every section is still reachable via search.
        </span>
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
              visible ? "border-primary/40 bg-primary/5" : "border-border hover:bg-muted/40 opacity-60",
            )}
          >
            <div className={cn(
              "h-5 w-5 rounded border-2 flex items-center justify-center shrink-0 transition-colors",
              visible ? "border-primary bg-primary" : "border-muted-foreground/30 bg-transparent",
            )}>
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
  data: OnboardingData;
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
      <h2 className="text-xl font-semibold mb-2">
        You&apos;re all set, {data.display_name.split(" ")[0] || "there"}!
      </h2>
      <p className="text-sm text-muted-foreground mb-6">Here&apos;s what we&apos;ve set up:</p>

      <div className="text-left rounded-lg border bg-muted/30 divide-y divide-border mb-6">
        {[
          { label: "Name",      value: data.display_name  },
          { label: "Household", value: data.household_name },
          { label: "Theme",     value: `${baseTheme?.label ?? "—"} · ${accent?.label ?? "—"}` },
          { label: "Sections",  value: `${visibleCount} of ${TOGGLEABLE_SECTIONS.length} visible` },
        ].map(({ label, value }) => (
          <div key={label} className="flex items-center justify-between px-4 py-2.5 text-sm">
            <span className="text-muted-foreground">{label}</span>
            <span className="font-medium">{value}</span>
          </div>
        ))}
      </div>

      {error && <p className="text-sm text-destructive mb-4">{error}</p>}

      <Button onClick={onSubmit} disabled={submitting} className="w-full">
        {submitting ? <><Loader2 className="h-4 w-4 animate-spin mr-2" />Saving…</> : "Open Hearth"}
      </Button>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function OnboardingPage() {
  const { user, isLoading } = useAuth();
  const { setConfig } = useThemeCustomizer();
  const router = useRouter();

  // If onboarding is already done, skip straight to the app.
  useEffect(() => {
    if (!isLoading && user?.preferences?.["onboarding_completed"] === true) {
      router.replace("/");
    }
  }, [isLoading, user, router]);

  const [stepIndex, setStepIndex] = useState(0);
  const [data, setData] = useState<OnboardingData>({
    display_name: user?.display_name ?? "",
    household_name: user?.household_name ?? "",
    themeConfig: DEFAULT_CONFIG,
    hidden_sections: [],
    selectedPurposes: [],
  });
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // Track whether the sections step was pre-populated by purpose selections
  const [sectionsFromPurpose, setSectionsFromPurpose] = useState(false);

  const currentStep = STEPS[stepIndex];
  const isDone = currentStep.id === "done";

  function patch(update: Partial<OnboardingData>) {
    setData((prev) => ({ ...prev, ...update }));
    setError(null);
  }

  function validate(): string | null {
    if (currentStep.id === "household") {
      if (!data.display_name.trim()) return "Please enter your name.";
      if (!data.household_name.trim()) return "Please name your household.";
    }
    return null;
  }

  function handleNext() {
    const err = validate();
    if (err) { setError(err); return; }
    setError(null);

    // When leaving the purpose step, pre-compute hidden_sections from selections
    if (currentStep.id === "purpose") {
      if (data.selectedPurposes.length === 0) {
        // Nothing selected → show everything (current default)
        patch({ hidden_sections: [] });
        setSectionsFromPurpose(false);
      } else {
        const revealedHrefs = new Set(
          data.selectedPurposes.flatMap(
            (pid) => PURPOSE_OPTIONS.find((p) => p.id === pid)?.reveals ?? [],
          ),
        );
        const hidden = TOGGLEABLE_SECTIONS.map((s) => s.href).filter(
          (href) => !revealedHrefs.has(href),
        );
        patch({ hidden_sections: hidden });
        setSectionsFromPurpose(true);
      }
    }

    setStepIndex((i) => i + 1);
  }

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);
    try {
      const preferences = {
        theme: data.themeConfig,
        sidebar: { hidden: data.hidden_sections, order: [], folders: [] },
        onboarding_completed: true,
      };

      const { error: meError } = await apiClient.PATCH("/auth/me", {
        body: { display_name: data.display_name.trim(), preferences },
      });
      if (meError) throw new Error("Failed to save your profile.");

      const { error: hhError } = await apiClient.PATCH("/households/name", {
        body: { name: data.household_name.trim() },
      });
      if (hhError) throw new Error("Failed to save household name.");

      // If the user made purpose selections, apply visibility to seeded
      // collection/project items that aren't controlled by hidden_sections.
      if (data.selectedPurposes.length > 0) {
        const wantsNotes = data.selectedPurposes.includes("notes");
        const wantsTasks = data.selectedPurposes.includes("tasks");

        if (!wantsNotes) {
          // Hide the seeded Journal collection from the sidebar.
          const { data: cols } = await apiClient.GET("/collections");
          const journal = cols?.items?.find((c) => c.kind === "journal");
          if (journal) {
            await apiClient.PATCH("/collections/{collection_id}", {
              params: { path: { collection_id: journal.id } },
              body: { show_in_nav: false },
            });
          }
        }

        if (!wantsTasks) {
          // Hide the seeded To-dos system project from the sidebar.
          const { data: projects } = await apiClient.GET("/projects", {
            params: { query: { show_in_nav: true } },
          });
          const todos = projects?.items?.find((p) => p.is_system);
          if (todos) {
            await apiClient.PATCH("/projects/{project_id}", {
              params: { path: { project_id: todos.id } },
              body: { show_in_nav: false },
            });
          }
        }
      }

      setConfig(data.themeConfig);
      applyThemeConfig(data.themeConfig, false);

      window.location.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setSubmitting(false);
    }
  }

  const STEP_TITLES: Partial<Record<StepId, string>> = {
    household: "Set up your home",
    purpose:   "What will you use Hearth for?",
    sections:  sectionsFromPurpose ? "Here's your navigation" : "Customize your navigation",
    theme:     "Choose your look",
  };

  return (
    <div className="flex items-center justify-center min-h-screen p-4">
      <div className="w-full max-w-sm">
        {!isDone && <StepDots currentId={currentStep.id} />}

        {STEP_TITLES[currentStep.id] && (
          <div className="mb-6">
            <h2 className="text-xl font-semibold">{STEP_TITLES[currentStep.id]}</h2>
          </div>
        )}

        <div className="mb-8">
          {currentStep.id === "household" && <HouseholdStep data={data} onChange={patch} />}
          {currentStep.id === "purpose"   && <PurposeStep   data={data} onChange={patch} />}
          {currentStep.id === "sections"  && (
            <SectionsStep data={data} onChange={patch} fromPurpose={sectionsFromPurpose} />
          )}
          {currentStep.id === "theme"     && <ThemeStep     data={data} onChange={patch} />}
          {currentStep.id === "done"      && (
            <DoneStep data={data} onSubmit={handleSubmit} submitting={submitting} error={error} />
          )}
        </div>

        {error && !isDone && (
          <p className="text-sm text-destructive mb-4">{error}</p>
        )}

        {!isDone && (
          <div className="flex items-center gap-3">
            {stepIndex > 0 && (
              <Button variant="outline" onClick={() => { setError(null); setStepIndex((i) => i - 1); }} className="flex-1">
                Back
              </Button>
            )}
            <Button onClick={handleNext} className="flex-1">
              Continue
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
