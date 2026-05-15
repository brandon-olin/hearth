"use client";

import { useState, useMemo } from "react";
import { $api } from "@/lib/api/query";
import { Button } from "@/components/ui/button";
import { EventSheet } from "@/components/calendar/event-sheet";
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

// ── Month view ────────────────────────────────────────────────────────────────

function DayCell({
  day,
  isCurrentMonth,
  isToday,
  isSelected,
  events,
  onClick,
}: {
  day: Date;
  isCurrentMonth: boolean;
  isToday: boolean;
  isSelected: boolean;
  events: CalendarEvent[];
  onClick: () => void;
}) {
  const shown = events.slice(0, 3);
  const overflow = events.length - 3;

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
        {shown.map((ev) => (
          <div
            key={ev.id}
            className="truncate rounded px-1 py-0.5 text-[10px] font-medium bg-primary/15 text-primary leading-tight"
          >
            {ev.all_day ? ev.title : `${formatTime(ev.starts_at)} ${ev.title}`}
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
  isLoading,
  onSelectDate,
  onEditEvent,
  onCreateEvent,
  canCreate,
}: {
  year: number;
  month: number;
  todayStr: string;
  selectedDate: string;
  eventsByDate: Map<string, CalendarEvent[]>;
  isLoading: boolean;
  onSelectDate: (d: string) => void;
  onEditEvent: (ev: CalendarEvent) => void;
  onCreateEvent: (date?: string) => void;
  canCreate: boolean;
}) {
  const grid = useMemo(() => buildGrid(year, month), [year, month]);
  const selectedEvents = useMemo(
    () => sortEvents(eventsByDate.get(selectedDate) ?? []),
    [eventsByDate, selectedDate]
  );

  const selectedDateLabel = new Date(selectedDate + "T00:00:00").toLocaleDateString(undefined, {
    weekday: "long", month: "long", day: "numeric",
  });

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
          {selectedEvents.length === 0 ? (
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
  isLoading,
  onEditEvent,
  onCreateEvent,
  canCreate,
}: {
  weekStart: Date;
  todayStr: string;
  eventsByDate: Map<string, CalendarEvent[]>;
  isLoading: boolean;
  onEditEvent: (ev: CalendarEvent) => void;
  onCreateEvent: (date?: string) => void;
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

              {/* Events */}
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
  isLoading,
  onEditEvent,
  onCreateEvent,
  canCreate,
}: {
  selectedDate: string;
  todayStr: string;
  eventsByDate: Map<string, CalendarEvent[]>;
  isLoading: boolean;
  onEditEvent: (ev: CalendarEvent) => void;
  onCreateEvent: (date?: string) => void;
  canCreate: boolean;
}) {
  const dayEvents = useMemo(
    () => sortEvents(eventsByDate.get(selectedDate) ?? []),
    [eventsByDate, selectedDate]
  );

  return (
    <div className="flex-1 overflow-auto p-6 max-w-2xl mx-auto w-full">
      {isLoading && (
        <p className="text-center text-xs text-muted-foreground mb-4">Loading…</p>
      )}

      {dayEvents.length === 0 ? (
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

              {/* Colour strip */}
              <div className="w-1 self-stretch rounded-full bg-primary shrink-0" />

              {/* Content */}
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

  // Compute the current week start based on selectedDate (for week/day nav)
  const weekStart = useMemo(() => getWeekStart(new Date(selectedDate + "T00:00:00")), [selectedDate]);
  const weekEnd = useMemo(() => {
    const d = new Date(weekStart);
    d.setDate(d.getDate() + 6);
    return d;
  }, [weekStart]);

  // Fetch window: padded for the current view.
  // The API stores datetimes as UTC but returns them without a timezone indicator,
  // so a bare date string like "2026-05-14" is parsed as UTC midnight by FastAPI.
  // An event at 10 PM UTC (= 6 PM EDT) would fail `starts_before = "2026-05-14"`
  // because 22:00 UTC > 00:00 UTC. We widen the window by ±1–2 days and rely on
  // client-side date bucketing (eventDateStr → normalizeIso → local date) instead.
  const fetchFrom = useMemo(() => {
    if (view === "month") return toDateStr(new Date(year, month, -6));
    if (view === "week") {
      // 1 day before week start covers UTC+n timezones where local Monday is UTC Sunday
      const d = new Date(weekStart);
      d.setDate(d.getDate() - 1);
      return toDateStr(d);
    }
    // Day view: 1 day before catches events stored on the prior UTC day that are local-today
    const d = new Date(selectedDate + "T00:00:00");
    d.setDate(d.getDate() - 1);
    return toDateStr(d);
  }, [view, year, month, weekStart, selectedDate]);

  const fetchTo = useMemo(() => {
    if (view === "month") return toDateStr(new Date(year, month + 1, 7));
    if (view === "week") {
      // 2 days after week end covers UTC-n timezones (e.g. EDT) where 10 PM Sunday = next UTC day
      const d = new Date(weekEnd);
      d.setDate(d.getDate() + 2);
      return toDateStr(d);
    }
    // Day view: 2 days ahead — e.g. 10 PM EDT is stored as the next UTC day,
    // and midnight EDT is stored 4 hours into the next UTC day.
    const d = new Date(selectedDate + "T00:00:00");
    d.setDate(d.getDate() + 2);
    return toDateStr(d);
  }, [view, year, month, weekEnd, selectedDate]);

  const { data, isLoading } = $api.useQuery("get", "/events", {
    params: { query: { starts_after: fetchFrom, starts_before: fetchTo, limit: 200 } },
  });

  const events = data?.items ?? [];

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
  function openEdit(ev: CalendarEvent) {
    setEditingEvent(ev);
    setNewEventDate(undefined);
    setSheetOpen(true);
  }
  function handleClose() {
    setSheetOpen(false);
    setTimeout(() => { setEditingEvent(null); setNewEventDate(undefined); }, 300);
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
    // day view
    return new Date(selectedDate + "T00:00:00").toLocaleDateString(undefined, {
      weekday: "long", month: "long", day: "numeric", year: "numeric",
    });
  }, [view, month, year, weekStart, weekEnd, selectedDate]);

  // When switching to week view while on month view, sync selectedDate into the visible month.
  function handleViewChange(v: ViewMode) {
    if (v === "week" || v === "day") {
      // If the selectedDate is not in the current month view, reset to today
      const sel = new Date(selectedDate + "T00:00:00");
      if (view === "month" && (sel.getFullYear() !== year || sel.getMonth() !== month)) {
        setSelectedDate(todayStr);
      }
    }
    if (v === "month") {
      // Sync the month/year to the currently selected date
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
            isLoading={isLoading}
            onSelectDate={(d) => {
              setSelectedDate(d);
              // Clicking a date in the overflow area navigates the month
              const clicked = new Date(d + "T00:00:00");
              if (clicked.getMonth() !== month) {
                setYear(clicked.getFullYear());
                setMonth(clicked.getMonth());
              }
            }}
            onEditEvent={openEdit}
            onCreateEvent={openCreate}
            canCreate={can("calendar", "create")}
          />
        )}

        {view === "week" && (
          <WeekView
            weekStart={weekStart}
            todayStr={todayStr}
            eventsByDate={eventsByDate}
            isLoading={isLoading}
            onEditEvent={openEdit}
            onCreateEvent={openCreate}
            canCreate={can("calendar", "create")}
          />
        )}

        {view === "day" && (
          <DayView
            selectedDate={selectedDate}
            todayStr={todayStr}
            eventsByDate={eventsByDate}
            isLoading={isLoading}
            onEditEvent={openEdit}
            onCreateEvent={openCreate}
            canCreate={can("calendar", "create")}
          />
        )}
      </div>

      <EventSheet
        open={sheetOpen}
        event={editingEvent}
        defaultDate={newEventDate}
        onClose={handleClose}
      />
    </div>
  );
}
