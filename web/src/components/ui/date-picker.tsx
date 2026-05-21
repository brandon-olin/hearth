"use client";

import { useEffect, useRef, useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

// ── Helpers ───────────────────────────────────────────────────────────────────

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const DAY_LABELS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

function todayStr(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Parse YYYY-MM-DD → { year, month (0-idx), day } or null. */
function parseDate(val: string): { year: number; month: number; day: number } | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(val)) return null;
  const year = parseInt(val.slice(0, 4), 10);
  const month = parseInt(val.slice(5, 7), 10) - 1;
  const day = parseInt(val.slice(8, 10), 10);
  if (month < 0 || month > 11 || day < 1 || day > 31) return null;
  return { year, month, day };
}

/** Format YYYY-MM-DD → "May 21, 2026" (for display only). */
function formatDisplay(val: string): string {
  const p = parseDate(val);
  if (!p) return val;
  return new Date(p.year, p.month, p.day).toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

// ── Calendar grid builder ─────────────────────────────────────────────────────

interface GridCell {
  day: number;
  current: boolean; // belongs to the viewed month
  dateStr: string;  // YYYY-MM-DD
}

function buildGrid(year: number, month: number): GridCell[] {
  const firstDow = new Date(year, month, 1).getDay(); // 0 = Sun
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const prevDays = new Date(year, month, 0).getDate();

  const cells: GridCell[] = [];

  // Overflow from previous month
  for (let i = firstDow - 1; i >= 0; i--) {
    const d = prevDays - i;
    const m = month === 0 ? 11 : month - 1;
    const y = month === 0 ? year - 1 : year;
    cells.push({
      day: d,
      current: false,
      dateStr: `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`,
    });
  }

  // Current month
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push({
      day: d,
      current: true,
      dateStr: `${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`,
    });
  }

  // Fill remaining rows (always show 6 rows = 42 cells)
  const remaining = 42 - cells.length;
  const nextMonth = month === 11 ? 0 : month + 1;
  const nextYear = month === 11 ? year + 1 : year;
  for (let d = 1; d <= remaining; d++) {
    cells.push({
      day: d,
      current: false,
      dateStr: `${nextYear}-${String(nextMonth + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`,
    });
  }

  return cells;
}

// ── Component ─────────────────────────────────────────────────────────────────

interface DatePickerProps {
  /** Selected date as YYYY-MM-DD string, or empty string for none. */
  value: string;
  onChange: (val: string) => void;
  placeholder?: string;
  className?: string;
  id?: string;
}

