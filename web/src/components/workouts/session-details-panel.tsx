"use client";

import { useEffect, useRef, useState } from "react";
import { AlertCircle, Check, ChevronDown, ChevronUp, Loader2, Trash2 } from "lucide-react";
import { $api } from "@/lib/api/query";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { components } from "@/lib/api/schema";

type SessionDetail = components["schemas"]["WorkoutSessionDetailResponse"];

const SAVE_DELAY = 700; // ms
type SaveStatus = "idle" | "saving" | "saved" | "error";

function SaveBadge({ status }: { status: SaveStatus }) {
  if (status === "idle") return null;
  if (status === "saving") {
    return (
      <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
        <Loader2 className="h-2.5 w-2.5 animate-spin" /> Saving
      </span>
    );
  }
  if (status === "saved") {
    return (
      <span className="flex items-center gap-1 text-[10px] text-primary">
        <Check className="h-2.5 w-2.5" /> Saved
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-[10px] text-destructive">
      <AlertCircle className="h-2.5 w-2.5" /> Error
    </span>
  );
}

/** Keep the time-of-day when only the date is edited — duration depends on it. */
function toDateInput(iso: string): string {
  const normalized = !iso.endsWith("Z") && !/[+-]\d\d:\d\d$/.test(iso) ? `${iso}Z` : iso;
  const d = new Date(normalized);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function withDate(iso: string, dateStr: string): string {
  const normalized = !iso.endsWith("Z") && !/[+-]\d\d:\d\d$/.test(iso) ? `${iso}Z` : iso;
  const original = new Date(normalized);
  const [y, m, d] = dateStr.split("-").map(Number);
  const next = new Date(original);
  next.setFullYear(y, m - 1, d);
  return next.toISOString();
}

/**
 * The workout's own metadata — name, date, notes, and deletion — collapsed under
 * the exercise list so it never competes with logging. This is the same editing
 * surface the pre-workouts-003 sheet offered; keeping it here means there is one
 * place a session is edited rather than two.
 */
export function SessionDetailsPanel({
  session,
  onDeleted,
  onError,
}: {
  session: SessionDetail;
  onDeleted: () => void;
  onError: (message: string) => void;
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(session.name ?? "");
  const [date, setDate] = useState(() => toDateInput(session.started_at));
  const [notes, setNotes] = useState(session.notes ?? "");
  const [status, setStatus] = useState<SaveStatus>("idle");
  const [confirmDelete, setConfirmDelete] = useState(false);

  const patchSession = $api.useMutation("patch", "/workouts/sessions/{session_id}");
  const deleteSession = $api.useMutation("delete", "/workouts/sessions/{session_id}");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  function schedule(next: { name: string; date: string; notes: string }) {
    if (timer.current) clearTimeout(timer.current);
    if (!next.date) return;
    timer.current = setTimeout(async () => {
      setStatus("saving");
      try {
        await patchSession.mutateAsync({
          params: { path: { session_id: session.id } },
          body: {
            name: next.name.trim() || null,
            notes: next.notes.trim() || null,
            started_at: withDate(session.started_at, next.date),
          },
        });
        setStatus("saved");
        qc.invalidateQueries({ queryKey: ["get", "/workouts/sessions"] });
        setTimeout(() => setStatus("idle"), 2000);
      } catch {
        setStatus("error");
      }
    }, SAVE_DELAY);
  }

  async function handleDelete() {
    try {
      await deleteSession.mutateAsync({ params: { path: { session_id: session.id } } });
      qc.invalidateQueries({ queryKey: ["get", "/workouts/sessions"] });
      onDeleted();
    } catch {
      onError("Couldn't delete this workout.");
    }
  }

  return (
    <div className="mt-8 border-t pt-4">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        Workout details
        <SaveBadge status={status} />
      </button>

      {open && (
        <div className="mt-3 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="session-name" className="text-xs">Name</Label>
              <Input
                id="session-name"
                value={name}
                placeholder="Leg day"
                onChange={(e) => {
                  setName(e.target.value);
                  schedule({ name: e.target.value, date, notes });
                }}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="session-date" className="text-xs">Date</Label>
              <Input
                id="session-date"
                type="date"
                value={date}
                onChange={(e) => {
                  setDate(e.target.value);
                  schedule({ name, date: e.target.value, notes });
                }}
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="session-notes" className="text-xs">Session notes</Label>
            <Textarea
              id="session-notes"
              rows={2}
              value={notes}
              placeholder="How it felt, PRs, anything notable…"
              onChange={(e) => {
                setNotes(e.target.value);
                schedule({ name, date, notes: e.target.value });
              }}
            />
          </div>

          {confirmDelete ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Delete this workout?</span>
              <Button
                size="sm" variant="destructive" className="h-7 text-xs"
                onClick={handleDelete}
                disabled={deleteSession.isPending}
              >
                {deleteSession.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : "Yes, delete"}
              </Button>
              <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setConfirmDelete(false)}>
                Cancel
              </Button>
            </div>
          ) : (
            <Button
              size="sm" variant="ghost"
              className="h-7 text-xs text-muted-foreground hover:text-destructive"
              onClick={() => setConfirmDelete(true)}
            >
              <Trash2 className="h-3.5 w-3.5 mr-1" /> Delete workout
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
