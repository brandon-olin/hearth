"use client";

import { useMemo } from "react";
import Link from "next/link";
import { $api } from "@/lib/api/query";
import { cn } from "@/lib/utils";
import { CalendarDays, Clock, MapPin, Loader2 } from "lucide-react";
import type { components } from "@/lib/api/schema";

type CalendarEvent = components["schemas"]["CalendarEventResponse"];

// ── Date / time helpers ───────────────────────────────────────────────────────

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

// ── Sub-components ────────────────────────────────────────────────────────────

function EventRow({ event }: { event: CalendarEvent }) {
  return (
    <div className="flex items-start gap-2.5 px-1 py-2 rounded-md hover:bg-muted/50 transition-colors group">
      <div className="mt-1.5 h-2 w-2 rounded-full bg-primary shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium truncate leading-snug">{event.title}</p>
        <div className="flex items-center gap-2 mt-0.5 text-xs text-muted-foreground flex-wrap">
          {event.all_day ? (
            <span>All day</span>
          ) : (
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3 shrink-0" />
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
  );
}

// ── Widget ────────────────────────────────────────────────────────────────────

export function CalendarTodayWidget() {
  const today = new Date();
  const todayStr = toDateStr(today);

  // Fetch ±1 day and filter client-side by local date.
  // The API compares bare date strings as UTC midnight, so a 10 PM EDT event
  // (= next UTC day) would be excluded with starts_before = today only.
  const tomorrow = new Date(today);
  tomorrow.setDate(tomorrow.getDate() + 1);
  const tomorrowStr = toDateStr(tomorrow);

  const { data, isLoading, isError } = $api.useQuery("get", "/events", {
    params: {
      query: { starts_after: todayStr, starts_before: tomorrowStr, limit: 50 },
    },
  });

  const events = useMemo(() => {
    const all = data?.items ?? [];
    return all
      .filter((ev) => eventDateStr(ev) === todayStr)
      .sort((a, b) => {
        if (a.all_day && !b.all_day) return -1;
        if (!a.all_day && b.all_day) return 1;
        return a.starts_at.localeCompare(b.starts_at);
      });
  }, [data, todayStr]);

  const todayLabel = today.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });

  return (
    <div>
      {/* Header */}
      <div className="flex items-baseline justify-between gap-2 mb-3">
        <div className="flex items-baseline gap-2">
          <h2 className="text-sm font-semibold">Today</h2>
          <span className="text-xs text-muted-foreground">{todayLabel}</span>
        </div>
        <Link
          href="/calendar"
          className="text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <CalendarDays className="h-3.5 w-3.5" />
        </Link>
      </div>

      {/* Body */}
      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Loading…
        </div>
      )}

      {isError && (
        <p className="text-sm text-destructive py-2">Failed to load events.</p>
      )}

      {!isLoading && !isError && events.length === 0 && (
        <p className="text-sm text-muted-foreground py-2">No events today.</p>
      )}

      {events.length > 0 && (
        <div className="space-y-0">
          {events.map((ev) => (
            <EventRow key={ev.id} event={ev} />
          ))}
        </div>
      )}
    </div>
  );
}
