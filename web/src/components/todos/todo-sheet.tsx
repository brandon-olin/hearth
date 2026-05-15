"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth/context";
import { usePermissions } from "@/lib/hooks/use-permissions";
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
import { Loader2 } from "lucide-react";
import { VisibilityPicker, type Visibility } from "@/components/visibility-picker";
import type { components } from "@/lib/api/schema";

type Todo = components["schemas"]["TodoResponse"];

// ── recurrence types ──────────────────────────────────────────────────────────

type RecurrenceFrequency =
  | "daily"
  | "weekdays"
  | "weekly"
  | "monthly_date"
  | "monthly_weekday"
  | "yearly";

type RecurrenceState = {
  frequency: RecurrenceFrequency;
  interval: number;
  days_of_week: number[]; // 0=Mon … 6=Sun (Python weekday convention)
  end_date: string; // ISO date string or ""
};

function defaultRecurrence(dueDate: string): RecurrenceState {
  const dow = dueDate
    ? (new Date(dueDate + "T00:00:00").getDay() + 6) % 7
    : 0;
  return { frequency: "weekly", interval: 1, days_of_week: [dow], end_date: "" };
}

function ruleToState(rule: Record<string, unknown>, dueDate: string): RecurrenceState {
  return {
    frequency: (rule.frequency as RecurrenceFrequency) ?? "weekly",
    interval: (rule.interval as number) ?? 1,
    days_of_week: (rule.days_of_week as number[]) ?? [
      (new Date(dueDate + "T00:00:00").getDay() + 6) % 7,
    ],
    end_date: (rule.end_date as string) ?? "",
  };
}

function stateToRule(r: RecurrenceState): Record<string, unknown> {
  const rule: Record<string, unknown> = {
    frequency: r.frequency,
    interval: r.interval,
  };
  if (r.frequency === "weekly" && r.days_of_week.length > 0) {
    rule.days_of_week = r.days_of_week;
  }
  if (r.end_date) {
    rule.end_date = r.end_date;
  }
  return rule;
}

// ── recurrence summary text ───────────────────────────────────────────────────

const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const DAY_SHORT = ["M", "T", "W", "T", "F", "S", "S"];
const ORDINAL = ["", "1st", "2nd", "3rd", "4th", "5th"];

function ordinal(n: number) {
  return ORDINAL[n] ?? `${n}th`;
}

function recurrenceSummary(r: RecurrenceState, dueDate: string): string {
  const n = r.interval;
  const due = dueDate ? new Date(dueDate + "T00:00:00") : null;

  switch (r.frequency) {
    case "daily":
      return n === 1 ? "Every day" : `Every ${n} days`;

    case "weekdays":
      return "Every weekday (Mon–Fri)";

    case "weekly": {
      const dayLabels = r.days_of_week.map((d) => DAY_NAMES[d]).join(", ");
      const freq = n === 1 ? "Every week" : `Every ${n} weeks`;
      return dayLabels ? `${freq} on ${dayLabels}` : freq;
    }

    case "monthly_date": {
      if (!due) return n === 1 ? "Monthly" : `Every ${n} months`;
      const day = due.getDate();
      const freq = n === 1 ? "Monthly" : `Every ${n} months`;
      return `${freq} on the ${ordinal(day)}`;
    }

    case "monthly_weekday": {
      if (!due) return n === 1 ? "Monthly" : `Every ${n} months`;
      const weekNum = Math.floor((due.getDate() - 1) / 7) + 1;
      const weekday = DAY_NAMES[(due.getDay() + 6) % 7];
      const freq = n === 1 ? "Monthly" : `Every ${n} months`;
      return `${freq} on the ${ordinal(weekNum)} ${weekday}`;
    }

    case "yearly": {
      if (!due) return n === 1 ? "Annually" : `Every ${n} years`;
      const label = due.toLocaleDateString("en-US", { month: "long", day: "numeric" });
      return n === 1 ? `Annually on ${label}` : `Every ${n} years on ${label}`;
    }
  }
}

function intervalUnitLabel(freq: RecurrenceFrequency, n: number): string {
  const plural = n !== 1;
  switch (freq) {
    case "daily": return plural ? "days" : "day";
    case "weekly": return plural ? "weeks" : "week";
    case "monthly_date":
    case "monthly_weekday": return plural ? "months" : "month";
    case "yearly": return plural ? "years" : "year";
    default: return "";
  }
}

