"use client";

import { Maximize2, Minimize2 } from "lucide-react";
import { useFocusMode } from "@/lib/focus/context";
import { cn } from "@/lib/utils";

export function FocusToggle({ className }: { className?: string }) {
  const { focused, toggle } = useFocusMode();

  return (
    <button
      type="button"
      onClick={toggle}
      title={focused ? "Exit focus mode (⌘⇧F)" : "Enter focus mode (⌘⇧F)"}
      className={cn(
        "flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium transition-colors",
        focused
          ? "text-primary bg-primary/10 hover:bg-primary/20"
          : "text-muted-foreground hover:text-foreground hover:bg-muted/50",
        className,
      )}
    >
      {focused ? (
        <Minimize2 className="h-3.5 w-3.5" />
      ) : (
        <Maximize2 className="h-3.5 w-3.5" />
      )}
      {focused ? "Exit focus" : "Focus"}
    </button>
  );
}
