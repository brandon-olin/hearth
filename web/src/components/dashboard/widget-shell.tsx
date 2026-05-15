"use client";

import { useRef } from "react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { WidgetInstance } from "@/lib/dashboard/types";

// ── Static Tailwind class lookups ─────────────────────────────────────────────
// Written out explicitly so Tailwind's JIT scanner includes them at build time.

const COL_SPAN_CLASS: Record<number, string> = {
  1: "col-span-1",
  2: "col-span-2",
  3: "col-span-3",
  4: "col-span-4",
};

const COL_START_CLASS: Record<number, string> = {
  1: "col-start-1",
  2: "col-start-2",
  3: "col-start-3",
  4: "col-start-4",
};

// ── Shared pill handle style ──────────────────────────────────────────────────
// Both the left (shift) and right (resize) handles use the same visual style
// so they look symmetric. Only their position and cursor differ.

const PILL_BASE =
  "absolute top-1/2 -translate-y-1/2 h-8 w-1.5 rounded-full z-20 " +
  "bg-primary/40 hover:bg-primary/80 opacity-50 hover:opacity-100 " +
  "transition-all cursor-ew-resize select-none";

// ── Left handle — shifts colStart (moves widget across columns) ───────────────

interface ShiftHandleProps {
  widgetRef: React.RefObject<HTMLDivElement | null>;
  colSpan: number;
  colStart: number; // effective colStart (already defaulted to 1)
  gridCols: number;
  onColStartChange: (start: number | null) => void;
}

