import { cn } from "@/lib/utils";

export function ProgressRing({
  percent,
  size,
  strokeWidth = 8,
  className,
}: {
  percent: number;
  /** Explicit pixel size. Omit to fill the parent container. */
  size?: number;
  /**
   * Stroke width in the same units as `size` (or 0-100 viewBox units when
   * `size` is omitted). Default: 8 (fills well at most sizes).
   */
  strokeWidth?: number;
  className?: string;
}) {
  // When size is explicit, the viewBox matches so strokeWidth is pixel-exact.
  // When size is omitted, viewBox is 100×100 so strokeWidth is a % of the ring.
  const vw = size ?? 100;
  const r = (vw - strokeWidth) / 2;
  const circ = 2 * Math.PI * r;
  const offset = circ * (1 - Math.min(1, Math.max(0, percent / 100)));
  const pct = Math.round(percent);
  const fontSize = vw * 0.22;

  return (
    <div
      className={cn(
        "relative inline-flex items-center justify-center",
        !size && "w-full h-full",
        className,
      )}
      style={size ? { width: size, height: size } : undefined}
    >
      <svg
        viewBox={`0 0 ${vw} ${vw}`}
        width={size ?? "100%"}
        height={size ?? "100%"}
        aria-label={`${pct}% complete`}
      >
        {/* Track */}
        <circle
          cx={vw / 2}
          cy={vw / 2}
          r={r}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          className="text-muted-foreground/20"
        />
        {/* Fill — rotated so progress starts from top */}
        <circle
          cx={vw / 2}
          cy={vw / 2}
          r={r}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          className={pct >= 100 ? "text-emerald-500" : "text-primary"}
          strokeDasharray={circ}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform={`rotate(-90, ${vw / 2}, ${vw / 2})`}
          style={{ transition: "stroke-dashoffset 0.4s ease" }}
        />
        {/* Percentage label — stays upright */}
        <text
          x={vw / 2}
          y={vw / 2}
          textAnchor="middle"
          dominantBaseline="central"
          fontSize={fontSize}
          fontWeight="600"
          fill="currentColor"
          className="tabular-nums"
        >
          {pct}%
        </text>
      </svg>
    </div>
  );
}
