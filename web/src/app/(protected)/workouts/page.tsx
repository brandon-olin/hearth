"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { $api } from "@/lib/api/query";
import { useQueryClient } from "@tanstack/react-query";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  Plus, Loader2, Dumbbell, Trash2, ClipboardList, TrendingUp, CheckCircle2,
} from "lucide-react";
import { NewWorkoutSheet } from "@/components/workouts/new-workout-sheet";
import { useToasts, ToastViewport } from "@/components/workouts/toasts";
import type { components } from "@/lib/api/schema";

type SessionSummary = components["schemas"]["WorkoutSessionResponse"];

// ── date helpers ────────────────────────────────────────────────────────────────
// A live workout is stamped with the real wall-clock time it began, because the
// logger's duration counts from it. Grouping therefore converts to LOCAL time
// rather than slicing the UTC string — the same thing the calendar does
// (`sessionDateStr`) — so an evening workout still lands on the day it happened.

function toLocalDateString(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function startedAtToDate(iso: string): string {
  // Timestamps without a zone come back from the API as UTC.
  const normalized = !iso.endsWith("Z") && !/[+-]\d\d:\d\d$/.test(iso) ? `${iso}Z` : iso;
  return toLocalDateString(new Date(normalized));
}

function formatDate(s: string): string {
  const [y, m, d] = s.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  const today = toLocalDateString(new Date());
  const yesterday = toLocalDateString(new Date(Date.now() - 86_400_000));
  if (s === today) return "Today";
  if (s === yesterday) return "Yesterday";
  return date.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
}

export default function WorkoutsPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const { toasts, show } = useToasts();

  const [chooserOpen, setChooserOpen] = useState(false);
  const [starting, setStarting] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing, setClearing] = useState(false);

  const { data, isLoading, isError } = $api.useQuery("get", "/workouts/sessions", {
    params: { query: { limit: 50 } },
  });

  const createSession = $api.useMutation("post", "/workouts/sessions");
  const deleteSession = $api.useMutation("delete", "/workouts/sessions/{session_id}");

  const sessions = data?.items ?? [];

  const grouped = sessions.reduce<Record<string, SessionSummary[]>>((acc, s) => {
    (acc[startedAtToDate(s.started_at)] ??= []).push(s);
    return acc;
  }, {});
  const sortedDates = Object.keys(grouped).sort((a, b) => b.localeCompare(a));

  /**
   * Start a workout and go straight to the live logger. Passing a template_id
   * materializes its exercises and sets server-side, so the logger opens with
   * everything already laid out.
   */
  async function handleStart(templateId: string | null) {
    setStarting(templateId ?? "blank");
    try {
      const session = await createSession.mutateAsync({
        body: {
          ...(templateId ? { template_id: templateId } : {}),
          started_at: new Date().toISOString(),
        },
      });
      qc.invalidateQueries({ queryKey: ["get", "/workouts/sessions"] });
      setChooserOpen(false);
      router.push(`/workouts/sessions/${session.id}`);
    } catch {
      show("Couldn't start that workout.", "error");
    } finally {
      setStarting(null);
    }
  }

  async function handleDeleteAll() {
    // The session API has no bulk-delete; remove each loaded session in turn.
    setClearing(true);
    try {
      await Promise.all(
        sessions.map((s) =>
          deleteSession.mutateAsync({ params: { path: { session_id: s.id } } }),
        ),
      );
      qc.invalidateQueries({ queryKey: ["get", "/workouts/sessions"] });
    } finally {
      setClearing(false);
      setConfirmClear(false);
    }
  }

  return (
    <div className="page-content">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <Dumbbell className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-xl font-semibold">Workouts</h1>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/workouts/progress"
            className={cn(buttonVariants({ size: "sm", variant: "ghost" }), "text-muted-foreground")}
          >
            <TrendingUp className="h-4 w-4 mr-1" /> Progress
          </Link>
          <Link
            href="/workouts/templates"
            className={cn(buttonVariants({ size: "sm", variant: "ghost" }), "text-muted-foreground")}
          >
            <ClipboardList className="h-4 w-4 mr-1" /> Templates
          </Link>
          {sessions.length > 0 && (
            confirmClear ? (
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-muted-foreground">Delete all?</span>
                <Button
                  size="sm" variant="destructive"
                  onClick={handleDeleteAll}
                  disabled={clearing}
                  className="h-7 text-xs px-2"
                >
                  {clearing ? <Loader2 className="h-3 w-3 animate-spin" /> : "Yes, delete all"}
                </Button>
                <Button
                  size="sm" variant="ghost"
                  onClick={() => setConfirmClear(false)}
                  className="h-7 text-xs px-2"
                >
                  Cancel
                </Button>
              </div>
            ) : (
              <Button
                size="sm" variant="ghost"
                onClick={() => setConfirmClear(true)}
                className="h-7 text-xs text-muted-foreground hover:text-destructive px-2"
              >
                <Trash2 className="h-3.5 w-3.5 mr-1" />
                Delete all
              </Button>
            )
          )}
          <Button size="sm" onClick={() => setChooserOpen(true)}>
            <Plus className="h-4 w-4 mr-1" />
            New workout
          </Button>
        </div>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </div>
      )}
      {isError && (
        <p className="py-8 text-sm text-destructive">Failed to load workouts.</p>
      )}

      {!isLoading && !isError && sessions.length === 0 && (
        <div className="py-12 text-center">
          <Dumbbell className="h-8 w-8 text-muted-foreground/30 mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">No workouts logged yet.</p>
          <Button variant="outline" size="sm" className="mt-4" onClick={() => setChooserOpen(true)}>
            <Plus className="h-4 w-4 mr-1" /> Start your first workout
          </Button>
        </div>
      )}

      {sortedDates.length > 0 && (
        <div className="space-y-6">
          {sortedDates.map((date) => (
            <div key={date}>
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
                {formatDate(date)}
              </p>
              <div className="space-y-2">
                {grouped[date].map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => router.push(`/workouts/sessions/${s.id}`)}
                    className={cn(
                      "w-full text-left border rounded-lg px-4 py-3 bg-card",
                      "hover:bg-muted/30 transition-colors flex items-center gap-3",
                    )}
                  >
                    <Dumbbell className="h-4 w-4 text-muted-foreground shrink-0" />
                    <div className="flex-1 min-w-0">
                      <span className="text-sm font-medium block truncate">
                        {s.name ?? "Workout"}
                      </span>
                      <span className="text-xs text-muted-foreground truncate block">
                        {s.exercise_count === 1 ? "1 exercise" : `${s.exercise_count} exercises`}
                      </span>
                    </div>
                    {s.ended_at ? (
                      <CheckCircle2 className="h-4 w-4 text-primary shrink-0" aria-label="Finished" />
                    ) : (
                      <span className="badge badge-progress shrink-0">In progress</span>
                    )}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      <NewWorkoutSheet
        open={chooserOpen}
        onClose={() => setChooserOpen(false)}
        onStart={handleStart}
        starting={starting}
      />
      <ToastViewport toasts={toasts} />
    </div>
  );
}
