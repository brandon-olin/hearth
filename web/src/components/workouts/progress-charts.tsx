"use client";

/**
 * Hand-rolled SVG charts for the workouts Progress tab (workouts-004).
 *
 * The project has no charting dependency and two SVG precedents
 * (`ui/progress-ring.tsx`, `notes/note-graph.tsx`) — these follow them: plain
 * polylines over a scaled domain, every colour via `currentColor` + a themed
 * Tailwind class so palette switching keeps working. Geometry is in fixed
 * pixels with a horizontally scrollable wrapper (the budget chart's approach) —
 * a scaled viewBox would shrink the axis text to nothing on a phone.
 */

import { useState } from "react";
import { cn } from "@/lib/utils";

// ── Sparkline ────────────────────────────────────────────────────────────────

const SPARK_W = 72;
const SPARK_H = 20;
const SPARK_PAD = 3;

/** Tiny inline trend — used on each row of the progress list. */
export function Sparkline({
  values,
  className,
}: {
  values: number[];
  className?: string;
}) {
  if (values.length < 2) return null;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min;
  const innerH = SPARK_H - SPARK_PAD * 2;
  const stepX = (SPARK_W - SPARK_PAD * 2) / (values.length - 1);

  const coords = values.map((v, i) => {
    const x = SPARK_PAD + i * stepX;
    // A flat series (span 0) draws down the middle rather than at the top.
    const y = span === 0 ? SPARK_H / 2 : SPARK_PAD + innerH - ((v - min) / span) * innerH;
    return [x, y] as const;
  });
  const last = coords[coords.length - 1];

  return (
    <svg
      width={SPARK_W}
      height={SPARK_H}
      viewBox={`0 0 ${SPARK_W} ${SPARK_H}`}
      className={cn("text-primary shrink-0", className)}
      aria-hidden="true"
    >
      <polyline
        points={coords.map(([x, y]) => `${x},${y}`).join(" ")}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={last[0]} cy={last[1]} r={2} fill="currentColor" />
    </svg>
  );
}

// ── Line chart ───────────────────────────────────────────────────────────────

export interface ChartPoint {
  /** X-axis label, e.g. "Jul 10". */
  label: string;
  /** Null renders a gap — e.g. a session with no set light enough to estimate a 1RM. */
  value: number | null;
  /** Session contained a working set below its target reps. */
  failed: boolean;
}

const H = 140;
const PAD_T = 10;
const PAD_B = 36;
const PAD_L = 46;
const PAD_R = 14;
const STEP = 58;
const TICKS = 3;

function niceDomain(values: number[]): [number, number] {
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (min === max) {
    // A single distinct value still needs a band to sit in.
    const pad = Math.abs(min) * 0.1 || 1;
    return [min - pad, max + pad];
  }
  const pad = (max - min) * 0.15;
  return [min - pad, max + pad];
}

/**
 * One line chart: a point per session, oldest to newest. Sessions with a failed
 * set are marked with a ✗ under the axis.
 */
export function LineChart({
  points,
  formatValue,
  unit,
}: {
  points: ChartPoint[];
  formatValue: (v: number) => string;
  unit?: string;
}) {
  const [hovered, setHovered] = useState<number | null>(null);

  const present = points.filter((p) => p.value != null).map((p) => p.value as number);
  if (present.length === 0) {
    return (
      <p className="text-sm text-muted-foreground text-center py-10">
        No data for this chart yet.
      </p>
    );
  }

  const [lo, hi] = niceDomain(present);
  const span = hi - lo || 1;
  const width = PAD_L + Math.max(1, points.length - 1) * STEP + PAD_R;
  const svgH = PAD_T + H + PAD_B;

  const x = (i: number) => PAD_L + i * STEP;
  const y = (v: number) => PAD_T + H - ((v - lo) / span) * H;

  // Consecutive runs of non-null points become separate polylines, so a gap
  // stays a gap instead of being bridged by a misleading straight line.
  const segments: Array<Array<{ i: number; v: number }>> = [];
  let run: Array<{ i: number; v: number }> = [];
  points.forEach((p, i) => {
    if (p.value == null) {
      if (run.length) segments.push(run);
      run = [];
    } else {
      run.push({ i, v: p.value });
    }
  });
  if (run.length) segments.push(run);

  const ticks = Array.from({ length: TICKS }, (_, t) => {
    const v = lo + (span * t) / (TICKS - 1);
    return { v, y: y(v) };
  });

  const active = hovered != null ? points[hovered] : null;

  return (
    <div>
      {/* Read-out for the hovered/tapped session — keeps the SVG label-free. */}
      <div className="h-5 mb-1 text-xs tabular-nums">
        {active ? (
          <span className="flex items-center gap-2">
            <span className="text-muted-foreground">{active.label}</span>
            <span className="font-medium">
              {active.value == null ? "—" : `${formatValue(active.value)}${unit ? ` ${unit}` : ""}`}
            </span>
            {active.failed && (
              <span className="text-destructive">✗ missed a target</span>
            )}
          </span>
        ) : (
          <span className="text-muted-foreground">
            Hover a point for that session&rsquo;s number.
          </span>
        )}
      </div>

      <div className="overflow-x-auto">
        <svg width={width} height={svgH} className="text-primary">
          {/* Gridlines + y-axis labels */}
          {ticks.map((t) => (
            <g key={t.v}>
              <line
                x1={PAD_L - 4}
                x2={width - PAD_R}
                y1={t.y}
                y2={t.y}
                stroke="currentColor"
                strokeOpacity={0.1}
                strokeWidth={1}
                className="text-foreground"
              />
              <text
                x={PAD_L - 8}
                y={t.y + 3.5}
                textAnchor="end"
                fontSize={9}
                fill="currentColor"
                opacity={0.5}
                className="text-foreground tabular-nums"
              >
                {formatValue(t.v)}
              </text>
            </g>
          ))}

          {/* The trend itself */}
          {segments.map((seg, si) => (
            <polyline
              key={si}
              points={seg.map((p) => `${x(p.i)},${y(p.v)}`).join(" ")}
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ))}

          {points.map((p, i) => (
            <g
              key={i}
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered(null)}
              onClick={() => setHovered(i)}
            >
              {/* Generous invisible hit area — the dots themselves are tiny. */}
              <rect
                x={x(i) - STEP / 2}
                y={PAD_T}
                width={STEP}
                height={H + PAD_B}
                fill="transparent"
              />
              {hovered === i && (
                <line
                  x1={x(i)}
                  x2={x(i)}
                  y1={PAD_T}
                  y2={PAD_T + H}
                  stroke="currentColor"
                  strokeOpacity={0.25}
                  strokeWidth={1}
                  className="text-foreground"
                />
              )}
              {p.value != null && (
                <circle
                  cx={x(i)}
                  cy={y(p.value)}
                  r={hovered === i ? 4 : 3}
                  fill="currentColor"
                />
              )}
              {/* Failed-set marker, on the timeline under the plot. */}
              {p.failed && (
                <text
                  x={x(i)}
                  y={PAD_T + H + 14}
                  textAnchor="middle"
                  fontSize={10}
                  fill="currentColor"
                  className="text-destructive"
                >
                  ✗
                </text>
              )}
              <text
                x={x(i)}
                y={PAD_T + H + 28}
                textAnchor="middle"
                fontSize={9}
                fill="currentColor"
                opacity={hovered === i ? 0.9 : 0.5}
                className="text-foreground"
              >
                {p.label}
              </text>
            </g>
          ))}
        </svg>
      </div>
    </div>
  );
}
