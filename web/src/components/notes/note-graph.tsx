"use client";

import { useEffect, useLayoutEffect, useRef, useState, useCallback, useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import { apiBaseUrl } from "@/lib/api/client";
import { getAccessToken } from "@/lib/auth/token";
import { cn } from "@/lib/utils";
import { RefreshCw } from "lucide-react";
import type { components } from "@/lib/api/schema";

type NoteSummary = components["schemas"]["NoteSummary"];
type TagResponse  = components["schemas"]["TagResponse"];

// ── Types ─────────────────────────────────────────────────────────────────────

interface GraphNode {
  id: string;
  title: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  degree: number;  // edge count — used for radius
  color: string;
}

interface GraphEdge {
  source: string;
  target: string;
}

// ── Wikilink parsing ──────────────────────────────────────────────────────────

function parseWikilinks(md: string | null): string[] {
  if (!md) return [];
  const matches = md.match(/\[\[([^\]]+)\]\]/g) ?? [];
  return matches.map((m) => m.slice(2, -2).trim());
}

// ── Force simulation ──────────────────────────────────────────────────────────

const K_REPEL  = 4500;   // node-node repulsion
const K_SPRING = 0.06;   // edge spring attraction
const REST_LEN = 130;    // desired edge length (px)
const K_CENTER = 0.004;  // gravity toward canvas centre
const DAMPING  = 0.82;
const DT       = 1.0;
const STOP_THRESHOLD = 0.3;  // avg velocity below this → stop

function initPositions(
  nodes: GraphNode[],
  cx: number,
  cy: number,
  radius: number
): void {
  nodes.forEach((n, i) => {
    const angle = (i / nodes.length) * 2 * Math.PI;
    n.x  = cx + radius * Math.cos(angle) + (Math.random() - 0.5) * 20;
    n.y  = cy + radius * Math.sin(angle) + (Math.random() - 0.5) * 20;
    n.vx = 0;
    n.vy = 0;
  });
}

function tickSimulation(
  nodes: GraphNode[],
  edges: GraphEdge[],
  cx: number,
  cy: number
): number {
  const fx: number[] = nodes.map(() => 0);
  const fy: number[] = nodes.map(() => 0);
  const idx = new Map(nodes.map((n, i) => [n.id, i]));

  // Repulsion between every pair
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const dx = nodes[i].x - nodes[j].x;
      const dy = nodes[i].y - nodes[j].y;
      const d2 = dx * dx + dy * dy;
      const d  = Math.max(Math.sqrt(d2), 1);
      const f  = K_REPEL / (d2);
      const nx = (dx / d) * f;
      const ny = (dy / d) * f;
      fx[i] += nx; fy[i] += ny;
      fx[j] -= nx; fy[j] -= ny;
    }
  }

  // Spring attraction along edges
  for (const e of edges) {
    const si = idx.get(e.source);
    const ti = idx.get(e.target);
    if (si === undefined || ti === undefined) continue;
    const dx = nodes[si].x - nodes[ti].x;
    const dy = nodes[si].y - nodes[ti].y;
    const d  = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
    const f  = K_SPRING * (d - REST_LEN);
    const nx = (dx / d) * f;
    const ny = (dy / d) * f;
    fx[si] -= nx; fy[si] -= ny;
    fx[ti] += nx; fy[ti] += ny;
  }

  // Center gravity
  for (let i = 0; i < nodes.length; i++) {
    fx[i] -= K_CENTER * (nodes[i].x - cx);
    fy[i] -= K_CENTER * (nodes[i].y - cy);
  }

  // Integrate
  let totalV = 0;
  for (let i = 0; i < nodes.length; i++) {
    nodes[i].vx = (nodes[i].vx + fx[i] * DT) * DAMPING;
    nodes[i].vy = (nodes[i].vy + fy[i] * DT) * DAMPING;
    nodes[i].x += nodes[i].vx * DT;
    nodes[i].y += nodes[i].vy * DT;
    totalV += Math.abs(nodes[i].vx) + Math.abs(nodes[i].vy);
  }

  return totalV / nodes.length;
}

// ── Default tag colors (fallback if tag has no color) ─────────────────────────

const FALLBACK_COLOR = "#94a3b8";

// ── Component ─────────────────────────────────────────────────────────────────