// ── recurrence UI section ─────────────────────────────────────────────────────

interface RecurrenceSectionProps {
  isRecurring: boolean;
  onToggle: (v: boolean) => void;
  state: RecurrenceState;
  onChange: (s: RecurrenceState) => void;
  dueDate: string;
}

function RecurrenceSection({
  isRecurring,
  onToggle,
  state,
  onChange,
  dueDate,
}: RecurrenceSectionProps) {
  function set<K extends keyof RecurrenceState>(key: K, value: RecurrenceState[K]) {
    onChange({ ...state, [key]: value });
  }

  function toggleDay(d: number) {
    const cur = state.days_of_week;
    const next = cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d].sort();
    // Keep at least one day selected
    if (next.length === 0) return;
    set("days_of_week", next);
  }

  const showInterval = state.frequency !== "weekdays";
  const showDayPicker = state.frequency === "weekly";
  const summary = isRecurring ? recurrenceSummary(state, dueDate) : "";

  // Derive monthly description from the due date
  const monthlyDesc = (() => {
    if (!dueDate) return null;
    const d = new Date(dueDate + "T00:00:00");
    const dateNum = d.getDate();
    const weekNum = Math.floor((dateNum - 1) / 7) + 1;
    const weekdayName = DAY_NAMES[(d.getDay() + 6) % 7];
    return {
      date: `On the ${ordinal(dateNum)} of each month`,
      weekday: `On the ${ordinal(weekNum)} ${weekdayName} of each month`,
    };
  })();

  return (
    <div className="space-y-3">
      {/* Checkbox row */}
      <label className="flex items-center gap-2 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={isRecurring}
          onChange={(e) => onToggle(e.target.checked)}
          className="checkbox-themed"
        />
        <span className="text-sm font-medium">Recurring task</span>
      </label>

      {isRecurring && (
        <div className="ml-6 space-y-4 border-l-2 border-muted pl-4">
          {/* Frequency */}
          <div className="space-y-1.5">
            <Label htmlFor="recur-freq">Repeats</Label>
            <Select
              id="recur-freq"
              value={state.frequency}
              onChange={(e) => {
                const freq = e.target.value as RecurrenceFrequency;
                // Pre-fill days_of_week from due date when switching to weekly
                let days = state.days_of_week;
                if (freq === "weekly" && days.length === 0 && dueDate) {
                  days = [(new Date(dueDate + "T00:00:00").getDay() + 6) % 7];
                }
                onChange({ ...state, frequency: freq, days_of_week: days });
              }}
            >
              <option value="daily">Daily</option>
              <option value="weekdays">Every weekday (Mon–Fri)</option>
              <option value="weekly">Weekly</option>
              <option value="monthly_date">
                {monthlyDesc ? monthlyDesc.date : "Monthly on same date"}
              </option>
              <option value="monthly_weekday">
                {monthlyDesc ? monthlyDesc.weekday : "Monthly on same weekday"}
              </option>
              <option value="yearly">Yearly</option>
            </Select>
          </div>

          {/* Interval */}
          {showInterval && (
            <div className="flex items-center gap-2">
              <Label className="shrink-0 text-sm">Every</Label>
              <Input
                type="number"
                min={1}
                max={365}
                value={state.interval}
                onChange={(e) =>
                  set("interval", Math.max(1, parseInt(e.target.value, 10) || 1))
                }
                className="w-16 text-center"
              />
              <span className="text-sm text-muted-foreground">
                {intervalUnitLabel(state.frequency, state.interval)}
              </span>
            </div>
          )}

          {/* Day-of-week picker (weekly only) */}
          {showDayPicker && (
            <div className="space-y-1.5">
              <Label className="text-sm">On</Label>
              <div className="flex gap-1.5">
                {DAY_SHORT.map((label, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => toggleDay(i)}
                    className={cn(
                      "h-7 w-7 rounded-full text-xs font-medium transition-colors",
                      state.days_of_week.includes(i)
                        ? "bg-primary text-primary-foreground"
                        : "bg-muted text-muted-foreground hover:bg-muted/80"
                    )}
                    aria-label={DAY_NAMES[i]}
                    aria-pressed={state.days_of_week.includes(i)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* End date */}
          <div className="space-y-1.5">
            <Label htmlFor="recur-end" className="text-sm">
              Ends
            </Label>
            <Input
              id="recur-end"
              type="date"
              value={state.end_date}
              onChange={(e) => set("end_date", e.target.value)}
              placeholder="Never"
            />
            {state.end_date && (
              <button
                type="button"
                className="text-xs text-muted-foreground underline underline-offset-2"
                onClick={() => set("end_date", "")}
              >
                Clear end date
              </button>
            )}
          </div>

          {/* Summary */}
          {summary && (
            <p className="text-xs text-muted-foreground italic">{summary}</p>
          )}
        </div>
      )}
    </div>
  );
}

// ── form state ────────────────────────────────────────────────────────────────

type FormState = {
  title: string;
  description: string;
  status: "pending" | "in_progress" | "done" | "cancelled";
  priority: "low" | "medium" | "high" | "";
  due_date: string;
  assigned_to: string;
  link_url: string;
};

function blankForm(): FormState {
  return {
    title: "",
    description: "",
    status: "pending",
    priority: "",
    due_date: "",
    assigned_to: "",
    link_url: "",
  };
}

function formFromTodo(todo: Todo): FormState {
  return {
    title: todo.title,
    description: todo.description ?? "",
    status: todo.status as FormState["status"],
    priority: (todo.priority ?? "") as FormState["priority"],
    due_date: todo.due_date ?? "",
    assigned_to: todo.assigned_to_user_id ?? "",
    link_url: todo.link_url ?? "",
  };
}

// ── main component ────────────────────────────────────────────────────────────

interface TodoSheetProps {
  open: boolean;
  todo: Todo | null;
  /** If set, newly created todos will belong to this project */
  defaultProjectId?: string;
  onClose: () => void;
}

export function TodoSheet({ open, todo, defaultProjectId, onClose }: TodoSheetProps) {
  const qc = useQueryClient();
  const isEdit = todo !== null;
  const { user } = useAuth();
  const { can } = usePermissions();
  const isOwnItem = !todo || todo.created_by_user_id === (user as { id?: string } | null)?.id;
  const canManageThis = isOwnItem || can("todos", "manage_others");

  const [form, setForm] = useState<FormState>(blankForm);
  const [isRecurring, setIsRecurring] = useState(false);
  const [recurrenceState, setRecurrenceState] = useState<RecurrenceState>(() =>
    defaultRecurrence("")
  );
  const [visibility, setVisibility] = useState<Visibility>("household");
  const [sharedWith, setSharedWith] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data: members } = $api.useQuery("get", "/households/members", {});

  // Reset all state when the target todo changes or the sheet opens
  useEffect(() => {
    const f = todo ? formFromTodo(todo) : blankForm();
    setForm(f);
    setVisibility((todo?.visibility as Visibility) ?? "household");
    setSharedWith(todo?.shared_with_user_ids ?? []);
    setConfirmDelete(false);
    setError(null);

    if (todo?.recurring) {
      setIsRecurring(true);
      setRecurrenceState(ruleToState(todo.recurring as Record<string, unknown>, f.due_date));
    } else {
      setIsRecurring(false);
      setRecurrenceState(defaultRecurrence(f.due_date));
    }
  }, [todo, open]);

  // When the due date changes, update the recurrence day-of-week seed if not yet customised
  function handleDueDateChange(val: string) {
    setForm((prev) => ({ ...prev, due_date: val }));
    if (!isRecurring && val) {
      setRecurrenceState(defaultRecurrence(val));
    }
  }

  const { mutateAsync: createTodo } = $api.useMutation("post", "/todos");
  const { mutateAsync: updateTodo } = $api.useMutation("patch", "/todos/{todo_id}");
  const { mutateAsync: deleteTodo } = $api.useMutation("delete", "/todos/{todo_id}");

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function invalidateAll() {
    qc.invalidateQueries({ queryKey: ["get", "/todos"] });
  }

  async function handleSave() {
    if (!form.title.trim()) {
      setError("Title is required.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const recurring = isRecurring ? stateToRule(recurrenceState) : null;
      const body = {
        title: form.title.trim(),
        description: form.description.trim() || null,
        status: form.status,
        priority: (form.priority || null) as "low" | "medium" | "high" | null,
        due_date: form.due_date || null,
        assigned_to_user_id: form.assigned_to || null,
        recurring,
        link_url: form.link_url.trim() || null,
        visibility,
        shared_with_user_ids: sharedWith,
      };
      if (isEdit) {
        await updateTodo({ params: { path: { todo_id: todo.id } }, body });
      } else {
        await createTodo({
          body: {
            ...body,
            ...(defaultProjectId ? { project_id: defaultProjectId } : {}),
          },
        });
      }
      invalidateAll();
      onClose();
    } catch {
      setError("Something went wrong. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!todo) return;
    setSaving(true);
    try {
      await deleteTodo({ params: { path: { todo_id: todo.id } } });
      invalidateAll();
      onClose();
    } catch {
      setError("Delete failed. Please try again.");
      setSaving(false);
    }
  }

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" showCloseButton className="flex flex-col gap-0 p-0">
        <SheetHeader className="px-6 py-4 border-b shrink-0">
          <SheetTitle>{isEdit ? "Edit to-do" : "New to-do"}</SheetTitle>
          <SheetDescription className="sr-only">
            {isEdit ? "Edit the details of this to-do." : "Create a new to-do item."}
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {error && <p className="text-sm text-destructive">{error}</p>}

          {/* Title */}
          <div className="space-y-1.5">
            <Label htmlFor="todo-title">Title</Label>
            <Input
              id="todo-title"
              placeholder="What needs to be done?"
              value={form.title}
              onChange={(e) => set("title", e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSave()}
              autoFocus={!isEdit}
            />
          </div>

          {/* Description */}
          <div className="space-y-1.5">
            <Label htmlFor="todo-desc">Description</Label>
            <Textarea
              id="todo-desc"
              placeholder="Add details…"
              value={form.description}
              onChange={(e) => set("description", e.target.value)}
            />
          </div>

          {/* Link URL */}
          <div className="space-y-1.5">
            <Label htmlFor="todo-link">Link</Label>
            <Input
              id="todo-link"
              type="url"
              placeholder="https://… or /grocery-lists/abc"
              value={form.link_url}
              onChange={(e) => set("link_url", e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Clicking this to-do's title will open this URL. Use an internal path (e.g. /grocery-lists/…) or an external link.
            </p>
          </div>

          {/* Status + Priority */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="todo-status">Status</Label>
              <Select
                id="todo-status"
                value={form.status}
                onChange={(e) => set("status", e.target.value as FormState["status"])}
              >
                <option value="pending">To-do</option>
                <option value="in_progress">In progress</option>
                <option value="done">Done</option>
                <option value="cancelled">Cancelled</option>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="todo-priority">Priority</Label>
              <Select
                id="todo-priority"
                value={form.priority}
                onChange={(e) => set("priority", e.target.value as FormState["priority"])}
              >
                <option value="">None</option>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </Select>
            </div>
          </div>

          {/* Due date + Assigned to */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="todo-due">Due date</Label>
              <Input
                id="todo-due"
                type="date"
                value={form.due_date}
                onChange={(e) => handleDueDateChange(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="todo-assigned">Assigned to</Label>
              <Select
                id="todo-assigned"
                value={form.assigned_to}
                onChange={(e) => set("assigned_to", e.target.value)}
              >
                <option value="">Unassigned</option>
                {(members ?? []).map((m) => (
                  <option key={m.user_id} value={m.user_id}>
                    {m.display_name ?? m.email}
                  </option>
                ))}
              </Select>
            </div>
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

          {/* Recurrence */}
          <RecurrenceSection
            isRecurring={isRecurring}
            onToggle={(v) => {
              setIsRecurring(v);
              if (v && form.due_date) {
                setRecurrenceState(defaultRecurrence(form.due_date));
              }
            }}
            state={recurrenceState}
            onChange={setRecurrenceState}
            dueDate={form.due_date}
          />
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t shrink-0 space-y-2">
          <div className="flex gap-2">
            <Button className="flex-1" onClick={handleSave} disabled={saving || (isEdit && !canManageThis)}>
              {saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              {isEdit ? "Save changes" : "Create"}
            </Button>
            <Button variant="outline" onClick={onClose} disabled={saving}>
              Cancel
            </Button>
          </div>

          {isEdit && !canManageThis && (
            <p className="text-xs text-muted-foreground text-center">
              You can view this to-do but cannot edit or delete it.
            </p>
          )}

          {isEdit && canManageThis &&
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
