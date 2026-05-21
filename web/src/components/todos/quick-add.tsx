"use client";

import { Plus } from "lucide-react";
import { cn } from "@/lib/utils";

interface QuickAddProps {
  /** Called when the button is clicked — should open the new-task sheet. */
  onOpen: () => void;
  className?: string;
}

/**
 * A simple "Add a task" button that opens the task creation sheet.
 * Replaces the old inline text-entry approach so users get the full
 * creation panel (due date, assignee, priority, etc.) from the start.
 */
export function QuickAdd({ onOpen, className }: QuickAddProps) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        "flex items-center gap-2 w-full px-3 py-2.5 rounded-md border border-dashed",
        "border-border/50 text-muted-foreground/60 text-sm",
        "hover:border-border/80 hover:text-muted-foreground hover:bg-muted/30",
        "transition-colors",
        className
      )}
    >
      <Plus className="h-4 w-4 shrink-0" />
      Add a task…
    </button>
  );
}
