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
import { Label } from "@/components/ui/label";
import { Loader2 } from "lucide-react";
import type { components } from "@/lib/api/schema";

type CalendarEvent = components["schemas"]["CalendarEventResponse"];

type FormState = {
  title: string;
  description: string;
  location: string;
  date: string;       // YYYY-MM-DD
  start_time: string; // HH:MM
  end_time: string;   // HH:MM or ""
  all_day: boolean;
};

function blankForm(defaultDate?: string): FormState {
  return {
    title: "",
    description: "",
    location: "",
    date: defaultDate ?? "",
    start_time: "09:00",
    end_time: "10:00",
    all_day: false,
  };
}

function toLocalDateStr(iso: string): string {
  // Parse ISO datetime and return YYYY-MM-DD in local time
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function toLocalTimeStr(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function formFromEvent(event: CalendarEvent): FormState {
  return {
    title: event.title,
    description: event.description ?? "",
    location: event.location ?? "",
    date: toLocalDateStr(event.starts_at),
    start_time: event.all_day ? "00:00" : toLocalTimeStr(event.starts_at),
    end_time: event.ends_at && !event.all_day ? toLocalTimeStr(event.ends_at) : "",
    all_day: event.all_day,
  };
}

function buildIso(date: string, time: string): string {
  // Build an ISO string from a YYYY-MM-DD date and HH:MM time in local time
  const [y, m, d] = date.split("-").map(Number);
  const [h, min] = time.split(":").map(Number);
  const dt = new Date(y, m - 1, d, h, min);
  return dt.toISOString();
}

interface EventSheetProps {
  open: boolean;
  event: CalendarEvent | null;
  /** Pre-fill the date when creating from a day click */
  defaultDate?: string;
  onClose: () => void;
}

export function EventSheet({ open, event, defaultDate, onClose }: EventSheetProps) {
  const qc = useQueryClient();
  const isEdit = event !== null;

  const [form, setForm] = useState<FormState>(blankForm(defaultDate));
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const createMutation = $api.useMutation("post", "/events");
  const updateMutation = $api.useMutation("patch", "/events/{event_id}");
  const deleteMutation = $api.useMutation("delete", "/events/{event_id}");

  useEffect(() => {
    setForm(event ? formFromEvent(event) : blankForm(defaultDate));
    setConfirmDelete(false);
    setError(null);
  }, [event, open, defaultDate]);

  function patch(field: keyof FormState, value: string | boolean) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function handleSave() {
    if (!form.title.trim()) {
      setError("Title is required.");
      return;
    }
    if (!form.date) {
      setError("Date is required.");
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const starts_at = form.all_day
        ? buildIso(form.date, "00:00")
        : buildIso(form.date, form.start_time || "09:00");

      const ends_at =
        !form.all_day && form.end_time
          ? buildIso(form.date, form.end_time)
          : undefined;

      const body = {
        title: form.title.trim(),
        description: form.description.trim() || undefined,
        location: form.location.trim() || undefined,
        starts_at,
        ends_at,
        all_day: form.all_day,
        status: "confirmed" as const,
        transparency: "opaque" as const,
      };

      if (isEdit) {
        await updateMutation.mutateAsync({
          params: { path: { event_id: event.id } },
          body,
        });
      } else {
        await createMutation.mutateAsync({ body });
      }

      await qc.invalidateQueries({ queryKey: ["get", "/events"] });
      onClose();
    } catch {
      setError("Failed to save event. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!isEdit) return;
    setSaving(true);
    try {
      await deleteMutation.mutateAsync({
        params: { path: { event_id: event.id } },
      });
      await qc.invalidateQueries({ queryKey: ["get", "/events"] });
      onClose();
    } catch {
      setError("Failed to delete event.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-md overflow-y-auto">
        <SheetHeader>
          <SheetTitle>{isEdit ? "Edit event" : "New event"}</SheetTitle>
          <SheetDescription>
            {isEdit ? "Update the event details below." : "Fill in the details for your new event."}
          </SheetDescription>
        </SheetHeader>

        <div className="mt-6 space-y-4 px-4 pb-6">
          {/* Title */}
          <div className="space-y-1.5">
            <Label htmlFor="ev-title">Title</Label>
            <Input
              id="ev-title"
              placeholder="Event title"
              value={form.title}
              onChange={(e) => patch("title", e.target.value)}
              autoFocus
            />
          </div>

          {/* Date */}
          <div className="space-y-1.5">
            <Label htmlFor="ev-date">Date</Label>
            <Input
              id="ev-date"
              type="date"
              value={form.date}
              onChange={(e) => patch("date", e.target.value)}
            />
          </div>

          {/* All-day toggle */}
          <div className="flex items-center gap-2">
            <input
              id="ev-allday"
              type="checkbox"
              checked={form.all_day}
              onChange={(e) => patch("all_day", e.target.checked)}
              className="cursor-pointer"
            />
            <Label htmlFor="ev-allday" className="cursor-pointer font-normal">
              All-day event
            </Label>
          </div>

          {/* Time fields — hidden when all_day */}
          {!form.all_day && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="ev-start">Start time</Label>
                <Input
                  id="ev-start"
                  type="time"
                  value={form.start_time}
                  onChange={(e) => patch("start_time", e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="ev-end">End time</Label>
                <Input
                  id="ev-end"
                  type="time"
                  value={form.end_time}
                  onChange={(e) => patch("end_time", e.target.value)}
                />
              </div>
            </div>
          )}

          {/* Location */}
          <div className="space-y-1.5">
            <Label htmlFor="ev-location">Location</Label>
            <Input
              id="ev-location"
              placeholder="Add a location"
              value={form.location}
              onChange={(e) => patch("location", e.target.value)}
            />
          </div>

          {/* Description */}
          <div className="space-y-1.5">
            <Label htmlFor="ev-desc">Description</Label>
            <Textarea
              id="ev-desc"
              placeholder="Add notes or details"
              value={form.description}
              onChange={(e) => patch("description", e.target.value)}
              rows={3}
            />
          </div>

          {/* Error */}
          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}

          {/* Actions */}
          <div className="flex items-center justify-between pt-2">
            {isEdit ? (
              confirmDelete ? (
                <div className="flex items-center gap-2">
                  <span className="text-sm text-muted-foreground">Delete?</span>
                  <Button
                    variant="destructive"
                    size="sm"
                    disabled={saving}
                    onClick={handleDelete}
                  >
                    {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : "Confirm"}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setConfirmDelete(false)}
                  >
                    Cancel
                  </Button>
                </div>
              ) : (
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive hover:text-destructive"
                  onClick={() => setConfirmDelete(true)}
                >
                  Delete
                </Button>
              )
            ) : (
              <span />
            )}

            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={onClose}>
                Cancel
              </Button>
              <Button size="sm" disabled={saving} onClick={handleSave}>
                {saving ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-1" />
                ) : null}
                {isEdit ? "Save changes" : "Create event"}
              </Button>
            </div>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
