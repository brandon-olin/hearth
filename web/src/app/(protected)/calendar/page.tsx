"use client";

import { useState, useMemo } from "react";
import { $api } from "@/lib/api/query";
import { Button } from "@/components/ui/button";
import { EventSheet } from "@/components/calendar/event-sheet";
import { TodoSheet } from "@/components/todos/todo-sheet";
import { HabitSheet } from "@/components/habits/habit-sheet";
import { cn } from "@/lib/utils";
import {
  ChevronLeft,
  ChevronRight,
  Plus,
  MapPin,
  Clock,
} from "lucide-react";
import { usePermissions } from "@/lib/hooks/use-permissions";
import type { components } from "@/lib/api/schema";

type CalendarEvent = components["schemas"]["CalendarEventResponse"];
type Todo = components["schemas"]["TodoResponse"];
type Habit = components["schemas"]["HabitWithStats"];
type ViewMode = "month" | "week" | "day";

// ── Date helpers ──────────────────────────────────────────────────────────────

function toDateStr(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function daysInMonth(year: number, month: number): number {
  return new Date(year, month + 1, 0).getDate();
}

/** Build the grid of days for the calendar — always 6 rows × 7 cols (Mon-start). */
function buildGrid(year: number, month: number): Date[] {
  const first = new Date(year, month, 1);
  // Convert Sunday=0 to Monday=0 offset
  const startDow = (first.getDay() + 6) % 7;
  const days: Date[] = [];

  // Pad with days from the previous month
  for (let i = startDow - 1; i >= 0; i--) {
    days.push(new Date(year, month, -i));
  }

  // Current month
  const total = daysInMonth(year, month);
  for (let d = 1; d <= total; d++) {
    days.push(new Date(year, month, d));
  }

  // Pad with next-month days to reach 42 cells
  while (days.length < 42) {
    days.push(new Date(year, month + 1, days.length - total - startDow + 1));
  }

  return days;
}

/** Returns the Monday of the week containing `date`. */
function getWeekStart(date: Date): Date {
  const d = new Date(date);
  const offset = (d.getDay() + 6) % 7;
  d.setDate(d.getDate() - offset);
  d.setHours(0, 0, 0, 0);
  return d;
}

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const SHORT_MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// ── Event display helpers ─────────────────────────────────────────────────────

/**
 * The API serializes UTC datetimes without a timezone indicator (no Z / offset).
 * Without a suffix, browsers interpret the string as *local* time — wrong.
 * Appending "Z" forces correct UTC interpretation.
 */
function normalizeIso(iso: string): string {
  if (!iso.endsWith("Z") && !/[+-]\d\d:\d\d$/.test(iso)) return iso + "Z";
  return iso;
}

function formatTime(iso: string): string {
  const d = new Date(normalizeIso(iso));
  const h = d.getHours();
  const m = d.getMinutes();
  const ampm = h >= 12 ? "pm" : "am";
  const hh = h % 12 || 12;
  return m === 0 ? `${hh}${ampm}` : `${hh}:${String(m).padStart(2, "0")}${ampm}`;
}

function eventDateStr(ev: CalendarEvent): string {
  return toDateStr(new Date(normalizeIso(ev.starts_at)));
}

function sortEvents(evs: CalendarEvent[]): CalendarEvent[] {
  return [...evs].sort((a, b) => {
    if (a.all_day && !b.all_day) return -1;
    if (!a.all_day && b.all_day) return 1;
    return a.starts_at.localeCompare(b.starts_at);
  });
}

// ── Habit scheduling helpers ──────────────────────────────────────────────────

/**
 * Convert a JS Date's getDay() (Sun=0…Sat=6) to Python weekday (Mon=0…Sun=6).
 * This matches the backend's cadence.days_of_week storage format.
 */
function jsDayToPythonWeekday(jsDay: number): number {
  return (jsDay + 6) % 7;
}

/**
 * Returns true if the habit is scheduled on the given date.
 * Handles daily, weekly (days_of_week), and monthly (day-of-month from start_date).
 */
function habitScheduledOn(habit: Habit, date: Date): boolean {
  const cadence = (habit.cadence ?? {}) as Record<string, unknown>;
  const frequency = habit.frequency;

  if (frequency === "daily") return true;

  if (frequency === "weekly") {
    const daysOfWeek = (cadence.days_of_week as number[] | null) ?? null;
    if (!daysOfWeek || daysOfWeek.length === 0) return true; // default: every day
    const pyWeekday = jsDayToPythonWeekday(date.getDay());
    return daysOfWeek.includes(pyWeekday);
  }

  if (frequency === "monthly") {
    const startDate = cadence.start_date as string | null;
    if (!startDate) return false;
    // Repeat on the same day-of-month as start_date
    const startDay = new Date(startDate + "T00:00:00").getDate();
    return date.getDate() === startDay;
  }

  return false;
}

// ── Shared sub-components ─────────────────────────────────────────────────────

function EventListItem({
  event,
  onClick,
}: {
  event: CalendarEvent;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left px-3 py-2.5 rounded-lg hover:bg-accent transition-colors"
    >
      <div className="flex items-start gap-2">
        <div className="mt-1.5 h-2 w-2 rounded-full bg-primary shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium truncate">{event.title}</p>
          <div className="flex items-center gap-2 mt-0.5 text-xs text-muted-foreground">
            {event.all_day ? (
              <span>All day</span>
            ) : (
              <span className="flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {formatTime(event.starts_at)}
                {event.ends_at && ` – ${formatTime(event.ends_at)}`}
              </span>
            )}
            {event.location && (
              <span className="flex items-center gap-1 truncate">
                <MapPin className="h-3 w-3 shrink-0" />
                {event.location}
              </span>
            )}
          </div>
        </div>
      </div>
    </button>
  );
}

function TodoListItem({ todo, onClick }: { todo: Todo; onClick: () => void }) {
  const isDone = todo.status === "done";
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left px-3 py-2.5 rounded-lg hover:bg-accent transition-colors"
    >
      <div className="flex items-start gap-2">
        <div className="mt-1.5 h-2 w-2 rounded-full cal-chip-todo shrink-0" />
        <div className="min-w-0 flex-1">
          <p className={cn("text-sm font-medium truncate", isDone && "line-through text-muted-foreground")}>
            {todo.title}
          </p>
          {todo.priority && (
            <p className="text-xs text-muted-foreground mt-0.5 capitalize">{todo.priority}</p>
          )}
        </div>
      </div>
    </button>
  );
}

