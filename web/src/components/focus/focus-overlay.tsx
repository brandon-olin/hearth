"use client";

import { useEffect, useRef, useState } from "react";
import { Minimize2 } from "lucide-react";
import { useFocusMode, FOCUS_PHRASES } from "@/lib/focus/context";
import { cn } from "@/lib/utils";

/** Picks a random phrase different from the last one shown. */
let lastPhraseIdx = -1;
function pickPhrase(): string {
  let idx: number;
  do { idx = Math.floor(Math.random() * FOCUS_PHRASES.length); }
  while (idx === lastPhraseIdx && FOCUS_PHRASES.length > 1);
  lastPhraseIdx = idx;
  return FOCUS_PHRASES[idx];
}

export function FocusOverlay() {
  const { focused, exit } = useFocusMode();
  const [toastVisible, setToastVisible] = useState(false);
  const [phrase, setPhrase] = useState("");
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    if (focused) {
      setPhrase(pickPhrase());
      setToastVisible(true);
      timerRef.current = setTimeout(() => setToastVisible(false), 2800);
    } else {
      setToastVisible(false);
      if (timerRef.current) clearTimeout(timerRef.current);
    }
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [focused]);

  if (!focused) return null;

  return (
    <>
      {/* Bottom-centre toast */}
      <div
        className={cn(
          "fixed bottom-8 left-1/2 -translate-x-1/2 z-50",
          "px-4 py-2 rounded-full bg-foreground/90 text-background text-xs font-medium shadow-lg",
          "pointer-events-none select-none",
          "transition-all duration-500",
          toastVisible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-2",
        )}
      >
        {phrase}
      </div>

      {/* Bottom-right exit button — appears after toast fades */}
      <button
        onClick={exit}
        title="Exit focus mode (⌘⇧F)"
        className={cn(
          "fixed bottom-6 right-6 z-50",
          "flex items-center gap-1.5 px-3 py-1.5 rounded-full",
          "bg-background/80 backdrop-blur-sm border border-border/60 shadow-sm",
          "text-xs text-muted-foreground hover:text-foreground transition-all duration-200",
          "opacity-0 hover:opacity-100 focus:opacity-100",
          // Always slightly visible so user can find it
          "after:absolute after:inset-0 after:rounded-full",
          "[&:not(:hover)]:opacity-20",
        )}
      >
        <Minimize2 className="h-3 w-3" />
        Exit focus
      </button>
    </>
  );
}