export function DatePicker({
  value,
  onChange,
  placeholder = "Pick a date",
  className,
  id,
}: DatePickerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [inputRaw, setInputRaw] = useState(value); // what the text input holds while focused

  // When the calendar is closed and value changes externally, sync inputRaw
  useEffect(() => {
    if (!open) setInputRaw(value);
  }, [value, open]);

  // Initial view: default to the selected date's month, or current month
  const parsed = parseDate(value);
  const [viewYear, setViewYear] = useState(parsed?.year ?? new Date().getFullYear());
  const [viewMonth, setViewMonth] = useState(parsed?.month ?? new Date().getMonth());

  // When value changes, snap the calendar view to that date's month
  useEffect(() => {
    const p = parseDate(value);
    if (p) { setViewYear(p.year); setViewMonth(p.month); }
  }, [value]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handle(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [open]);

  // ── Month navigation ───────────────────────────────────────────────────────

  function prevMonth() {
    if (viewMonth === 0) { setViewMonth(11); setViewYear((y) => y - 1); }
    else setViewMonth((m) => m - 1);
  }

  function nextMonth() {
    if (viewMonth === 11) { setViewMonth(0); setViewYear((y) => y + 1); }
    else setViewMonth((m) => m + 1);
  }

  // ── Text input handling ────────────────────────────────────────────────────

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const raw = e.target.value;
    setInputRaw(raw);
    // Accept YYYY-MM-DD once complete
    if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
      onChange(raw);
    }
  }

  function handleInputBlur() {
    // Commit or revert on blur
    if (/^\d{4}-\d{2}-\d{2}$/.test(inputRaw)) {
      onChange(inputRaw);
    } else {
      setInputRaw(value); // revert to last valid
    }
  }

  function handleInputFocus() {
    // Switch to raw YYYY-MM-DD for editing
    setInputRaw(value);
    // Don't open the calendar on focus — only via the icon button
  }

  // ── Day selection ──────────────────────────────────────────────────────────

  function selectDay(dateStr: string) {
    onChange(dateStr);
    setOpen(false);
    setInputRaw(dateStr);
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  const today = todayStr();
  const grid = buildGrid(viewYear, viewMonth);
  // Display value: formatted when closed and valid, otherwise raw
  const isFocused = document.activeElement === inputRef.current;
  const displayValue = isFocused ? inputRaw : (value ? formatDisplay(value) : "");

  return (
    <div ref={containerRef} className={cn("relative", className)}>
      {/* Input row */}
      <div className="relative flex items-center">
        <input
          ref={inputRef}
          id={id}
          type="text"
          value={displayValue}
          onChange={handleInputChange}
          onFocus={handleInputFocus}
          onBlur={handleInputBlur}
          placeholder={placeholder}
          className={cn(
            // Match the app's Input component styling exactly
            "h-8 w-full min-w-0 rounded-lg border border-input bg-transparent",
            "px-2.5 py-1 pr-8 text-sm transition-colors outline-none",
            "placeholder:text-muted-foreground",
            "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
            "dark:bg-input/30"
          )}
        />
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="absolute right-2 text-muted-foreground hover:text-foreground transition-colors"
          tabIndex={-1}
          aria-label="Open calendar"
        >
          <CalendarDays className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Calendar popover */}
      {open && (
        <div
          className={cn(
            "absolute z-50 mt-1.5 w-[268px] rounded-xl border border-border bg-popover shadow-lg p-3",
            // Open upward if near the bottom? For now always down.
            "top-full left-0"
          )}
          onMouseDown={(e) => e.preventDefault()} // prevent blur on input
        >
          {/* Month / year header */}
          <div className="flex items-center justify-between mb-2">
            <button
              type="button"
              onClick={prevMonth}
              className="p-1 rounded-md hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="text-sm font-semibold">
              {MONTH_NAMES[viewMonth]} {viewYear}
            </span>
            <button
              type="button"
              onClick={nextMonth}
              className="p-1 rounded-md hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>

          {/* Day-of-week labels */}
          <div className="grid grid-cols-7 mb-1">
            {DAY_LABELS.map((d) => (
              <div
                key={d}
                className="text-center text-[11px] font-medium text-muted-foreground/70 py-1 select-none"
              >
                {d}
              </div>
            ))}
          </div>

          {/* Day grid */}
          <div className="grid grid-cols-7 gap-y-0.5">
            {grid.map((cell, i) => {
              if (!cell.current) {
                return (
                  <div
                    key={i}
                    className="flex items-center justify-center h-8 text-[13px] text-muted-foreground/25 select-none"
                  >
                    {cell.day}
                  </div>
                );
              }
              const isSelected = cell.dateStr === value;
              const isToday = cell.dateStr === today;
              return (
                <button
                  key={i}
                  type="button"
                  onClick={() => selectDay(cell.dateStr)}
                  className={cn(
                    "flex items-center justify-center h-8 w-full rounded-lg text-[13px] transition-colors",
                    isSelected
                      ? "bg-primary text-primary-foreground font-semibold"
                      : isToday
                      ? "text-primary font-semibold hover:bg-muted"
                      : "hover:bg-muted text-foreground"
                  )}
                >
                  {cell.day}
                </button>
              );
            })}
          </div>

          {/* Clear + Today row */}
          <div className="flex items-center justify-between mt-2 pt-2 border-t border-border">
            <button
              type="button"
              onClick={() => { onChange(""); setInputRaw(""); setOpen(false); }}
              className="text-xs text-muted-foreground hover:text-foreground transition-colors px-1"
            >
              Clear
            </button>
            <button
              type="button"
              onClick={() => selectDay(today)}
              className="text-xs text-primary hover:text-primary/80 transition-colors px-1 font-medium"
            >
              Today
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