function ShiftHandle({ widgetRef, colSpan, colStart, gridCols, onColStartChange }: ShiftHandleProps) {
  const isDraggingRef = useRef(false);

  function handleMouseDown(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    if (!widgetRef.current) return;

    isDraggingRef.current = true;

    const startX      = e.clientX;
    const initialStart = colStart;
    // Column width derived from the rendered widget width and its current span
    const columnWidth  = widgetRef.current.offsetWidth / colSpan;
    const maxStart     = gridCols - colSpan + 1;

    function handleMouseMove(e: MouseEvent) {
      if (!isDraggingRef.current) return;
      const deltaX   = e.clientX - startX;
      const deltaCols = Math.round(deltaX / columnWidth);
      const newStart  = Math.max(1, Math.min(maxStart, initialStart + deltaCols));
      // colStart=1 is the natural default — store as null to keep serialisation clean
      onColStartChange(newStart === 1 ? null : newStart);
    }

    function handleMouseUp() {
      isDraggingRef.current = false;
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
    document.body.style.cursor = "ew-resize";
    document.body.style.userSelect = "none";
  }

  return (
    <div
      onMouseDown={handleMouseDown}
      className={cn(PILL_BASE, "left-1.5")}
      aria-label="Drag to shift position"
      title="Drag left/right to shift column position"
    />
  );
}

// ── Right handle — changes colSpan (resizes widget width) ─────────────────────

interface ResizeHandleProps {
  widgetRef: React.RefObject<HTMLDivElement | null>;
  colSpan: number;
  maxColSpan: number;
  onColSpanChange: (span: number) => void;
}

function ResizeHandle({ widgetRef, colSpan, maxColSpan, onColSpanChange }: ResizeHandleProps) {
  const isDraggingRef = useRef(false);

  function handleMouseDown(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    if (!widgetRef.current) return;

    isDraggingRef.current = true;

    const startX      = e.clientX;
    const initialWidth = widgetRef.current.offsetWidth;
    const columnWidth  = initialWidth / colSpan;

    function handleMouseMove(e: MouseEvent) {
      if (!isDraggingRef.current) return;
      const deltaX  = e.clientX - startX;
      const newSpan = Math.max(1, Math.min(maxColSpan, Math.round((initialWidth + deltaX) / columnWidth)));
      onColSpanChange(newSpan);
    }

    function handleMouseUp() {
      isDraggingRef.current = false;
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
    document.body.style.cursor = "ew-resize";
    document.body.style.userSelect = "none";
  }

  return (
    <div
      onMouseDown={handleMouseDown}
      className={cn(PILL_BASE, "right-1.5")}
      aria-label="Drag to resize"
      title="Drag to resize width"
    />
  );
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface WidgetShellProps {
  widget: WidgetInstance;
  isEditMode: boolean;
  gridCols: number;
  /** Max colSpan this widget can grow to (total cols minus siblings' spans) */
  maxColSpan: number;
  /** When set, renders a vertical drop-indicator line on this side of the widget */
  dropIndicatorSide?: "left" | "right" | null;
  onRemove: (id: string) => void;
  onColSpanChange: (id: string, span: number) => void;
  onColStartChange: (id: string, start: number | null) => void;
  children: React.ReactNode;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function WidgetShell({
  widget,
  isEditMode,
  gridCols,
  maxColSpan,
  dropIndicatorSide,
  onRemove,
  onColSpanChange,
  onColStartChange,
  children,
}: WidgetShellProps) {
  const widgetRef = useRef<HTMLDivElement>(null);

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: widget.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  const colSpan      = Math.min(widget.colSpan ?? 1, gridCols);
  const effectiveStart = widget.colStart != null
    ? Math.min(widget.colStart, gridCols - colSpan + 1)
    : null;

  // Merge dnd-kit's ref with our own ref for resize/shift calculations
  function setRefs(el: HTMLDivElement | null) {
    (widgetRef as React.MutableRefObject<HTMLDivElement | null>).current = el;
    setNodeRef(el);
  }

  return (
    <div
      ref={setRefs}
      style={style}
      {...attributes}
      className={cn(
        "relative rounded-lg border bg-card p-4 transition-shadow min-w-0",
        isDragging && "shadow-lg opacity-50 z-50",
        isEditMode && "ring-2 ring-primary/25",
        COL_SPAN_CLASS[colSpan] ?? "col-span-1",
        effectiveStart != null && COL_START_CLASS[effectiveStart],
      )}
    >
      {/* ── Within-row drop indicator lines ─────────────────────────────── */}
      {/* These bleed into the gap between widgets (gap-4 = 16px, half = 8px = translate-x-2) */}
      {dropIndicatorSide === "left" && (
        <div className="absolute -left-2 top-3 bottom-3 w-0.5 bg-primary rounded-full z-30 pointer-events-none" />
      )}
      {dropIndicatorSide === "right" && (
        <div className="absolute -right-2 top-3 bottom-3 w-0.5 bg-primary rounded-full z-30 pointer-events-none" />
      )}

      {/* ── Edit mode controls (top-right) ──────────────────────────────── */}
      {isEditMode && (
        <div className="absolute top-2 right-2 flex items-center gap-1 z-10">
          {/* Drag handle */}
          <button
            {...listeners}
            type="button"
            className="p-1 rounded text-muted-foreground/50 hover:text-muted-foreground hover:bg-muted transition-colors cursor-grab active:cursor-grabbing"
            aria-label="Drag to reorder"
          >
            <GripVertical className="h-4 w-4" />
          </button>
          {/* Remove */}
          <button
            type="button"
            onClick={() => onRemove(widget.id)}
            className="p-1 rounded text-muted-foreground/50 hover:text-destructive hover:bg-destructive/10 transition-colors"
            aria-label="Remove widget"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* ── Widget content ───────────────────────────────────────────────── */}
      <div className={cn(isEditMode && "pt-4")}>{children}</div>

      {/* ── Edge handles (only when there are multiple columns) ──────────── */}
      {isEditMode && gridCols > 1 && (
        <>
          {/* Left pill — drag to shift column position */}
          <ShiftHandle
            widgetRef={widgetRef}
            colSpan={colSpan}
            colStart={effectiveStart ?? 1}
            gridCols={gridCols}
            onColStartChange={(start) => onColStartChange(widget.id, start)}
          />
          {/* Right pill — drag to resize width */}
          <ResizeHandle
            widgetRef={widgetRef}
            colSpan={colSpan}
            maxColSpan={maxColSpan}
            onColSpanChange={(span) => onColSpanChange(widget.id, span)}
          />
        </>
      )}
    </div>
  );
}
