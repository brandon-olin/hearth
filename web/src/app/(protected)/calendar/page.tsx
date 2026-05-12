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
import type { components } from "@/lib/api/schema";

type CalendarEvent = components["schemas"]["CalendarEventResponse"];

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

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// ── Event display helpers ─────────────────────────────────────────────────────

function formatTime(iso: string): string {
  const d = new Date(iso);
  const h = d.getHours();
  const m = d.getMinutes();
  const ampm = h >= 12 ? "pm" : "am";
  const hh = h % 12 || 12;
  return m === 0 ? `${hh}${ampm}` : `${hh}:${String(m).padStart(2, "0")}${ampm}`;
}

function eventDateStr(ev: CalendarEvent): string {
  return toDateStr(new Date(ev.starts_at));
}

// ── Event list item ───────────────────────────────────────────────────────────

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

// ── Day cell ──────────────────────────────────────────────────────────────────

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

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CalendarPage() {
  const today = new Date();
  const todayStr = toDateStr(today);

  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth());
  const [selectedDate, setSelectedDate] = useState(todayStr);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editingEvent, setEditingEvent] = useState<CalendarEvent | null>(null);
  const [newEventDate, setNewEventDate] = useState<string | undefined>(undefined);

  // Fetch a padded window so grid overflow days are covered
  const fetchFrom = toDateStr(new Date(year, month, -6));
  const fetchTo = toDateStr(new Date(year, month + 1, 7));

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

  const grid = useMemo(() => buildGrid(year, month), [year, month]);

  const selectedEvents = useMemo(() =>
    (eventsByDate.get(selectedDate) ?? []).sort((a, b) => {
      if (a.all_day && !b.all_day) return -1;
      if (!a.all_day && b.all_day) return 1;
      return a.starts_at.localeCompare(b.starts_at);
    }),
    [eventsByDate, selectedDate]
  );

  const upcomingEvents = useMemo(() => {
    const cutoffDate = new Date(today);
    cutoffDate.setDate(today.getDate() + 30);
    const cutoff = toDateStr(cutoffDate);
    return events
      .filter((ev) => { const d = eventDateStr(ev); return d >= todayStr && d <= cutoff; })
      .sort((a, b) => a.starts_at.localeCompare(b.starts_at))
      .slice(0, 10);
  }, [events, todayStr]);

  function prevMonth() {
    if (month === 0) { setYear((y) => y - 1); setMonth(11); }
    else setMonth((m) => m - 1);
  }
  function nextMonth() {
    if (month === 11) { setYear((y) => y + 1); setMonth(0); }
    else setMonth((m) => m + 1);
  }
  function goToday() {
    setYear(today.getFullYear());
    setMonth(today.getMonth());
    setSelectedDate(todayStr);
  }

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

  const selectedDateLabel = new Date(selectedDate + "T00:00:00").toLocaleDateString(undefined, {
    weekday: "long", month: "long", day: "numeric",
  });

  return (
    <div className="flex flex-col h-full">
      {/* Top bar */}
      <div className="flex items-center justify-between px-6 py-4 border-b shrink-0">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold">
            {MONTH_NAMES[month]} {year}
          </h1>
          <div className="flex items-center gap-0.5">
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={prevMonth}>
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={nextMonth}>
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
          {(year !== today.getFullYear() || month !== today.getMonth()) && (
            <Button variant="outline" size="sm" className="h-7 text-xs" onClick={goToday}>
              Today
            </Button>
          )}
        </div>
        <Button size="sm" onClick={() => openCreate()}>
          <Plus className="h-4 w-4 mr-1" />
          New event
        </Button>
      </div>

      {/* Body: grid + right sidebar */}
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
                  onClick={() => setSelectedDate(dateStr)}
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
          {/* Selected day header */}
          <div className="flex items-center justify-between px-4 py-3 border-b shrink-0">
            <p className="text-sm font-medium">{selectedDateLabel}</p>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => openCreate(selectedDate)}
            >
              <Plus className="h-3.5 w-3.5" />
            </Button>
          </div>

          {/* Events for selected day */}
          <div className="flex-1 overflow-y-auto px-2 py-2 min-h-0">
            {selectedEvents.length === 0 ? (
              <div className="py-8 text-center">
                <p className="text-xs text-muted-foreground">No events</p>
                <Button
                  variant="ghost"
                  size="sm"
                  className="mt-2 h-7 text-xs"
                  onClick={() => openCreate(selectedDate)}
                >
                  <Plus className="h-3 w-3 mr-1" />
                  Add event
                </Button>
              </div>
            ) : (
              <div className="space-y-0.5">
                {selectedEvents.map((ev) => (
                  <EventListItem key={ev.id} event={ev} onClick={() => openEdit(ev)} />
                ))}
              </div>
            )}
          </div>

          {/* Upcoming section */}
          {upcomingEvents.length > 0 && (
            <>
              <div className="border-t px-4 pt-3 pb-1 shrink-0">
                <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Upcoming
                </p>
              </div>
              <div className="overflow-y-auto px-2 pb-2" style={{ maxHeight: 240 }}>
                {upcomingEvents.map((ev) => (
                  <EventListItem key={ev.id} event={ev} onClick={() => openEdit(ev)} />
                ))}
              </div>
            </>
          )}
        </div>
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
