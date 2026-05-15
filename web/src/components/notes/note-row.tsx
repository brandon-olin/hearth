"use client";

import { cn, relativeTime } from "@/lib/utils";
import type { components } from "@/lib/api/schema";

type NoteSummary = components["schemas"]["NoteSummary"];

interface NoteRowProps {
  note: NoteSummary;
  selected: boolean;
  onSelect: (note: NoteSummary) => void;
}

export function NoteRow({ note, selected, onSelect }: NoteRowProps) {
  // Extract a short preview from content_md
  const preview = note.content_md
    ? note.content_md
        .replace(/^#+\s+/gm, "")   // strip headings
        .replace(/\[\[([^\]]+)\]\]/g, "$1") // unwrap wikilinks
        .replace(/[*_`~]/g, "")     // strip inline markers
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 80)
    : null;

  return (
    <button
      type="button"
      onClick={() => onSelect(note)}
      className={cn(
        "w-full text-left px-3 py-2.5 rounded-md transition-colors group",
        selected
          ? "bg-primary/10 text-foreground"
          : "hover:bg-muted/60 text-foreground"
      )}
    >
      <div className="flex items-baseline justify-between gap-2 mb-0.5">
        <span className={cn("text-sm font-medium truncate flex-1", !note.title && "italic text-muted-foreground")}>
          {note.title || "Untitled"}
        </span>
        <span className="text-[11px] text-muted-foreground shrink-0">
          {relativeTime(note.updated_at)}
        </span>
      </div>
      {preview && (
        <p className="text-xs text-muted-foreground truncate leading-relaxed">{preview}</p>
      )}
    </button>
  );
}
