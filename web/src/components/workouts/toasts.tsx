"use client";

import { useCallback, useRef, useState } from "react";
import { cn } from "@/lib/utils";

/**
 * A tiny transient-toast primitive local to the workouts builder — the app has
 * no global toast system yet, and workouts-002 only needs a lightweight "blocked
 * with a toast" affordance (e.g. the 6-member superset cap). Not a general
 * solution; if toasts are needed app-wide, promote this to components/ui.
 */
export interface ToastItem {
  id: number;
  message: string;
  tone: "info" | "error";
}

export function useToasts() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const show = useCallback((message: string, tone: ToastItem["tone"] = "info") => {
    const id = nextId.current++;
    setToasts((prev) => [...prev, { id, message, tone }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3000);
  }, []);

  return { toasts, show };
}

export function ToastViewport({ toasts }: { toasts: ToastItem[] }) {
  if (toasts.length === 0) return null;
  return (
    <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 flex flex-col items-center gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          role="status"
          className={cn(
            "rounded-lg px-4 py-2 text-sm shadow-lg border",
            t.tone === "error"
              ? "bg-destructive text-destructive-foreground border-destructive"
              : "bg-foreground text-background border-foreground",
          )}
        >
          {t.message}
        </div>
      ))}
    </div>
  );
}
