"use client";

import { useState } from "react";
import { Loader2, Lock } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import { usePermissions } from "@/lib/hooks/use-permissions";
import { cn } from "@/lib/utils";

// ── Role options ──────────────────────────────────────────────────────────────

const ROLE_OPTIONS = [
  { value: "viewer", label: "Everyone",        description: "Admins, Parents & Children" },
  { value: "member", label: "Parents & above", description: "Parents and Admins only" },
  { value: "owner",  label: "Admins only",     description: "Only Admins" },
] as const;

type RoleValue = typeof ROLE_OPTIONS[number]["value"];

// ── Fixed domains (not configurable) ─────────────────────────────────────────

const FIXED_DOMAINS = [
  {
    key: "notes",
    label: "Notes & journaling",
    description: "Always private to the individual",
    reason: "Notes and journaling are always private to the individual — access cannot be changed.",
  },
  {
    key: "workouts",
    label: "Workouts",
    description: "Always private to the individual",
    reason: "Workouts are always private to the individual — access cannot be changed.",
  },
];

// ── Sub-components ────────────────────────────────────────────────────────────

function RoleSelect({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (v: RoleValue) => void;
  disabled?: boolean;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as RoleValue)}
      disabled={disabled}
      className={cn(
        "text-xs rounded-md border bg-background px-2 py-1.5 pr-6",
        "focus:outline-none focus:ring-1 focus:ring-primary",
        "disabled:opacity-40 disabled:cursor-not-allowed",
      )}
    >
      {ROLE_OPTIONS.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  );
}

