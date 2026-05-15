"use client";

import { useMemo } from "react";
import Link from "next/link";
import { $api } from "@/lib/api/query";
import { cn } from "@/lib/utils";
import { CalendarDays, Clock, Loader2 } from "lucide-react";
import type { components } from "@/lib/api/schema";

type CalendarEvent = components["schemas"]["CalendarEventResponse"];

// ── Date helpers ──────────────────────────────────────────────────────────────

function toDateStr(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/**
 * The API returns UTC datetimes without a timezone indicator.
 * Without "Z", browsers treat the string as local time — wrong.
 * Appending "Z" ensures correct UTC interpretation.
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

/**
 * Returns the Monday of the week containing `date`.
 * JS Date: Sun=0…Sat=6, so Mon offset = (getDay() + 6) % 7.
 */
function getWeekStart(date: Date): Date {
  const d = new Date(date);
  const offset = (d.getDay() + 6) % 7;
  d.setDate(d.getDate() - offset);
  d.setHours(0, 0, 0, 0);
  return d;
}

/** Short day label: "Mon 12", "Tue 13", etc. */
function dayLabel(date: Date): { short: string; num: number } {
  return {
    short: date.toLocaleDateString(undefined, { weekday: "short" }),
    num: date.getDate(),
  };
}

const SHORT_MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

// ── Sub-components ────────────────────────────────────────────────────────────

function WeekEventChip({ event }: { event: CalendarEvent }) {
  return (
    <div className="rounded px-1.5 py-1 bg-primary/10 text-primary text-[11px] leading-snug truncate">
      {event.all_day ? (
        <span className="font-medium truncate">{event.title}</span>
      ) : (
        <span className="font-medium truncate">
          <span className="opacity-70 mr-1">{formatTime(event.starts_at)}</span>
          {event.title}
        </span>
      )}
    </div>
  );
}

// ── Widget ────────────────────────────────────────────────────────────────────

export function CalendarWeekWidget() {
  const today = new Date();
  const todayStr = toDateStr(today);

  const weekStart = getWeekStart(today);
  const weekEnd = new Date(weekStart);
  weekEnd.setDate(weekStart.getDate() + 6);

  const weekStartStr = toDateStr(weekStart);
  const weekEndStr = toDateStr(weekEnd);

  // Widen the fetch window ±2 days and filter client-side by local date.
  // The API treats bare date strings as UTC midnight; events in UTC-n timezones
  // (e.g. 10 PM EDT = next UTC day) would otherwise be excluded.
  const fetchFrom = new Date(weekStart);
  fetchFrom.setDate(fetchFrom.getDate() - 1);
  const fetchTo = new Date(weekEnd);
  fetchTo.setDate(fetchTo.getDate() + 2);

  const { data, isLoading, isError } = $api.useQuery("get", "/events", {
    params: {
      query: {
        starts_after: toDateStr(fetchFrom),
        starts_before: toDateStr(fetchTo),
        limit: 200,
      },
    },
  });

  // Build an array of 7 day objects (Mon → Sun)
  const days = useMemo(() => {
    return Array.from({ length: 7 }, (_, i) => {
      const d = new Date(weekStart);
      d.setDate(weekStart.getDate() + i);
      return d;
    });
    // weekStart is derived from `today` which is stable within a render
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [weekStartStr]);

  // Group events by date string
  const eventsByDate = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>();
    for (const ev of data?.items ?? []) {
      const key = eventDateStr(ev);
      const list = map.get(key) ?? [];
      list.push(ev);
      map.set(key, list);
    }
    // Sort each day's events: all-day first, then by start time
    for (const [key, list] of map.entries()) {
      map.set(
        key,
        list.sort((a, b) => {
          if (a.all_day && !b.all_day) return -1;
          if (!a.all_day && b.all_day) return 1;
          return a.starts_at.localeCompare(b.starts_at);
        })
      );
    }
    return map;
  }, [data]);

  // Week range label: "May 12 – 18, 2026"
  const rangeLabel = (() => {
    const s = weekStart;
    const e = weekEnd;
    if (s.getMonth() === e.getMonth()) {
      return `${SHORT_MONTHS[s.getMonth()]} ${s.getDate()}–${e.getDate()}, ${e.getFullYear()}`;
    }
    return `${SHORT_MONTHS[s.getMonth()]} ${s.getDate()} – ${SHORT_MONTHS[e.getMonth()]} ${e.getDate()}, ${e.getFullYear()}`;
  })();

  return (
    <div>
      {/* Header */}
      <div className="flex items-baseline justify-between gap-2 mb-3">
        <div className="flex items-baseline gap-2">
          <h2 className="text-sm font-semibold">This week</h2>
          <span className="text-xs text-muted-foreground">{rangeLabel}</span>
        </div>
        <Link
          href="/calendar"
          className="text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <CalendarDays className="h-3.5 w-3.5" />
        </Link>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Loading…
        </div>
      )}

      {isError && (
        <p className="text-sm text-destructive py-2">Failed to load events.</p>
      )}

      {/* 7-column week grid */}
      {!isLoading && !isError && (
        <div className="grid grid-cols-7 gap-1 min-w-0">
          {days.map((day) => {
            const dateStr = toDateStr(day);
            const isToday = dateStr === todayStr;
            const isPast = dateStr < todayStr;
            const label = dayLabel(day);
            const dayEvents = eventsByDate.get(dateStr) ?? [];
            const shown = dayEvents.slice(0, 4);
            const overflow = dayEvents.length - shown.length;

            return (
              <div
                key={dateStr}
                className={cn(
                  "flex flex-col gap-1 rounded-lg p-1.5 min-w-0",
                  isToday && "bg-primary/5 ring-1 ring-primary/20",
                  !isToday && "bg-muted/30",
                )}
              >
                {/* Day header */}
                <div className="flex flex-col items-center gap-0 pb-1 border-b border-border/50">
                  <span
                    className={cn(
                      "text-[10px] font-medium uppercase tracking-wide",
                      isToday ? "text-primary" : isPast ? "text-muted-foreground/50" : "text-muted-foreground"
                    )}
                  >
                    {label.short}
                  </span>
                  <span
                    className={cn(
                      "flex h-5 w-5 items-center justify-center rounded-full text-xs font-semibold",
                      isToday
                        ? "bg-primary text-primary-foreground"
                        : isPast
                        ? "text-muted-foreground/50"
                        : "text-foreground"
                    )}
                  >
                    {label.num}
                  </span>
                </div>

                {/* Events */}
                <div className="flex flex-col gap-0.5 min-w-0">
                  {shown.length === 0 ? (
                    <div className="h-4" /> // spacer so empty days don't collapse
                  ) : (
                    shown.map((ev) => <WeekEventChip key={ev.id} event={ev} />)
                  )}
                  {overflow > 0 && (
                    <span className="text-[10px] text-muted-foreground pl-1">
                      +{overflow} more
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