function HabitListItem({ habit, onClick }: { habit: Habit; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left px-3 py-2.5 rounded-lg hover:bg-accent transition-colors"
    >
      <div className="flex items-start gap-2">
        <div className="mt-1.5 h-2 w-2 rounded-full cal-chip-habit shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium truncate">{habit.name}</p>
          <p className="text-xs text-muted-foreground mt-0.5 capitalize">{habit.frequency}</p>
        </div>
      </div>
    </button>
  );
}

// ── Month view ────────────────────────────────────────────────────────────────

function DayCell({
  day,
  isCurrentMonth,
  isToday,
  isSelected,
  events,
  todos,
  habits,
  onClick,
}: {
  day: Date;
  isCurrentMonth: boolean;
  isToday: boolean;
  isSelected: boolean;
  events: CalendarEvent[];
  todos: Todo[];
  habits: Habit[];
  onClick: () => void;
}) {
  // Budget the 3 visible slots across events, todos, habits in order
  const allItems: Array<{ kind: "event" | "todo" | "habit"; label: string; isDone?: boolean }> = [
    ...events.map((ev) => ({
      kind: "event" as const,
      label: ev.all_day ? ev.title : `${formatTime(ev.starts_at)} ${ev.title}`,
    })),
    ...todos.map((t) => ({
      kind: "todo" as const,
      label: t.title,
      isDone: t.status === "done",
    })),
    ...habits.map((h) => ({
      kind: "habit" as const,
      label: h.name,
    })),
  ];

  const shown = allItems.slice(0, 3);
  const overflow = allItems.length - 3;

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "relative min-h-[72px] p-1.5 text-left rounded-lg border transition-colors w-full",
        "hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        isCurrentMonth ? "bg-card" : "bg-muted/30 opacity-50",
        isSelected && !isToday && "ring-2 ring-primary",
      )}
    >
      <span
        className={cn(
          "flex h-6 w-6 items-center justify-center rounded-full text-xs font-medium",
          isToday
            ? "bg-primary text-primary-foreground"
            : "text-foreground",
        )}
      >
        {day.getDate()}
      </span>

      <div className="mt-1 space-y-0.5">
        {shown.map((item, i) => (
          <div
            key={i}
            className={cn(
              "truncate rounded px-1 py-0.5 text-[10px] font-medium leading-tight",
              item.kind === "event" && "bg-primary/15 text-primary",
              item.kind === "todo" && "cal-chip-todo opacity-90",
              item.kind === "habit" && "cal-chip-habit opacity-90",
              item.isDone && "line-through opacity-50",
            )}
          >
            {item.label}
          </div>
        ))}
        {overflow > 0 && (
          <div className="text-[10px] text-muted-foreground pl-1">+{overflow} more</div>
        )}
      </div>
    </button>
  );
}

