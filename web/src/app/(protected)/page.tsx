"use client";

import { useState } from "react";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
  useDroppable,
  type DragEndEvent,
  type DragStartEvent,
  type DragOverEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  horizontalListSortingStrategy,
} from "@dnd-kit/sortable";
import { createPortal } from "react-dom";

import { useAuth } from "@/lib/auth/context";
import { useDashboardLayout } from "@/lib/dashboard/use-dashboard-layout";
import {
  type DashboardLayout,
  type DashboardRow,
  type WidgetInstance,
  type TodosWidgetConfig,
  type TodoFilter,
  type AiCoachWidgetConfig,
} from "@/lib/dashboard/types";

import { WidgetShell } from "@/components/dashboard/widget-shell";
import { TodosWidget } from "@/components/dashboard/todos-widget";
import { HabitsWidget } from "@/components/dashboard/habits-widget";
import { GoalProgressWidget } from "@/components/dashboard/goal-progress-widget";
import { ProjectProgressWidget } from "@/components/dashboard/project-progress-widget";
import { AiCoachWidget } from "@/components/dashboard/ai-coach-widget";
import { CalendarTodayWidget } from "@/components/dashboard/calendar-today-widget";
import { CalendarWeekWidget } from "@/components/dashboard/calendar-week-widget";
import { AddWidgetSheet } from "@/components/dashboard/add-widget-sheet";
import { Button } from "@/components/ui/button";
import { Settings2, Plus, Check } from "lucide-react";
import { cn } from "@/lib/utils";

// ── Helpers ───────────────────────────────────────────────────────────────────

