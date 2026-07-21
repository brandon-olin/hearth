"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { Timer, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  adjustRestTimer,
  dismissRestTimer,
  formatClock,
  getRestTimer,
  secondsRemaining,
  subscribeRestTimer,
  type RestTimer,
} from "@/lib/workouts/rest-timer";

/**
 * Subscribe to the module-level rest timer and re-render once a second while it
 * runs. The ticking interval lives here rather than in the store so nothing
 * keeps firing when no bar is mounted — the store holds an absolute end time,
 * so a remount after navigating away picks the countdown back up mid-flight.
 */
function useRestTimer(): { timer: RestTimer | null; remaining: number } {
  const timer = useSyncExternalStore(subscribeRestTimer, getRestTimer, () => null);
  const [, tick] = useState(0);

  useEffect(() => {
    if (!timer) return;
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [timer]);

  return { timer, remaining: timer ? secondsRemaining(timer) : 0 };
}

export function RestTimerBar({ sessionId }: { sessionId: string }) {
  const { timer, remaining } = useRestTimer();

  if (!timer || timer.sessionId !== sessionId) return null;

  const done = remaining === 0;
  const elapsed = timer.durationSeconds - remaining;
  const pct = Math.min(100, Math.round((elapsed / timer.durationSeconds) * 100));

  return (
    <div className="fixed bottom-0 left-0 right-0 z-40 border-t bg-background">
      <div
        className={cn("h-0.5 transition-all duration-1000", done ? "bg-primary" : "bg-primary/60")}
        style={{ width: `${pct}%` }}
      />
      <div className="px-4 py-2.5 flex items-center gap-3 max-w-3xl mx-auto">
        <Timer className={cn("h-4 w-4 shrink-0", done ? "text-primary" : "text-muted-foreground")} />
        <div className="min-w-0 flex-1">
          <span
            className={cn(
              "text-sm font-medium tabular-nums",
              done ? "text-primary" : "text-foreground",
            )}
          >
            {done ? "Rest over" : formatClock(remaining)}
          </span>
          <span className="text-xs text-muted-foreground truncate block">
            Resting after {timer.label}
          </span>
        </div>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 text-xs px-2"
          onClick={() => adjustRestTimer(-15)}
          disabled={done}
        >
          −15s
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 text-xs px-2"
          onClick={() => adjustRestTimer(15)}
        >
          +15s
        </Button>
        <button
          type="button"
          onClick={dismissRestTimer}
          aria-label="Dismiss rest timer"
          className="text-muted-foreground hover:text-foreground transition-colors p-1 shrink-0"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