interface NoteGraphProps {
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function NoteGraph({ selectedId, onSelect }: NoteGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const simNodes = useRef<GraphNode[]>([]);
  const simEdges = useRef<GraphEdge[]>([]);
  const animFrame = useRef<number | null>(null);
  const [renderNodes, setRenderNodes] = useState<GraphNode[]>([]);
  const [renderEdges, setRenderEdges] = useState<GraphEdge[]>([]);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [dimensions, setDimensions] = useState({ w: 800, h: 600 });

  // ── Data fetching ────────────────────────────────────────────────────────────

  const { data: notesData } = $api.useQuery("get", "/notes", {
    params: { query: { limit: 500 } },
  });

  const { data: tagsData } = $api.useQuery("get", "/tags", {
    params: { query: { limit: 100 } },
  });

  const tags: TagResponse[] = tagsData?.items ?? [];

  // Parallel per-tag note queries to build nodeId → color map
  const tagNoteQueries = useQueries({
    queries: tags.map((tag) => ({
      queryKey: ["notes-by-tag", tag.id],
      queryFn: async (): Promise<{ tagId: string; noteIds: string[] }> => {
        const token = getAccessToken();
        const res = await fetch(`${apiBaseUrl}/notes?tag_id=${tag.id}&limit=500`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        const data = await res.json();
        return {
          tagId: tag.id,
          noteIds: (data.items ?? []).map((n: NoteSummary) => n.id),
        };
      },
      enabled: tags.length > 0,
      staleTime: 30_000,
    })),
  });

  // Build nodeId → color (use first matching tag's color) — reactive memo
  const nodeColorMap = useMemo(() => {
    const map = new Map<string, string>();
    tagNoteQueries.forEach((q, i) => {
      if (!q.data) return;
      const tag = tags[i];
      if (!tag) return;
      q.data.noteIds.forEach((id) => {
        if (!map.has(id)) map.set(id, tag.color ?? FALLBACK_COLOR);
      });
    });
    return map;
  }, [tagNoteQueries, tags]);

  // Keep a ref so startSimulation (a callback) always reads the latest value
  const nodeColorMapRef = useRef(nodeColorMap);
  useLayoutEffect(() => {
    nodeColorMapRef.current = nodeColorMap;
  }, [nodeColorMap]);

  // Whenever the color map updates, patch both simNodes and renderNodes so the
  // animation loop (which spreads simNodes) picks up the correct colors too.
  useEffect(() => {
    if (!simNodes.current.length) return;
    simNodes.current.forEach((n) => {
      n.color = nodeColorMapRef.current.get(n.id) ?? FALLBACK_COLOR;
    });
    setRenderNodes((prev) =>
      prev.map((n) => ({ ...n, color: nodeColorMapRef.current.get(n.id) ?? FALLBACK_COLOR }))
    );
  }, [nodeColorMap]);

  // ── Container dimensions ──────────────────────────────────────────────────

  useEffect(() => {
    const el = svgRef.current?.parentElement;
    if (!el) return;
    const obs = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      if (width > 0 && height > 0) setDimensions({ w: width, h: height });
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  // ── Build and run simulation when data changes ───────────────────────────

  const startSimulation = useCallback(() => {
    if (!notesData?.items?.length) return;

    const notes = notesData.items;
    const titleToId = new Map(notes.map((n) => [n.title.toLowerCase(), n.id]));

    // Build edges from wikilinks
    const edges: GraphEdge[] = [];
    const edgeSet = new Set<string>();
    for (const note of notes) {
      const targets = parseWikilinks(note.content_md);
      for (const t of targets) {
        const targetId = titleToId.get(t.toLowerCase());
        if (!targetId || targetId === note.id) continue;
        const key = [note.id, targetId].sort().join(":");
        if (!edgeSet.has(key)) {
          edgeSet.add(key);
          edges.push({ source: note.id, target: targetId });
        }
      }
    }

    // Compute degree
    const degree = new Map<string, number>();
    for (const e of edges) {
      degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
      degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
    }

    const { w, h } = dimensions;
    const cx = w / 2, cy = h / 2;

    const nodes: GraphNode[] = notes.map((n) => ({
      id:     n.id,
      title:  n.title,
      x: 0, y: 0, vx: 0, vy: 0,
      degree: degree.get(n.id) ?? 0,
      color:  nodeColorMapRef.current.get(n.id) ?? FALLBACK_COLOR,
    }));

    initPositions(nodes, cx, cy, Math.min(w, h) * 0.32);
    simNodes.current = nodes;
    simEdges.current = edges;

    if (animFrame.current) cancelAnimationFrame(animFrame.current);
    setRunning(true);

    let tick = 0;
    function loop() {
      const avgV = tickSimulation(simNodes.current, simEdges.current, cx, cy);
      tick++;
      // Refresh render every 3 ticks
      if (tick % 3 === 0) {
        setRenderNodes(simNodes.current.map((n) => ({ ...n })));
        setRenderEdges([...simEdges.current]);
      }
      if (avgV > STOP_THRESHOLD && tick < 600) {
        animFrame.current = requestAnimationFrame(loop);
      } else {
        setRenderNodes(simNodes.current.map((n) => ({ ...n })));
        setRenderEdges([...simEdges.current]);
        setRunning(false);
      }
    }

    animFrame.current = requestAnimationFrame(loop);
  }, [notesData, dimensions]);

  // Auto-start when data is ready
  useEffect(() => {
    if (notesData?.items?.length) startSimulation();
    return () => {
      if (animFrame.current) cancelAnimationFrame(animFrame.current);
    };
  }, [notesData, dimensions]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Render ─────────────────────────────────────────────────────────────────

  const { w, h } = dimensions;
  const nodeRadius = (n: GraphNode) => Math.max(12, Math.min(22, 12 + n.degree * 2.5));

  const hoveredNeighbors = new Set<string>();
  if (hoveredId) {
    renderEdges.forEach((e) => {
      if (e.source === hoveredId) hoveredNeighbors.add(e.target);
      if (e.target === hoveredId) hoveredNeighbors.add(e.source);
    });
  }

  return (
    <div className="relative w-full h-full">
      {/* Toolbar */}
      <div className="absolute top-3 right-3 z-10 flex items-center gap-2">
        {running && (
          <span className="text-[11px] text-muted-foreground animate-pulse">
            Settling…
          </span>
        )}
        <button
          type="button"
          onClick={startSimulation}
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground bg-background/80 border rounded-md px-2 py-1 transition-colors"
          title="Re-run layout"
        >
          <RefreshCw className={cn("h-3 w-3", running && "animate-spin")} />
          Re-layout
        </button>
      </div>

      {/* Tag legend */}
      {tags.length > 0 && (
        <div className="absolute top-3 left-3 z-10 flex flex-wrap gap-1.5 max-w-[200px]">
          {tags.map((tag) => (
            <span
              key={tag.id}
              className="inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded-full border bg-background/80"
            >
              <span
                className="w-2 h-2 rounded-full"
                style={{ background: tag.color ?? FALLBACK_COLOR }}
              />
              {tag.name}
            </span>
          ))}
        </div>
      )}

      {/* SVG */}
      <svg
        ref={svgRef}
        width={w}
        height={h}
        className="w-full h-full"
        style={{ cursor: hoveredId ? "pointer" : "default" }}
      >
        {/* Edges */}
        <g>
          {renderEdges.map((e) => {
            const s = renderNodes.find((n) => n.id === e.source);
            const t = renderNodes.find((n) => n.id === e.target);
            if (!s || !t) return null;
            const isHighlighted =
              hoveredId && (e.source === hoveredId || e.target === hoveredId);
            return (
              <line
                key={`${e.source}-${e.target}`}
                x1={s.x} y1={s.y}
                x2={t.x} y2={t.y}
                stroke={isHighlighted ? "var(--primary)" : "var(--border)"}
                strokeWidth={isHighlighted ? 2 : 1}
                strokeOpacity={hoveredId && !isHighlighted ? 0.2 : 0.6}
                style={{ transition: "stroke-opacity 0.15s, stroke-width 0.15s" }}
              />
            );
          })}
        </g>

        {/* Nodes */}
        <g>
          {renderNodes.map((n) => {
            const r = nodeRadius(n);
            const isSelected  = n.id === selectedId;
            const isHovered   = n.id === hoveredId;
            const isNeighbor  = hoveredNeighbors.has(n.id);
            const isDimmed    = !!hoveredId && !isHovered && !isNeighbor;
            const showLabel   = isHovered || isSelected || isNeighbor || renderNodes.length <= 6;

            return (
              <g
                key={n.id}
                transform={`translate(${n.x},${n.y})`}
                onMouseEnter={() => setHoveredId(n.id)}
                onMouseLeave={() => setHoveredId(null)}
                onClick={() => onSelect(n.id)}
                style={{ cursor: "pointer" }}
              >
                {/* Outer ring for selected */}
                {isSelected && (
                  <circle
                    r={r + 5}
                    fill="none"
                    stroke="var(--primary)"
                    strokeWidth={2}
                    opacity={0.6}
                  />
                )}

                {/* Node circle */}
                <circle
                  r={r}
                  fill={n.color}
                  fillOpacity={isDimmed ? 0.2 : 0.85}
                  stroke={isHovered || isSelected ? "var(--primary)" : "var(--background)"}
                  strokeWidth={isHovered || isSelected ? 2 : 1.5}
                  style={{ transition: "fill-opacity 0.15s, r 0.1s" }}
                />

                {/* Label */}
                {showLabel && (
                  <text
                    y={r + 13}
                    textAnchor="middle"
                    fontSize={11}
                    fill="var(--foreground)"
                    fillOpacity={isDimmed ? 0.3 : 1}
                    style={{
                      fontWeight: isHovered || isSelected ? 600 : 400,
                      pointerEvents: "none",
                      userSelect: "none",
                    }}
                  >
                    {n.title.length > 22 ? n.title.slice(0, 20) + "…" : n.title}
                  </text>
                )}

                {/* Always show short label on all nodes (small) */}
                {!showLabel && (
                  <text
                    y={r + 12}
                    textAnchor="middle"
                    fontSize={10}
                    fill="var(--muted-foreground)"
                    fillOpacity={0.5}
                    style={{ pointerEvents: "none", userSelect: "none" }}
                  >
                    {n.title.length > 14 ? n.title.slice(0, 12) + "…" : n.title}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>

      {/* Empty state */}
      {!notesData?.items?.length && (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
          No notes to graph yet.
        </div>
      )}
    </div>
  );
}
