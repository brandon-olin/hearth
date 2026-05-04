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
import { Loader2 } from "lucide-react";
import type { components } from "@/lib/api/schema";

type Habit = components["schemas"]["HabitResponse"];
type Occurrence = components["schemas"]["OccurrenceResponse"];

// ── date helpers ──────────────────────────────────────────────────────────────

function toLocalDateString(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function buildWeek(): { date: string; dayLetter: string; dateLabel: string }[] {
  const days = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    days.push({
      date: toLocalDateString(d),
      dayLetter: d.toLocaleDateString("en-US", { weekday: "short" }).charAt(0),
      dateLabel: `${d.getMonth() + 1}/${d.getDate()}`,
    });
  }
  return days;
}

// ── 7-day tracker ─────────────────────────────────────────────────────────────

function WeekTracker({ habitId }: { habitId: string }) {
  const week = buildWeek();
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

  const { mutateAsync: generateOccs } = $api.useMutation(
    "post",
    "/habits/{habit_id}/occurrences/generate"
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
        await generateOccs({
          params: { path: { habit_id: habitId } },
          body: { from_date: date, to_date: date },
        });
        const fresh = await refetch();
        occ = fresh.data?.items.find((o) => o.scheduled_date === date) ?? null;
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
      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
        Last 7 days
      </p>
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

type Frequency = "daily" | "weekly" | "monthly" | "custom";
type PreferredTime = "morning" | "afternoon" | "evening" | "night" | "";

type FormState = {
  name: string;
  description: string;
  frequency: Frequency;
  times_per_period: string;
  period_unit: string;
  preferred_time: PreferredTime;
  start_date: string;
  is_active: boolean;
};

function blankForm(): FormState {
  return {
    name: "",
    description: "",
    frequency: "daily",
    times_per_period: "1",
    period_unit: "",
    preferred_time: "",
    start_date: toLocalDateString(new Date()),
    is_active: true,
  };
}

function formFromHabit(habit: Habit): FormState {
  return {
    name: habit.name,
    description: habit.description ?? "",
    frequency: habit.frequency as Frequency,
    times_per_period: String(habit.times_per_period ?? 1),
    period_unit: habit.period_unit ?? "",
    preferred_time: (habit.preferred_time ?? "") as PreferredTime,
    start_date: habit.start_date,
    is_active: habit.is_active,
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
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setForm(habit ? formFromHabit(habit) : blankForm());
    setConfirmDelete(false);
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
      const body = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        frequency: form.frequency,
        times_per_period:
          form.frequency !== "daily" && form.times_per_period
            ? Number(form.times_per_period)
            : null,
        period_unit:
          form.frequency === "custom" ? form.period_unit.trim() || null : null,
        preferred_time: (form.preferred_time || null) as
          | "morning"
          | "afternoon"
          | "evening"
          | "night"
          | null,
        start_date: form.start_date,
        is_active: form.is_active,
      };

      if (isEdit) {
        await updateHabit({
          params: { path: { habit_id: habit.id } },
          body,
        });
      } else {
        await createHabit({ body: { ...body, tag_ids: [] } });
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
      setSaving(false);
    }
  }

  const showTimesPerPeriod = form.frequency !== "daily";
  const showPeriodUnit = form.frequency === "custom";

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" showCloseButton className="flex flex-col gap-0 p-0">
        <SheetHeader className="px-6 py-5 border-b shrink-0">
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

          {/* Frequency + times per period */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="habit-freq">Frequency</Label>
              <Select
                id="habit-freq"
                value={form.frequency}
                onChange={(e) => set("frequency", e.target.value as Frequency)}
              >
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
                <option value="custom">Custom</option>
              </Select>
            </div>

            {showTimesPerPeriod && (
              <div className="space-y-1.5">
                <Label htmlFor="habit-times">Times per period</Label>
                <Input
                  id="habit-times"
                  type="number"
                  min={1}
                  value={form.times_per_period}
                  onChange={(e) => set("times_per_period", e.target.value)}
                />
              </div>
            )}
          </div>

          {/* Custom period unit */}
          {showPeriodUnit && (
            <div className="space-y-1.5">
              <Label htmlFor="habit-unit">Period unit</Label>
              <Input
                id="habit-unit"
                placeholder="e.g. fortnight"
                value={form.period_unit}
                onChange={(e) => set("period_unit", e.target.value)}
              />
            </div>
          )}

          {/* Preferred time + start date */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="habit-time">Preferred time</Label>
              <Select
                id="habit-time"
                value={form.preferred_time}
                onChange={(e) =>
                  set("preferred_time", e.target.value as PreferredTime)
                }
              >
                <option value="">Any time</option>
                <option value="morning">Morning</option>
                <option value="afternoon">Afternoon</option>
                <option value="evening">Evening</option>
                <option value="night">Night</option>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="habit-start">Start date</Label>
              <Input
                id="habit-start"
                type="date"
                value={form.start_date}
                onChange={(e) => set("start_date", e.target.value)}
              />
            </div>
          </div>

          {/* Active toggle */}
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="habit-active"
              checked={form.is_active}
              onChange={(e) => set("is_active", e.target.checked)}
              className="cursor-pointer"
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