function FixedDomainRow({ label, description, reason }: { label: string; description: string; reason: string }) {
  const [showTip, setShowTip] = useState(false);

  return (
    <div className="grid grid-cols-[1fr_auto_auto_auto] gap-x-6 gap-y-0 items-center py-2.5 border-b last:border-0 opacity-50">
      <div>
        <p className="text-sm font-medium text-foreground">{label}</p>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
      {/* Three placeholder cells — all greyed out */}
      {(["View", "Create", "Edit/Delete Household"] as const).map((col) => (
        <div key={col} className="relative">
          <div
            className="flex items-center gap-1 text-xs text-muted-foreground cursor-default"
            onMouseEnter={() => setShowTip(true)}
            onMouseLeave={() => setShowTip(false)}
          >
            <Lock className="h-3 w-3 shrink-0" />
            <span>Private</span>
          </div>
          {showTip && col === "View" && (
            <div className="absolute left-0 top-6 z-50 w-64 rounded-md border bg-popover p-2.5 text-xs text-popover-foreground shadow-md">
              {reason}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Main section ──────────────────────────────────────────────────────────────

export function VisibilitySettingsSection() {
  const qc = useQueryClient();
  const { config, isLoading } = usePermissions();
  const [localConfig, setLocalConfig] = useState<Record<string, Record<string, string>> | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedOk, setSavedOk] = useState(false);

  // Use localConfig (in-flight edits) when set, otherwise use the fetched config.
  const displayConfig = localConfig ?? config;

  const updatePermissions = $api.useMutation("put", "/households/permissions");

  function setAction(domain: string, action: string, role: RoleValue) {
    setLocalConfig((prev) => {
      const base = prev ?? config;
      return {
        ...base,
        [domain]: {
          ...(base[domain] ?? {}),
          [action]: role,
        },
      };
    });
    setSavedOk(false);
    setSaveError(null);
  }

  async function handleSave() {
    if (!localConfig) return;
    setSaving(true);
    setSaveError(null);
    try {
      await updatePermissions.mutateAsync({ body: { config: localConfig } });
      qc.invalidateQueries({ queryKey: ["get", "/households/permissions"] });
      setLocalConfig(null);
      setSavedOk(true);
      setTimeout(() => setSavedOk(false), 2500);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to save permissions.";
      setSaveError(msg);
    } finally {
      setSaving(false);
    }
  }

  // Domain metadata — pull from the API response if available, fall back to defaults.
  const { data: permsData } = $api.useQuery("get", "/households/permissions");
  const domains = permsData?.domains ?? [
    { key: "calendar",  label: "Calendar",       description: "Events and appointments" },
    { key: "recipes",   label: "Recipes",         description: "Recipe library" },
    { key: "grocery",   label: "Grocery lists",   description: "Shopping lists" },
    { key: "projects",  label: "Projects",        description: "Projects" },
    { key: "todos",     label: "To-dos",          description: "Individual tasks" },
    { key: "documents", label: "Documents",       description: "Shared documents" },
    { key: "goals",     label: "Goals",           description: "Household goals" },
  ];

  const hasChanges = localConfig !== null;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1">
          Visibility
        </h2>
        <p className="text-sm text-muted-foreground">
          Control which household members can view, create, or modify items in each section.
          Owners and admins always have full access.
        </p>
      </div>

      <div className="border rounded-lg bg-card overflow-hidden">
        {/* Table header */}
        <div className="grid grid-cols-[1fr_auto_auto_auto] gap-x-6 gap-y-0 px-4 py-2 bg-muted/40 border-b">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Section</p>
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">View</p>
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Create</p>
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide whitespace-nowrap">
            Edit/Delete Household
          </p>
        </div>

        {/* Configurable domain rows */}
        <div className="px-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-8 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
              <span className="text-sm">Loading…</span>
            </div>
          ) : (
            domains.map((domain) => {
              const domainCfg = displayConfig[domain.key] ?? {};
              return (
                <div
                  key={domain.key}
                  className="grid grid-cols-[1fr_auto_auto_auto] gap-x-6 gap-y-0 items-center py-2.5 border-b last:border-0"
                >
                  <div>
                    <p className="text-sm font-medium">{domain.label}</p>
                    <p className="text-xs text-muted-foreground">{domain.description}</p>
                  </div>
                  <RoleSelect
                    value={domainCfg.read ?? "viewer"}
                    onChange={(v) => setAction(domain.key, "read", v)}
                  />
                  <RoleSelect
                    value={domainCfg.create ?? "viewer"}
                    onChange={(v) => setAction(domain.key, "create", v)}
                  />
                  <RoleSelect
                    value={domainCfg.manage_others ?? "member"}
                    onChange={(v) => setAction(domain.key, "manage_others", v)}
                  />
                </div>
              );
            })
          )}
        </div>

        {/* Fixed (non-configurable) domain rows */}
        <div className="px-4 border-t bg-muted/10 [&>*]:pr-4">
          {FIXED_DOMAINS.map((d) => (
            <FixedDomainRow key={d.key} label={d.label} description={d.description} reason={d.reason} />
          ))}
        </div>
      </div>

      {/* Legend */}
      <div className="rounded-md border bg-muted/20 px-4 py-3 space-y-1">
        {ROLE_OPTIONS.map((opt) => (
          <div key={opt.value} className="flex items-baseline gap-2 text-xs">
            <span className="font-medium text-foreground w-32 shrink-0">{opt.label}</span>
            <span className="text-muted-foreground">{opt.description}</span>
          </div>
        ))}
      </div>

      {/* Save bar */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleSave}
          disabled={!hasChanges || saving}
          className={cn(
            "px-4 py-2 rounded-md text-sm font-medium transition-colors",
            hasChanges && !saving
              ? "bg-primary text-primary-foreground hover:bg-primary/90"
              : "bg-muted text-muted-foreground cursor-not-allowed",
          )}
        >
          {saving ? (
            <span className="flex items-center gap-1.5">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Saving…
            </span>
          ) : (
            "Save changes"
          )}
        </button>
        {hasChanges && !saving && (
          <button
            type="button"
            onClick={() => { setLocalConfig(null); setSaveError(null); }}
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            Discard
          </button>
        )}
        {saveError && <p className="text-sm text-destructive">{saveError}</p>}
        {savedOk && <p className="text-sm text-green-600 dark:text-green-400">Saved.</p>}
      </div>
    </div>
  );
}
