"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { AppLinkPicker, type AppLinkValue } from "@/components/ui/app-link-picker";
import { VisibilityPicker, type Visibility } from "@/components/visibility-picker";
import type { components } from "@/lib/api/schema";

type Habit = components["schemas"]["HabitWithStats"] & {
  times_per_period?: number | null;
  period_unit?: string | null;
  preferred_time?: string | null;
  start_date?: string | null;
};
type Occurrence = components["schemas"]["OccurrenceResponse"];

// ── date helpers ──────────────────────────────────────────────────────────────

function toLocalDateString(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function buildWeek(
  weekOffset: number
): { date: string; dayLetter: string; dateLabel: string }[] {
  const days = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i - weekOffset * 7);
    days.push({
      date: toLocalDateString(d),
      dayLetter: d.toLocaleDateString("en-US", { weekday: "short" }).charAt(0),
      dateLabel: `${d.getMonth() + 1}/${d.getDate()}`,
    });
  }
  return days;
}

function weekLabel(weekOffset: number): string {
  if (weekOffset === 0) return "This week";
  if (weekOffset === 1) return "Last week";
  return `${weekOffset} weeks ago`;
}

// ── 7-day tracker ─────────────────────────────────────────────────────────────

function WeekTracker({ habitId }: { habitId: string }) {
  const [weekOffset, setWeekOffset] = useState(0);
  const week = buildWeek(weekOffset);
  const fromDate = week[0].date;
  const toDate = week[6].date;
  const [toggling, setToggling] = useState<Set<string>>(new Set());

  const { data: occData, refetch } = $api.useQuery(
    "get",
    "/habits/{habit_id}/occurrences",
    {
      params: {
        path: { habit_id: habitId },
        query: { from_date: fromDate, to_date: toDate, limit: 20 },
      },
    }
  );

  const { mutateAsync: createOcc } = $api.useMutation(
    "post",
    "/habits/{habit_id}/occurrences"
  );
  const { mutateAsync: updateOcc } = $api.useMutation(
    "patch",
    "/habits/{habit_id}/occurrences/{occurrence_id}"
  );

  const occByDate = new Map<string, Occurrence>();
  for (const occ of occData?.items ?? []) {
    occByDate.set(occ.scheduled_date, occ);
  }

  async function handleDayClick(date: string) {
    if (toggling.has(date)) return;
    setToggling((prev) => new Set(prev).add(date));
    try {
      let occ = occByDate.get(date) ?? null;
      if (!occ) {
        // Create an occurrence for this date and mark it completed immediately
        const created = await createOcc({
          params: { path: { habit_id: habitId } },
          body: { scheduled_date: date, status: "completed" },
        });
        refetch();
        if (created) return;
      }
      if (occ) {
        await updateOcc({
          params: { path: { habit_id: habitId, occurrence_id: occ.id } },
          body: { status: occ.status === "completed" ? "pending" : "completed" },
        });
        refetch();
      }
    } finally {
      setToggling((prev) => {
        const next = new Set(prev);
        next.delete(date);
        return next;
      });
    }
  }

  const today = toLocalDateString(new Date());

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          {weekLabel(weekOffset)}
        </p>
        <div className="flex items-center gap-0.5">
          <button
            type="button"
            onClick={() => setWeekOffset((o) => o + 1)}
            className="p-0.5 rounded hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
            aria-label="Previous week"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={() => setWeekOffset((o) => Math.max(0, o - 1))}
            disabled={weekOffset === 0}
            className="p-0.5 rounded hover:bg-muted transition-colors text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-default"
            aria-label="Next week"
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      <div className="flex gap-1">
        {week.map(({ date, dayLetter, dateLabel }) => {
          const occ = occByDate.get(date);
          const completed = occ?.status === "completed";
          const pending = occ?.status === "pending";
          const isToday = date === today;
          const spinning = toggling.has(date);

          return (
            <button
              key={date}
              type="button"
              title={dateLabel}
              onClick={() => handleDayClick(date)}
              disabled={spinning}
              className={cn(
                "flex-1 flex flex-col items-center gap-1 py-2 rounded-md transition-colors cursor-pointer disabled:cursor-wait",
                "hover:bg-muted/60"
              )}
            >
              <span
                className={cn(
                  "text-[10px] font-medium",
                  isToday ? "text-foreground" : "text-muted-foreground"
                )}
              >
                {dayLetter}
              </span>
              <span
                className={cn(
                  "w-6 h-6 rounded-full flex items-center justify-center text-xs transition-colors",
                  completed
                    ? "bg-primary text-primary-foreground"
                    : pending
                    ? "border-2 border-primary"
                    : isToday
                    ? "border border-muted-foreground/40"
                    : "border border-muted/50"
                )}
              >
                {spinning ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : completed ? (
                  "✓"
                ) : null}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── form ──────────────────────────────────────────────────────────────────────

type Frequency = "daily" | "weekly" | "monthly";

// Backend stores weekday values using Python convention: Mon=0 … Sun=6
// Display order is Sun-first (US convention): Sun(6) Mon(0) Tue(1) Wed(2) Thu(3) Fri(4) Sat(5)
const DAY_DISPLAY_ORDER = [6, 0, 1, 2, 3, 4, 5]; // maps display index → backend weekday value
const DAY_LABELS = ["S", "M", "T", "W", "T", "F", "S"]; // Sun Mon Tue Wed Thu Fri Sat
const DAY_NAMES  = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
// Indexed by backend weekday value (0=Mon…6=Sun) — used for display text
const DAY_SHORT  = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

type FormState = {
  name: string;
  description: string;
  frequency: Frequency;
  days_of_week: number[]; // weekly only
  day_of_month: string;   // monthly: "1"–"31"
  scheduled_time: string; // optional "HH:MM" for all cadences
  start_date: string;     // daily/weekly only
  is_active: boolean;
  link: AppLinkValue | null;
};

function blankForm(): FormState {
  return {
    name: "",
    description: "",
    frequency: "daily",
    days_of_week: [],
    day_of_month: "1",
    scheduled_time: "",
    start_date: toLocalDateString(new Date()),
    is_active: true,
    link: null,
  };
}

function formFromHabit(habit: Habit): FormState {
  const c = (habit.cadence ?? {}) as Record<string, unknown>;
  const linkRaw = c.link as { path: string; label: string } | null | undefined;
  const startDate = (c.start_date as string | undefined) ?? habit.start_date ?? "";
  const freq = (habit.frequency === "custom" ? "monthly" : habit.frequency) as Frequency;
  const dayOfMonth = freq === "monthly" && startDate
    ? String(new Date(startDate + "T00:00:00").getDate())
    : "1";
  return {
    name: habit.name,
    description: habit.description ?? "",
    frequency: freq,
    days_of_week: (c.days_of_week as number[] | undefined) ?? [],
    day_of_month: dayOfMonth,
    scheduled_time: (c.scheduled_time as string | undefined) ?? "",
    start_date: freq !== "monthly" ? startDate : "",
    is_active: habit.status === "active",
    link: linkRaw?.path && linkRaw?.label ? { path: linkRaw.path, label: linkRaw.label } : null,
  };
}

// ── sheet ─────────────────────────────────────────────────────────────────────

interface HabitSheetProps {
  open: boolean;
  habit: Habit | null;
  onClose: () => void;
}

export function HabitSheet({ open, habit, onClose }: HabitSheetProps) {
  const qc = useQueryClient();
  const isEdit = habit !== null;

  const [form, setForm] = useState<FormState>(blankForm);
  const [visibility, setVisibility] = useState<Visibility>("personal");
  const [sharedWith, setSharedWith] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setForm(habit ? formFromHabit(habit) : blankForm());
    setVisibility((habit?.visibility as Visibility) ?? "personal");
    setSharedWith(habit?.shared_with_user_ids ?? []);
    setConfirmDelete(false);
    setSaving(false);
    setError(null);
  }, [habit, open]);

  const { mutateAsync: createHabit } = $api.useMutation("post", "/habits");
  const { mutateAsync: updateHabit } = $api.useMutation(
    "patch",
    "/habits/{habit_id}"
  );
  const { mutateAsync: deleteHabit } = $api.useMutation(
    "delete",
    "/habits/{habit_id}"
  );

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSave() {
    if (!form.name.trim()) {
      setError("Name is required.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      // Pack cadence sub-fields into the JSONB cadence blob the API expects
      const cadence: Record<string, unknown> = {
        link: form.link ?? null,
        scheduled_time: form.scheduled_time || null,
      };

      if (form.frequency === "weekly") {
        cadence.days_of_week = form.days_of_week.length > 0 ? [...form.days_of_week].sort() : null;
        cadence.start_date = form.start_date || null;
      } else if (form.frequency === "monthly") {
        const day = Math.max(1, Math.min(31, parseInt(form.day_of_month || "1", 10)));
        cadence.start_date = `2020-01-${String(day).padStart(2, "0")}`;
        cadence.days_of_week = null;
      } else {
        // daily
        cadence.start_date = form.start_date || null;
        cadence.days_of_week = null;
      }

      const body = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        frequency: form.frequency,
        cadence,
        status: (form.is_active ? "active" : "paused") as "active" | "paused" | "archived",
        visibility,
        shared_with_user_ids: sharedWith,
      };

      if (isEdit) {
        await updateHabit({
          params: { path: { habit_id: habit.id } },
          body,
        });
      } else {
        await createHabit({ body });
      }

      qc.invalidateQueries({ queryKey: ["get", "/habits"] });
      onClose();
    } catch {
      setError("Something went wrong. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!habit) return;
    setSaving(true);
    try {
      await deleteHabit({ params: { path: { habit_id: habit.id } } });
      qc.invalidateQueries({ queryKey: ["get", "/habits"] });
      onClose();
    } catch {
      setError("Delete failed. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  // Day-of-week picker: only for weekly frequency
  const showDayPicker = form.frequency === "weekly";
  // Day-of-month picker: only for monthly
  const showDayOfMonth = form.frequency === "monthly";
  // Start date: only for daily/weekly (monthly uses day_of_month instead)
  const showStartDate = form.frequency !== "monthly";

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" showCloseButton className="flex flex-col gap-0 p-0">
        <SheetHeader className="px-6 py-4 border-b shrink-0">
          <SheetTitle>{isEdit ? "Edit habit" : "New habit"}</SheetTitle>
          <SheetDescription className="sr-only">
            {isEdit ? "Edit this habit." : "Create a new habit."}
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {error && <p className="text-sm text-destructive">{error}</p>}

          {/* Name */}
          <div className="space-y-1.5">
            <Label htmlFor="habit-name">Name</Label>
            <Input
              id="habit-name"
              placeholder="e.g. Morning run"
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSave()}
              autoFocus={!isEdit}
            />
          </div>

          {/* Description */}
          <div className="space-y-1.5">
            <Label htmlFor="habit-desc">Description</Label>
            <Textarea
              id="habit-desc"
              placeholder="Add details…"
              value={form.description}
              onChange={(e) => set("description", e.target.value)}
            />
          </div>

          {/* Frequency */}
          <div className="space-y-1.5">
            <Label htmlFor="habit-freq">Frequency</Label>
            <Select
              id="habit-freq"
              value={form.frequency}
              onChange={(e) => {
                const f = e.target.value as Frequency;
                setForm((prev) => ({
                  ...prev,
                  frequency: f,
                  days_of_week: f !== "weekly" ? [] : prev.days_of_week,
                }));
              }}
            >
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
            </Select>
          </div>

          {/* Day-of-week picker — weekly only */}
          {showDayPicker && <div className="space-y-1.5">
            <Label className="text-sm">Which days?</Label>
            <div className="flex gap-1.5">
              {DAY_LABELS.map((label, i) => {
                const dayValue = DAY_DISPLAY_ORDER[i]; // backend weekday value
                const selected = form.days_of_week.includes(dayValue);
                return (
                  <button
                    key={dayValue}
                    type="button"
                    aria-label={DAY_NAMES[i]}
                    aria-pressed={selected}
                    onClick={() => {
                      const next = selected
                        ? form.days_of_week.filter((d) => d !== dayValue)
                        : [...form.days_of_week, dayValue];
                      set("days_of_week", next);
                    }}
                    className={cn(
                      "h-7 w-7 rounded-full text-xs font-medium transition-colors",
                      selected
                        ? "bg-primary text-primary-foreground"
                        : "bg-muted text-muted-foreground hover:bg-muted/80"
                    )}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
            <p className="text-xs text-muted-foreground">
              {form.days_of_week.length === 0
                ? "Every day of the week"
                : form.days_of_week.length === 7
                ? "Every day"
                : form.days_of_week.length === 5 &&
                  !form.days_of_week.includes(5) &&
                  !form.days_of_week.includes(6)
                ? "Weekdays only"
                : [...form.days_of_week].sort().map((d) => DAY_SHORT[d]).join(", ")}
            </p>
          </div>}

          {/* Day of month — monthly only */}
          {showDayOfMonth && (
            <div className="space-y-1.5">
              <Label htmlFor="habit-day">Day of month</Label>
              <Select
                id="habit-day"
                value={form.day_of_month}
                onChange={(e) => set("day_of_month", e.target.value)}
              >
                {Array.from({ length: 31 }, (_, i) => {
                  const n = i + 1;
                  const suffix = n === 1 ? "st" : n === 2 ? "nd" : n === 3 ? "rd" : "th";
                  return (
                    <option key={n} value={String(n)}>
                      {n}{suffix}
                    </option>
                  );
                })}
              </Select>
            </div>
          )}

          {/* Start date — daily/weekly only */}
          {showStartDate && (
            <div className="space-y-1.5">
              <Label htmlFor="habit-start">Start date</Label>
              <Input
                id="habit-start"
                type="date"
                value={form.start_date}
                onChange={(e) => set("start_date", e.target.value)}
              />
            </div>
          )}

          {/* Scheduled time */}
          <div className="space-y-1.5">
            <Label htmlFor="habit-time">Scheduled time (optional)</Label>
            <Input
              id="habit-time"
              type="time"
              value={form.scheduled_time}
              onChange={(e) => set("scheduled_time", e.target.value)}
            />
            {form.scheduled_time && (
              <p className="text-xs text-muted-foreground">
                Appears at {new Date(`2000-01-01T${form.scheduled_time}`).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} on the calendar
              </p>
            )}
          </div>

          {/* Page link */}
          <div className="space-y-1.5">
            <Label>Link to page</Label>
            <AppLinkPicker
              value={form.link}
              onChange={(v) => set("link", v)}
            />
            <p className="text-xs text-muted-foreground">
              Tap the habit name to navigate to this page.
            </p>
          </div>

          {/* Visibility */}
          <div className="space-y-1.5">
            <Label>Visibility</Label>
            <VisibilityPicker
              value={visibility}
              sharedWith={sharedWith}
              onChange={(v, sw) => { setVisibility(v); setSharedWith(sw); }}
            />
          </div>

          {/* Active toggle */}
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="habit-active"
              checked={form.is_active}
              onChange={(e) => set("is_active", e.target.checked)}
              className="checkbox-themed"
            />
            <Label htmlFor="habit-active" className="cursor-pointer">
              Active
            </Label>
          </div>

          {/* 7-day tracker — only for existing habits */}
          {isEdit && (
            <div className="pt-2 border-t">
              <WeekTracker habitId={habit.id} />
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t shrink-0 space-y-2">
          <div className="flex gap-2">
            <Button className="flex-1" onClick={handleSave} disabled={saving}>
              {saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              {isEdit ? "Save changes" : "Create"}
            </Button>
            <Button variant="outline" onClick={onClose} disabled={saving}>
              Cancel
            </Button>
          </div>

          {isEdit &&
            (confirmDelete ? (
              <div className="flex gap-2">
                <Button
                  variant="destructive"
                  className="flex-1"
                  onClick={handleDelete}
                  disabled={saving}
                >
                  {saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                  Yes, delete
                </Button>
                <Button
                  variant="outline"
                  onClick={() => setConfirmDelete(false)}
                  disabled={saving}
                >
                  Cancel
                </Button>
              </div>
            ) : (
              <Button
                variant="ghost"
                className="w-full text-destructive hover:text-destructive hover:bg-destructive/10"
                onClick={() => setConfirmDelete(true)}
                disabled={saving}
              >
                Delete
              </Button>
            ))}
        </div>
      </SheetContent>
    </Sheet>
  );
}