function toLocalDateString(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function greeting(hour: number): string {
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

function formatDate(dateStr: string): string {
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}

// Written out explicitly so Tailwind's scanner includes the classes
const DESKTOP_COLS_CLASS: Record<number, string> = {
  1: "sm:grid-cols-1",
  2: "sm:grid-cols-2",
  3: "sm:grid-cols-3",
  4: "sm:grid-cols-4",
};

// ── Drop zone ID helpers ──────────────────────────────────────────────────────

function zoneBeforeRow(rowId: string) { return `zone-before:${rowId}`; }
function zoneAfterRow(rowId: string)  { return `zone-after:${rowId}`; }
function parseZone(id: string): { position: "before" | "after"; rowId: string } | null {
  if (id.startsWith("zone-before:")) return { position: "before", rowId: id.slice("zone-before:".length) };
  if (id.startsWith("zone-after:"))  return { position: "after",  rowId: id.slice("zone-after:".length) };
  return null;
}

// ── Inter-row drop zone component ─────────────────────────────────────────────

function RowDropZone({ id, isOver }: { id: string; isOver: boolean }) {
  const { setNodeRef, isOver: dndIsOver } = useDroppable({ id });
  const active = isOver || dndIsOver;
  return (
    <div
      ref={setNodeRef}
      className={cn(
        "flex items-center transition-all duration-150 rounded-lg overflow-hidden",
        active ? "h-12 my-1" : "h-3 my-0"
      )}
    >
      <div
        className={cn(
          "w-full rounded-lg border-2 border-dashed transition-all duration-150",
          active ? "border-primary/60 bg-primary/10 h-full" : "border-transparent h-0"
        )}
      />
    </div>
  );
}

// ── Widget renderer ───────────────────────────────────────────────────────────

function renderWidget(
  widget: WidgetInstance,
  today: string,
  isEditMode: boolean,
  onConfigChange: (id: string, config: Partial<WidgetInstance["config"]>) => void
) {
  switch (widget.type) {
    case "todos": {
      const cfg = widget.config as TodosWidgetConfig;
      return (
        <TodosWidget
          today={today}
          filter={cfg.filter}
          onFilterChange={(f: TodoFilter) => onConfigChange(widget.id, { filter: f })}
        />
      );
    }
    case "habits":
      return <HabitsWidget today={today} />;
    case "goal_progress":
      return <GoalProgressWidget config={widget.config as import("@/lib/dashboard/types").GoalProgressConfig} />;
    case "project_progress":
      return <ProjectProgressWidget config={widget.config as import("@/lib/dashboard/types").ProjectProgressConfig} />;
    case "ai_coach":
      return (
        <AiCoachWidget
          config={widget.config as AiCoachWidgetConfig}
          isEditMode={isEditMode}
          onConfigChange={(partial) => onConfigChange(widget.id, partial)}
        />
      );
    case "calendar_today":
      return <CalendarTodayWidget />;
    case "calendar_week":
      return <CalendarWeekWidget />;
    default:
      return null;
  }
}

// ── Layout mutation helpers ───────────────────────────────────────────────────

/** Find [rowIndex, widgetIndex] for a widget by id */
function findWidget(rows: DashboardRow[], widgetId: string): [number, number] | null {
  for (let ri = 0; ri < rows.length; ri++) {
    const wi = rows[ri].widgets.findIndex((w) => w.id === widgetId);
    if (wi !== -1) return [ri, wi];
  }
  return null;
}

/**
 * Remove a widget from its row. Returns [newRows, removedWidget].
 * Empty rows are NOT automatically dropped — caller decides.
 */
function extractWidget(
  rows: DashboardRow[],
  widgetId: string
): [DashboardRow[], WidgetInstance] | null {
  const pos = findWidget(rows, widgetId);
  if (!pos) return null;
  const [ri, wi] = pos;
  const widget = rows[ri].widgets[wi];
  const newRows = rows.map((r, i) =>
    i === ri ? { ...r, widgets: r.widgets.filter((_, j) => j !== wi) } : r
  );
  return [newRows, widget];
}

function dropEmptyRows(rows: DashboardRow[]): DashboardRow[] {
  return rows.filter((r) => r.widgets.length > 0);
}

/** Insert widget as a brand-new row before or after the given target row */
function insertAsNewRow(
  rows: DashboardRow[],
  widget: WidgetInstance,
  targetRowId: string,
  position: "before" | "after"
): DashboardRow[] {
  const newRow: DashboardRow = { id: crypto.randomUUID(), widgets: [widget] };
  const targetIdx = rows.findIndex((r) => r.id === targetRowId);
  if (targetIdx === -1) return [...rows, newRow];
  const insertIdx = position === "before" ? targetIdx : targetIdx + 1;
  const result = [...rows];
  result.splice(insertIdx, 0, newRow);
  return result;
}

// ── Dashboard page ────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const { user } = useAuth();
  const { layout, setLayout, isEditMode, setIsEditMode } = useDashboardLayout();
  const [addSheetOpen, setAddSheetOpen] = useState(false);

  // Track drag state for visual feedback
  const [activeWidgetId,  setActiveWidgetId]  = useState<string | null>(null);
  const [overZoneId,      setOverZoneId]       = useState<string | null>(null);
  // Which widget is hovered during a drag, and which side the indicator appears on
  const [overWidgetId,    setOverWidgetId]     = useState<string | null>(null);
  const [overWidgetSide,  setOverWidgetSide]   = useState<"left" | "right" | null>(null);

  const now   = new Date();
  const today = toLocalDateString(now);
  const name  = user?.display_name?.split(" ")[0] ?? user?.email ?? "there";

  // ── DnD sensors ────────────────────────────────────────────────────────────
  const sensors = useSensors(
    useSensor(PointerSensor, {
      // Small tolerance so clicks still register on drag handles
      activationConstraint: { distance: 6 },
    })
  );

  // ── DnD event handlers ─────────────────────────────────────────────────────

  function handleDragStart(event: DragStartEvent) {
    setActiveWidgetId(event.active.id as string);
  }

  function handleDragOver(event: DragOverEvent) {
    const overId = event.over?.id as string | undefined;

    if (!overId || overId === activeWidgetId) {
      setOverZoneId(null);
      setOverWidgetId(null);
      setOverWidgetSide(null);
      return;
    }

    if (parseZone(overId)) {
      setOverZoneId(overId);
      setOverWidgetId(null);
      setOverWidgetSide(null);
      return;
    }

    // Hovering over another widget — determine which side to show the indicator
    setOverZoneId(null);
    setOverWidgetId(overId);
    const translated = event.active.rect.current.translated;
    const overRect   = event.over?.rect;
    if (translated && overRect) {
      const activeMidX = translated.left + translated.width / 2;
      const overMidX   = overRect.left + overRect.width / 2;
      setOverWidgetSide(activeMidX < overMidX ? "left" : "right");
    }
  }

  function handleDragEnd(event: DragEndEvent) {
    setActiveWidgetId(null);
    setOverZoneId(null);
    setOverWidgetId(null);
    setOverWidgetSide(null);

    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const draggedId = active.id as string;
    const overId    = over.id as string;

    // ── Dropped on an inter-row zone → create new row ───────────────────────
    const zone = parseZone(overId);
    if (zone) {
      const extracted = extractWidget(layout.rows, draggedId);
      if (!extracted) return;
      const [rowsAfterExtract, widget] = extracted;
      // Recalculate the target row id after extraction (row still exists unless it was the only widget)
      const finalRows = insertAsNewRow(
        dropEmptyRows(rowsAfterExtract),
        widget,
        zone.rowId,
        zone.position
      );
      setLayout({ ...layout, rows: finalRows });
      return;
    }

    // ── Dropped on another widget → reorder or merge rows ───────────────────
    const dragPos = findWidget(layout.rows, draggedId);
    const overPos = findWidget(layout.rows, overId);
    if (!dragPos || !overPos) return;

    const [dragRowIdx, dragWidgetIdx] = dragPos;
    const [overRowIdx,  overWidgetIdx]  = overPos;

    if (dragRowIdx === overRowIdx) {
      // Same row — horizontal reorder
      const row = layout.rows[dragRowIdx];
      const newWidgets = arrayMove(row.widgets, dragWidgetIdx, overWidgetIdx);
      const newRows = layout.rows.map((r, i) =>
        i === dragRowIdx ? { ...r, widgets: newWidgets } : r
      );
      setLayout({ ...layout, rows: newRows });
    } else {
      // Different row — move dragged widget into the over-widget's row,
      // inserting it at the over-widget's position.
      const extracted = extractWidget(layout.rows, draggedId);
      if (!extracted) return;
      const [rowsAfterExtract, widget] = extracted;

      const newOverPos = findWidget(rowsAfterExtract, overId);
      if (!newOverPos) return;
      const [newOverRowIdx, newOverWidgetIdx] = newOverPos;

      const newRows = rowsAfterExtract.map((r, i) => {
        if (i !== newOverRowIdx) return r;
        const widgets = [...r.widgets];
        widgets.splice(newOverWidgetIdx, 0, widget);
        return { ...r, widgets };
      });
      setLayout({ ...layout, rows: dropEmptyRows(newRows) });
    }
  }

  // ── Layout mutations ───────────────────────────────────────────────────────

  function handleRemoveWidget(id: string) {
    const extracted = extractWidget(layout.rows, id);
    if (!extracted) return;
    const [newRows] = extracted;
    setLayout({ ...layout, rows: dropEmptyRows(newRows) });
  }

  function handleAddWidget(partial: Omit<WidgetInstance, "id">) {
    const newWidget: WidgetInstance = { id: crypto.randomUUID(), ...partial };
    const newRow: DashboardRow = { id: crypto.randomUUID(), widgets: [newWidget] };
    setLayout({ ...layout, rows: [...layout.rows, newRow] });
  }

  function handleConfigChange(id: string, config: Partial<WidgetInstance["config"]>) {
    setLayout({
      ...layout,
      rows: layout.rows.map((row) => ({
        ...row,
        widgets: row.widgets.map((w) =>
          w.id === id ? { ...w, config: { ...w.config, ...config } } : w
        ),
      })),
    });
  }

  function handleColSpanChange(id: string, colSpan: number) {
    setLayout({
      ...layout,
      rows: layout.rows.map((row) => ({
        ...row,
        widgets: row.widgets.map((w) => (w.id === id ? { ...w, colSpan } : w)),
      })),
    });
  }

  function handleColStartChange(id: string, colStart: number | null) {
    setLayout({
      ...layout,
      rows: layout.rows.map((row) => ({
        ...row,
        widgets: row.widgets.map((w) =>
          w.id === id ? { ...w, colStart: colStart ?? undefined } : w
        ),
      })),
    });
  }

  function handleColumnsChange(cols: DashboardLayout["columns"]) {
    setLayout({ ...layout, columns: cols });
  }

  // ── Drag overlay widget ────────────────────────────────────────────────────
  const activeWidget = activeWidgetId
    ? layout.rows.flatMap((r) => r.widgets).find((w) => w.id === activeWidgetId) ?? null
    : null;

  const totalWidgets = layout.rows.reduce((n, r) => n + r.widgets.length, 0);

  return (
    <div className="flex flex-col min-h-full">
      {/* ── Header strip ──────────────────────────────────────────────────── */}
      <div className="border-b bg-muted/20 px-6 py-5 shrink-0">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wide">
              {formatDate(today)}
            </p>
            <h1 className="text-xl font-semibold mt-1">
              {greeting(now.getHours())}, {name}.
            </h1>
          </div>

          {/* Edit mode toggle */}
          <button
            type="button"
            onClick={() => setIsEditMode(!isEditMode)}
            className={cn(
              "mt-1 flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer",
              isEditMode
                ? "bg-primary text-primary-foreground hover:bg-primary/90"
                : "text-muted-foreground hover:text-foreground hover:bg-muted"
            )}
            aria-label={isEditMode ? "Done editing" : "Edit dashboard"}
          >
            {isEditMode ? (
              <>
                <Check className="h-3.5 w-3.5" />
                Done
              </>
            ) : (
              <>
                <Settings2 className="h-3.5 w-3.5" />
                Edit
              </>
            )}
          </button>
        </div>

        {/* Column count + edit hint — only in edit mode */}
        {isEditMode && (
          <div className="flex items-center gap-2 mt-4 flex-wrap">
            <span className="text-xs text-muted-foreground">Columns:</span>
            {([1, 2, 3, 4] as const).map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => handleColumnsChange(n)}
                className={cn(
                  "w-7 h-7 rounded text-xs font-medium transition-colors cursor-pointer",
                  layout.columns === n
                    ? "bg-primary text-primary-foreground"
                    : "border text-muted-foreground hover:text-foreground hover:bg-muted"
                )}
              >
                {n}
              </button>
            ))}
            <span className="text-xs text-muted-foreground/60 ml-1">
              · drag to reorder, grab edge to resize
            </span>
          </div>
        )}
      </div>

      {/* ── Widget grid ───────────────────────────────────────────────────── */}
      <div className="p-6 flex-1">
        <DndContext
          sensors={sensors}
          onDragStart={handleDragStart}
          onDragOver={handleDragOver}
          onDragEnd={handleDragEnd}
        >
          <div className="flex flex-col gap-4">
            {totalWidgets === 0 && (
              <div className="py-16 text-center">
                <p className="text-sm text-muted-foreground">
                  No widgets yet.{" "}
                  {isEditMode ? "Add one below." : "Click Edit to add widgets."}
                </p>
              </div>
            )}

            {layout.rows.map((row, rowIdx) => {
              const widgetIds = row.widgets.map((w) => w.id);
              const usedSpans = row.widgets.reduce((s, w) => s + (w.colSpan ?? 1), 0);
              const isLast    = rowIdx === layout.rows.length - 1;

              return (
                <div key={row.id}>
                  {/* Drop zone ABOVE this row — shown only while dragging */}
                  {activeWidgetId && (
                    <RowDropZone
                      id={zoneBeforeRow(row.id)}
                      isOver={overZoneId === zoneBeforeRow(row.id)}
                    />
                  )}

                  {/* Row widgets */}
                  <SortableContext items={widgetIds} strategy={horizontalListSortingStrategy}>
                    <div
                      className={cn(
                        "grid grid-cols-1 gap-4",
                        DESKTOP_COLS_CLASS[layout.columns]
                      )}
                    >
                      {row.widgets.map((widget) => {
                        const siblingsSpan = usedSpans - (widget.colSpan ?? 1);
                        const maxColSpan   = Math.max(1, layout.columns - siblingsSpan);

                        // Show the drop indicator only when this widget is
                        // being hovered during a drag (not the dragged widget itself)
                        const isDropTarget =
                          activeWidgetId !== null &&
                          widget.id === overWidgetId &&
                          widget.id !== activeWidgetId;

                        return (
                          <WidgetShell
                            key={widget.id}
                            widget={widget}
                            isEditMode={isEditMode}
                            gridCols={layout.columns}
                            maxColSpan={maxColSpan}
                            dropIndicatorSide={isDropTarget ? overWidgetSide : null}
                            onRemove={handleRemoveWidget}
                            onColSpanChange={handleColSpanChange}
                            onColStartChange={handleColStartChange}
                          >
                            {renderWidget(widget, today, isEditMode, handleConfigChange)}
                          </WidgetShell>
                        );
                      })}
                    </div>
                  </SortableContext>

                  {/* Drop zone BELOW the last row — shown only while dragging */}
                  {activeWidgetId && isLast && (
                    <RowDropZone
                      id={zoneAfterRow(row.id)}
                      isOver={overZoneId === zoneAfterRow(row.id)}
                    />
                  )}
                </div>
              );
            })}
          </div>

          {/* Drag overlay — floating ghost of the dragged widget */}
          {typeof document !== "undefined" &&
            createPortal(
              <DragOverlay dropAnimation={null}>
                {activeWidget && (
                  <div className="rounded-lg border bg-card p-4 shadow-2xl opacity-90 rotate-1 scale-[1.03] pointer-events-none">
                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                      {activeWidget.type.replace(/_/g, " ")}
                    </p>
                  </div>
                )}
              </DragOverlay>,
              document.body
            )}
        </DndContext>

        {/* Add widget button — edit mode only */}
        {isEditMode && (
          <div className="mt-4">
            <Button
              variant="outline"
              className="w-full border-dashed text-muted-foreground hover:text-foreground"
              onClick={() => setAddSheetOpen(true)}
            >
              <Plus className="h-4 w-4 mr-2" />
              Add widget
            </Button>
          </div>
        )}
      </div>

      <AddWidgetSheet
        open={addSheetOpen}
        onClose={() => setAddSheetOpen(false)}
        onAdd={handleAddWidget}
      />
    </div>
  );
}