function MonthView({
  year,
  month,
  todayStr,
  selectedDate,
  eventsByDate,
  todosByDate,
  habitsByDate,
  isLoading,
  onSelectDate,
  onEditEvent,
  onCreateEvent,
  onEditTodo,
  onEditHabit,
  canCreate,
}: {
  year: number;
  month: number;
  todayStr: string;
  selectedDate: string;
  eventsByDate: Map<string, CalendarEvent[]>;
  todosByDate: Map<string, Todo[]>;
  habitsByDate: Map<string, Habit[]>;
  isLoading: boolean;
  onSelectDate: (d: string) => void;
  onEditEvent: (ev: CalendarEvent) => void;
  onCreateEvent: (date?: string) => void;
  onEditTodo: (todo: Todo) => void;
  onEditHabit: (habit: Habit) => void;
  canCreate: boolean;
}) {
  const grid = useMemo(() => buildGrid(year, month), [year, month]);
  const selectedEvents = useMemo(
    () => sortEvents(eventsByDate.get(selectedDate) ?? []),
    [eventsByDate, selectedDate]
  );
  const selectedTodos = useMemo(
    () => todosByDate.get(selectedDate) ?? [],
    [todosByDate, selectedDate]
  );
  const selectedHabits = useMemo(
    () => habitsByDate.get(selectedDate) ?? [],
    [habitsByDate, selectedDate]
  );

  const selectedDateLabel = new Date(selectedDate + "T00:00:00").toLocaleDateString(undefined, {
    weekday: "long", month: "long", day: "numeric",
  });

  const totalSelected = selectedEvents.length + selectedTodos.length + selectedHabits.length;

  return (
    <div className="flex flex-1 min-h-0 overflow-hidden">
      {/* Month grid */}
      <div className="flex-1 overflow-auto p-4">
        {/* Day-of-week headers */}
        <div className="grid grid-cols-7 gap-1 mb-1">
          {DAY_NAMES.map((d) => (
            <div key={d} className="py-1 text-center text-xs font-medium text-muted-foreground">
              {d}
            </div>
          ))}
        </div>

        {/* Day cells */}
        <div className="grid grid-cols-7 gap-1">
          {grid.map((day, i) => {
            const dateStr = toDateStr(day);
            return (
              <DayCell
                key={i}
                day={day}
                isCurrentMonth={day.getMonth() === month}
                isToday={dateStr === todayStr}
                isSelected={dateStr === selectedDate}
                events={eventsByDate.get(dateStr) ?? []}
                todos={todosByDate.get(dateStr) ?? []}
                habits={habitsByDate.get(dateStr) ?? []}
                onClick={() => onSelectDate(dateStr)}
              />
            );
          })}
        </div>

        {isLoading && (
          <p className="mt-4 text-center text-xs text-muted-foreground">Loading…</p>
        )}
      </div>

      {/* Right sidebar */}
      <div className="w-72 shrink-0 border-l flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b shrink-0">
          <p className="text-sm font-medium">{selectedDateLabel}</p>
          {canCreate && (
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => onCreateEvent(selectedDate)}
            >
              <Plus className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>

        <div className="flex-1 overflow-y-auto px-2 py-2 min-h-0">
          {totalSelected === 0 ? (
            <div className="py-8 text-center">
              <p className="text-xs text-muted-foreground">No events</p>
              {canCreate && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="mt-2 h-7 text-xs"
                  onClick={() => onCreateEvent(selectedDate)}
                >
                  <Plus className="h-3 w-3 mr-1" />
                  Add event
                </Button>
              )}
            </div>
          ) : (
            <div className="space-y-0.5">
              {selectedEvents.map((ev) => (
                <EventListItem key={ev.id} event={ev} onClick={() => onEditEvent(ev)} />
              ))}
              {selectedTodos.map((t) => (
                <TodoListItem key={t.id} todo={t} onClick={() => onEditTodo(t)} />
              ))}
              {selectedHabits.map((h) => (
                <HabitListItem key={h.id} habit={h} onClick={() => onEditHabit(h)} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Week view ─────────────────────────────────────────────────────────────────

function WeekView({
  weekStart,
  todayStr,
  eventsByDate,
  todosByDate,
  habitsByDate,
  isLoading,
  onEditEvent,
  onCreateEvent,
  onEditTodo,
  onEditHabit,
  canCreate,
}: {
  weekStart: Date;
  todayStr: string;
  eventsByDate: Map<string, CalendarEvent[]>;
  todosByDate: Map<string, Todo[]>;
  habitsByDate: Map<string, Habit[]>;
  isLoading: boolean;
  onEditEvent: (ev: CalendarEvent) => void;
  onCreateEvent: (date?: string) => void;
  onEditTodo: (todo: Todo) => void;
  onEditHabit: (habit: Habit) => void;
  canCreate: boolean;
}) {
  const days = useMemo(() => {
    return Array.from({ length: 7 }, (_, i) => {
      const d = new Date(weekStart);
      d.setDate(weekStart.getDate() + i);
      return d;
    });
  }, [weekStart]);

  return (
    <div className="flex-1 overflow-auto p-4">
      {isLoading && (
        <p className="text-center text-xs text-muted-foreground mb-3">Loading…</p>
      )}
      <div className="grid grid-cols-7 gap-2 min-w-[560px]">
        {days.map((day) => {
          const dateStr = toDateStr(day);
          const isToday = dateStr === todayStr;
          const isPast = dateStr < todayStr;
          const dayEvents = sortEvents(eventsByDate.get(dateStr) ?? []);
          const dayTodos = todosByDate.get(dateStr) ?? [];
          const dayHabits = habitsByDate.get(dateStr) ?? [];

          return (
            <div key={dateStr} className="flex flex-col min-h-[200px]">
              {/* Day header */}
              <div
                className={cn(
                  "flex flex-col items-center pb-2 mb-2 border-b",
                  isToday ? "border-primary/40" : "border-border"
                )}
              >
                <span
                  className={cn(
                    "text-[11px] font-medium uppercase tracking-wide",
                    isToday ? "text-primary" : isPast ? "text-muted-foreground/50" : "text-muted-foreground"
                  )}
                >
                  {day.toLocaleDateString(undefined, { weekday: "short" })}
                </span>
                <span
                  className={cn(
                    "flex h-7 w-7 items-center justify-center rounded-full text-sm font-semibold mt-0.5",
                    isToday
                      ? "bg-primary text-primary-foreground"
                      : isPast
                      ? "text-muted-foreground/50"
                      : "text-foreground"
                  )}
                >
                  {day.getDate()}
                </span>
              </div>

              {/* Items */}
              <div className="flex flex-col gap-1 flex-1">
                {dayEvents.map((ev) => (
                  <button
                    key={ev.id}
                    type="button"
                    onClick={() => onEditEvent(ev)}
                    className="w-full text-left rounded-md px-2 py-1.5 bg-primary/10 hover:bg-primary/20 transition-colors text-primary text-[11px] leading-snug"
                  >
                    <div className="font-medium truncate">{ev.title}</div>
                    {!ev.all_day && (
                      <div className="opacity-70 text-[10px]">
                        {formatTime(ev.starts_at)}
                        {ev.ends_at && ` – ${formatTime(ev.ends_at)}`}
                      </div>
                    )}
                    {ev.all_day && (
                      <div className="opacity-70 text-[10px]">All day</div>
                    )}
                  </button>
                ))}

                {dayTodos.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => onEditTodo(t)}
                    className="w-full text-left rounded-md px-2 py-1.5 cal-chip-todo opacity-90 hover:opacity-100 transition-opacity text-[11px] leading-snug"
                  >
                    <div className={cn("font-medium truncate", t.status === "done" && "line-through opacity-60")}>
                      {t.title}
                    </div>
                    <div className="opacity-70 text-[10px]">Todo</div>
                  </button>
                ))}

                {dayHabits.map((h) => (
                  <button
                    key={h.id}
                    type="button"
                    onClick={() => onEditHabit(h)}
                    className="w-full text-left rounded-md px-2 py-1.5 cal-chip-habit opacity-90 hover:opacity-100 transition-opacity text-[11px] leading-snug"
                  >
                    <div className="font-medium truncate">{h.name}</div>
                    <div className="opacity-70 text-[10px] capitalize">{h.frequency}</div>
                  </button>
                ))}

                {canCreate && (
                  <button
                    type="button"
                    onClick={() => onCreateEvent(dateStr)}
                    className="mt-auto w-full rounded-md py-1 text-[11px] text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors opacity-0 hover:opacity-100 group-hover:opacity-100 focus:opacity-100"
                    aria-label={`Add event on ${dateStr}`}
                  >
                    <Plus className="h-3 w-3 mx-auto" />
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Day view ──────────────────────────────────────────────────────────────────

function DayView({
  selectedDate,
  todayStr,
  eventsByDate,
  todosByDate,
  habitsByDate,
  isLoading,
  onEditEvent,
  onCreateEvent,
  onEditTodo,
  onEditHabit,
  canCreate,
}: {
  selectedDate: string;
  todayStr: string;
  eventsByDate: Map<string, CalendarEvent[]>;
  todosByDate: Map<string, Todo[]>;
  habitsByDate: Map<string, Habit[]>;
  isLoading: boolean;
  onEditEvent: (ev: CalendarEvent) => void;
  onCreateEvent: (date?: string) => void;
  onEditTodo: (todo: Todo) => void;
  onEditHabit: (habit: Habit) => void;
  canCreate: boolean;
}) {
  const dayEvents = useMemo(
    () => sortEvents(eventsByDate.get(selectedDate) ?? []),
    [eventsByDate, selectedDate]
  );
  const dayTodos = todosByDate.get(selectedDate) ?? [];
  const dayHabits = habitsByDate.get(selectedDate) ?? [];
  const total = dayEvents.length + dayTodos.length + dayHabits.length;

  return (
    <div className="flex-1 overflow-auto p-6 max-w-2xl mx-auto w-full">
      {isLoading && (
        <p className="text-center text-xs text-muted-foreground mb-4">Loading…</p>
      )}

      {total === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <p className="text-sm text-muted-foreground">No events this day.</p>
          {canCreate && (
            <Button
              variant="outline"
              size="sm"
              className="mt-4"
              onClick={() => onCreateEvent(selectedDate)}
            >
              <Plus className="h-4 w-4 mr-1" />
              Add event
            </Button>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          {dayEvents.map((ev) => (
            <button
              key={ev.id}
              type="button"
              onClick={() => onEditEvent(ev)}
              className="w-full text-left flex items-start gap-4 rounded-xl border bg-card px-5 py-4 hover:bg-accent transition-colors group"
            >
              {/* Time column */}
              <div className="w-20 shrink-0 text-right">
                {ev.all_day ? (
                  <span className="text-xs text-muted-foreground">All day</span>
                ) : (
                  <div className="text-xs text-muted-foreground space-y-0.5">
                    <div className="font-medium text-foreground">
                      {formatTime(ev.starts_at)}
                    </div>
                    {ev.ends_at && (
                      <div>{formatTime(ev.ends_at)}</div>
                    )}
                  </div>
                )}
              </div>
              <div className="w-1 self-stretch rounded-full bg-primary shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold">{ev.title}</p>
                {ev.location && (
                  <p className="flex items-center gap-1 text-xs text-muted-foreground mt-1">
                    <MapPin className="h-3 w-3 shrink-0" />
                    {ev.location}
                  </p>
                )}
                {ev.description && (
                  <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                    {ev.description}
                  </p>
                )}
              </div>
            </button>
          ))}

          {dayTodos.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => onEditTodo(t)}
              className="w-full text-left flex items-start gap-4 rounded-xl border bg-card px-5 py-4 hover:bg-accent transition-colors"
            >
              <div className="w-20 shrink-0 text-right">
                <span className="text-xs text-muted-foreground">Todo</span>
              </div>
              <div className="w-1 self-stretch rounded-full cal-chip-todo shrink-0" />
              <div className="flex-1 min-w-0">
                <p className={cn(
                  "text-sm font-semibold",
                  t.status === "done" && "line-through text-muted-foreground"
                )}>
                  {t.title}
                </p>
                {t.description && (
                  <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{t.description}</p>
                )}
                {t.priority && (
                  <p className="text-xs text-muted-foreground mt-0.5 capitalize">{t.priority} priority</p>
                )}
              </div>
            </button>
          ))}

          {dayHabits.map((h) => (
            <button
              key={h.id}
              type="button"
              onClick={() => onEditHabit(h)}
              className="w-full text-left flex items-start gap-4 rounded-xl border bg-card px-5 py-4 hover:bg-accent transition-colors"
            >
              <div className="w-20 shrink-0 text-right">
                <span className="text-xs text-muted-foreground capitalize">{h.frequency}</span>
              </div>
              <div className="w-1 self-stretch rounded-full cal-chip-habit shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold">{h.name}</p>
                {h.description && (
                  <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{h.description}</p>
                )}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CalendarPage() {
  const today = new Date();
  const todayStr = toDateStr(today);
  const { can } = usePermissions();

  const [view, setView] = useState<ViewMode>("month");
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth());
  const [selectedDate, setSelectedDate] = useState(todayStr);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editingEvent, setEditingEvent] = useState<CalendarEvent | null>(null);
  const [newEventDate, setNewEventDate] = useState<string | undefined>(undefined);
  const [todoSheetOpen, setTodoSheetOpen] = useState(false);
  const [editingTodo, setEditingTodo] = useState<Todo | null>(null);
  const [habitSheetOpen, setHabitSheetOpen] = useState(false);
  const [editingHabit, setEditingHabit] = useState<Habit | null>(null);

  // Compute the current week start based on selectedDate (for week/day nav)
  const weekStart = useMemo(() => getWeekStart(new Date(selectedDate + "T00:00:00")), [selectedDate]);
  const weekEnd = useMemo(() => {
    const d = new Date(weekStart);
    d.setDate(d.getDate() + 6);
    return d;
  }, [weekStart]);

  // Fetch window: padded for the current view.
  const fetchFrom = useMemo(() => {
    if (view === "month") return toDateStr(new Date(year, month, -6));
    if (view === "week") {
      const d = new Date(weekStart);
      d.setDate(d.getDate() - 1);
      return toDateStr(d);
    }
    const d = new Date(selectedDate + "T00:00:00");
    d.setDate(d.getDate() - 1);
    return toDateStr(d);
  }, [view, year, month, weekStart, selectedDate]);

  const fetchTo = useMemo(() => {
    if (view === "month") return toDateStr(new Date(year, month + 1, 7));
    if (view === "week") {
      const d = new Date(weekEnd);
      d.setDate(d.getDate() + 2);
      return toDateStr(d);
    }
    const d = new Date(selectedDate + "T00:00:00");
    d.setDate(d.getDate() + 2);
    return toDateStr(d);
  }, [view, year, month, weekEnd, selectedDate]);

  // ── Fetch events ────────────────────────────────────────────────────────────
  const { data: eventsData, isLoading: eventsLoading } = $api.useQuery("get", "/events", {
    params: { query: { starts_after: fetchFrom, starts_before: fetchTo, limit: 200 } },
  });

  // ── Fetch todos with due dates in the visible window ────────────────────────
  const { data: todosData } = $api.useQuery("get", "/todos", {
    params: {
      query: {
        due_date_from: fetchFrom,
        due_date_to: fetchTo,
        limit: 500,
      },
    },
  });

  // ── Fetch active habits ─────────────────────────────────────────────────────
  const { data: habitsData } = $api.useQuery("get", "/habits", {
    params: { query: { limit: 200 } },
  });

  const events = eventsData?.items ?? [];
  const todos = (todosData?.items ?? []).filter((t) => t.due_date != null);
  const activeHabits = (habitsData?.items ?? []).filter((h) => h.status === "active");

  // ── Build lookup maps ───────────────────────────────────────────────────────

  const eventsByDate = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>();
    for (const ev of events) {
      const key = eventDateStr(ev);
      const list = map.get(key) ?? [];
      list.push(ev);
      map.set(key, list);
    }
    return map;
  }, [events]);

  const todosByDate = useMemo(() => {
    const map = new Map<string, Todo[]>();
    for (const t of todos) {
      if (!t.due_date) continue;
      const list = map.get(t.due_date) ?? [];
      list.push(t);
      map.set(t.due_date, list);
    }
    return map;
  }, [todos]);

  /**
   * For habits: iterate every date in the visible window and check which
   * habits are scheduled on that day. This is purely client-side — no extra API calls.
   */
  const habitsByDate = useMemo(() => {
    const map = new Map<string, Habit[]>();
    const from = new Date(fetchFrom + "T00:00:00");
    const to = new Date(fetchTo + "T00:00:00");
    const cursor = new Date(from);
    while (cursor <= to) {
      const dateStr = toDateStr(cursor);
      const scheduled = activeHabits.filter((h) => habitScheduledOn(h, cursor));
      if (scheduled.length > 0) map.set(dateStr, scheduled);
      cursor.setDate(cursor.getDate() + 1);
    }
    return map;
  }, [activeHabits, fetchFrom, fetchTo]);

  // ── Navigation ──────────────────────────────────────────────────────────────

  function prevPeriod() {
    if (view === "month") {
      if (month === 0) { setYear((y) => y - 1); setMonth(11); }
      else setMonth((m) => m - 1);
    } else if (view === "week") {
      const prev = new Date(weekStart);
      prev.setDate(prev.getDate() - 7);
      setSelectedDate(toDateStr(prev));
    } else {
      const prev = new Date(selectedDate + "T00:00:00");
      prev.setDate(prev.getDate() - 1);
      setSelectedDate(toDateStr(prev));
    }
  }

  function nextPeriod() {
    if (view === "month") {
      if (month === 11) { setYear((y) => y + 1); setMonth(0); }
      else setMonth((m) => m + 1);
    } else if (view === "week") {
      const next = new Date(weekStart);
      next.setDate(next.getDate() + 7);
      setSelectedDate(toDateStr(next));
    } else {
      const next = new Date(selectedDate + "T00:00:00");
      next.setDate(next.getDate() + 1);
      setSelectedDate(toDateStr(next));
    }
  }

  function goToday() {
    setYear(today.getFullYear());
    setMonth(today.getMonth());
    setSelectedDate(todayStr);
  }

  // ── Event sheet helpers ─────────────────────────────────────────────────────

  function openCreate(date?: string) {
    setEditingEvent(null);
    setNewEventDate(date ?? selectedDate);
    setSheetOpen(true);
  }
  function openEditEvent(ev: CalendarEvent) {
    setEditingEvent(ev);
    setNewEventDate(undefined);
    setSheetOpen(true);
  }
  function handleEventClose() {
    setSheetOpen(false);
    setTimeout(() => { setEditingEvent(null); setNewEventDate(undefined); }, 300);
  }

  // ── Todo sheet helpers ──────────────────────────────────────────────────────

  function openEditTodo(todo: Todo) {
    setEditingTodo(todo);
    setTodoSheetOpen(true);
  }
  function handleTodoClose() {
    setTodoSheetOpen(false);
    setTimeout(() => setEditingTodo(null), 300);
  }

  // ── Habit sheet helpers ─────────────────────────────────────────────────────

  function openEditHabit(habit: Habit) {
    setEditingHabit(habit);
    setHabitSheetOpen(true);
  }
  function handleHabitClose() {
    setHabitSheetOpen(false);
    setTimeout(() => setEditingHabit(null), 300);
  }

  // ── Period label ────────────────────────────────────────────────────────────

  const periodLabel = useMemo(() => {
    if (view === "month") return `${MONTH_NAMES[month]} ${year}`;
    if (view === "week") {
      const s = weekStart;
      const e = weekEnd;
      if (s.getFullYear() !== e.getFullYear()) {
        return `${SHORT_MONTHS[s.getMonth()]} ${s.getDate()}, ${s.getFullYear()} – ${SHORT_MONTHS[e.getMonth()]} ${e.getDate()}, ${e.getFullYear()}`;
      }
      if (s.getMonth() === e.getMonth()) {
        return `${MONTH_NAMES[s.getMonth()]} ${s.getDate()}–${e.getDate()}, ${e.getFullYear()}`;
      }
      return `${SHORT_MONTHS[s.getMonth()]} ${s.getDate()} – ${SHORT_MONTHS[e.getMonth()]} ${e.getDate()}, ${e.getFullYear()}`;
    }
    return new Date(selectedDate + "T00:00:00").toLocaleDateString(undefined, {
      weekday: "long", month: "long", day: "numeric", year: "numeric",
    });
  }, [view, month, year, weekStart, weekEnd, selectedDate]);

  function handleViewChange(v: ViewMode) {
    if (v === "week" || v === "day") {
      const sel = new Date(selectedDate + "T00:00:00");
      if (view === "month" && (sel.getFullYear() !== year || sel.getMonth() !== month)) {
        setSelectedDate(todayStr);
      }
    }
    if (v === "month") {
      const sel = new Date(selectedDate + "T00:00:00");
      setYear(sel.getFullYear());
      setMonth(sel.getMonth());
    }
    setView(v);
  }

  const isNotToday =
    view === "month"
      ? year !== today.getFullYear() || month !== today.getMonth()
      : view === "week"
      ? toDateStr(weekStart) !== toDateStr(getWeekStart(today))
      : selectedDate !== todayStr;

  const isLoading = eventsLoading;

  return (
    <div className="flex flex-col h-full">
      {/* Top bar */}
      <div className="flex items-center justify-between px-6 py-4 border-b shrink-0 gap-4 flex-wrap">
        <div className="flex items-center gap-3 min-w-0">
          <h1 className="text-xl font-semibold truncate">{periodLabel}</h1>
          <div className="flex items-center gap-0.5">
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={prevPeriod}>
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={nextPeriod}>
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
          {isNotToday && (
            <Button variant="outline" size="sm" className="h-7 text-xs" onClick={goToday}>
              Today
            </Button>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* View switcher */}
          <div className="flex items-center rounded-md border overflow-hidden text-xs">
            {(["month", "week", "day"] as ViewMode[]).map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => handleViewChange(v)}
                className={cn(
                  "px-3 py-1.5 font-medium capitalize transition-colors cursor-pointer",
                  view === v
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted"
                )}
              >
                {v}
              </button>
            ))}
          </div>

          {can("calendar", "create") && (
            <Button size="sm" onClick={() => openCreate()}>
              <Plus className="h-4 w-4 mr-1" />
              New event
            </Button>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {view === "month" && (
          <MonthView
            year={year}
            month={month}
            todayStr={todayStr}
            selectedDate={selectedDate}
            eventsByDate={eventsByDate}
            todosByDate={todosByDate}
            habitsByDate={habitsByDate}
            isLoading={isLoading}
            onSelectDate={(d) => {
              setSelectedDate(d);
              const clicked = new Date(d + "T00:00:00");
              if (clicked.getMonth() !== month) {
                setYear(clicked.getFullYear());
                setMonth(clicked.getMonth());
              }
            }}
            onEditEvent={openEditEvent}
            onCreateEvent={openCreate}
            onEditTodo={openEditTodo}
            onEditHabit={openEditHabit}
            canCreate={can("calendar", "create")}
          />
        )}

        {view === "week" && (
          <WeekView
            weekStart={weekStart}
            todayStr={todayStr}
            eventsByDate={eventsByDate}
            todosByDate={todosByDate}
            habitsByDate={habitsByDate}
            isLoading={isLoading}
            onEditEvent={openEditEvent}
            onCreateEvent={openCreate}
            onEditTodo={openEditTodo}
            onEditHabit={openEditHabit}
            canCreate={can("calendar", "create")}
          />
        )}

        {view === "day" && (
          <DayView
            selectedDate={selectedDate}
            todayStr={todayStr}
            eventsByDate={eventsByDate}
            todosByDate={todosByDate}
            habitsByDate={habitsByDate}
            isLoading={isLoading}
            onEditEvent={openEditEvent}
            onCreateEvent={openCreate}
            onEditTodo={openEditTodo}
            onEditHabit={openEditHabit}
            canCreate={can("calendar", "create")}
          />
        )}
      </div>

      <EventSheet
        open={sheetOpen}
        event={editingEvent}
        defaultDate={newEventDate}
        onClose={handleEventClose}
      />

      <TodoSheet
        open={todoSheetOpen}
        todo={editingTodo}
        onClose={handleTodoClose}
      />

      <HabitSheet
        open={habitSheetOpen}
        habit={editingHabit}
        onClose={handleHabitClose}
      />
    </div>
  );
}
