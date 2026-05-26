"use client";

import { useEffect, useLayoutEffect, useRef, useState, useCallback, useMemo } from "react";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import { apiBaseUrl } from "@/lib/api/client";
import { getAccessToken } from "@/lib/auth/token";
import { cn } from "@/lib/utils";
import { RefreshCw, Loader2 } from "lucide-react";
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
  isGhost: boolean; // true = unresolved wikilink target with no real note yet
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

// Prefix used for ghost node IDs so they can be distinguished from real note IDs
const GHOST_PREFIX = "ghost::";

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

// ── Colors ─────────────────────────────────────────────────────────────────────

const FALLBACK_COLOR = "#94a3b8";
const GHOST_COLOR    = "#cbd5e1"; // lighter slate — visually distinct from real nodes

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
  // Ghost node being created right now (its graph ID, e.g. "ghost::title")
  const [creatingGhostId, setCreatingGhostId] = useState<string | null>(null);
  const qc = useQueryClient();

  // Simulation gravity centre — updated on resize without restarting the sim.
  // The loop reads this ref directly so it always uses the current canvas centre.
  const simCenter = useRef({ cx: 400, cy: 300 });
  // Debounce timer for ResizeObserver — prevents rapid dimension changes from
  // repeatedly calling startSimulation (which resets node positions each time).
  const resizeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Data fetching ────────────────────────────────────────────────────────────

  // Always fetch all notes across every collection so wikilinks are resolved globally.
  const { data: notesData } = $api.useQuery("get", "/notes", {
    params: { query: { limit: 500, include_all_collections: true } },
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

  // Stable primitive key — only changes when actual tag/note assignment data changes.
  // useQueries returns a new array reference every render, so depending on tagNoteQueries
  // directly would recompute the memo (and fire the color-patch effect) on every render,
  // causing an infinite setState loop.
  const colorDataKey = tagNoteQueries
    .map((q, i) => `${tags[i]?.id ?? ""}:${tags[i]?.color ?? ""}:${(q.data?.noteIds ?? []).join(",")}`)
    .join("|");

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [colorDataKey]);

  // Keep a ref so startSimulation (a callback) always reads the latest value
  const nodeColorMapRef = useRef(nodeColorMap);
  useLayoutEffect(() => {
    nodeColorMapRef.current = nodeColorMap;
  }, [nodeColorMap]);

  // Whenever the color map updates, patch both simNodes and renderNodes so the
  // animation loop (which spreads simNodes) picks up the correct colors too.
  // Ghost nodes are never in the color map so they keep GHOST_COLOR.
  useEffect(() => {
    if (!simNodes.current.length) return;
    simNodes.current.forEach((n) => {
      if (!n.isGhost) n.color = nodeColorMapRef.current.get(n.id) ?? FALLBACK_COLOR;
    });
    setRenderNodes((prev) =>
      prev.map((n) =>
        n.isGhost ? n : { ...n, color: nodeColorMapRef.current.get(n.id) ?? FALLBACK_COLOR }
      )
    );
  }, [nodeColorMap]);

  // ── Container dimensions ──────────────────────────────────────────────────

  useEffect(() => {
    const el = svgRef.current?.parentElement;
    if (!el) return;
    const obs = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      if (width <= 0 || height <= 0) return;
      // Always update the gravity centre immediately so any running simulation
      // stays centred without restarting.
      simCenter.current = { cx: width / 2, cy: height / 2 };
      // Debounce the SVG size state update — it's only needed for correct SVG
      // dimensions and does NOT restart the simulation (dimensions is no longer
      // in the auto-start effect dep array).
      if (resizeTimer.current) clearTimeout(resizeTimer.current);
      resizeTimer.current = setTimeout(() => {
        setDimensions({ w: width, h: height });
      }, 150);
    });
    obs.observe(el);
    return () => {
      obs.disconnect();
      if (resizeTimer.current) clearTimeout(resizeTimer.current);
    };
  }, []);

  // ── Build and run simulation when data changes ───────────────────────────

  const startSimulation = useCallback(() => {
    if (!notesData?.items?.length) return;

    const notes = notesData.items;
    const titleToId = new Map(notes.map((n) => [n.title.toLowerCase(), n.id]));

    // Build edges, collecting both resolved targets and ghost (unresolved) targets.
    const edges: GraphEdge[] = [];
    const edgeSet = new Set<string>();
    // ghost title (lowercase) → ghost node ID
    const ghostNodes = new Map<string, GraphNode>();

    for (const note of notes) {
      const targets = parseWikilinks(note.content_md);
      for (const t of targets) {
        const tLower = t.toLowerCase();
        const targetId = titleToId.get(tLower);

        if (targetId && targetId !== note.id) {
          // Resolved → real edge between two existing notes
          const key = [note.id, targetId].sort().join(":");
          if (!edgeSet.has(key)) {
            edgeSet.add(key);
            edges.push({ source: note.id, target: targetId });
          }
        } else if (!targetId) {
          // Unresolved → create / reuse a ghost node for this title
          const ghostId = `${GHOST_PREFIX}${tLower}`;
          if (!ghostNodes.has(tLower)) {
            ghostNodes.set(tLower, {
              id: ghostId,
              title: t, // preserve original casing for display
              x: 0, y: 0, vx: 0, vy: 0,
              degree: 0,
              color: GHOST_COLOR,
              isGhost: true,
            });
          }
          // Edge from the real note to the ghost node
          const key = [note.id, ghostId].sort().join(":");
          if (!edgeSet.has(key)) {
            edgeSet.add(key);
            edges.push({ source: note.id, target: ghostId });
          }
        }
      }
    }

    // Compute degree (real + ghost nodes participate equally)
    const degree = new Map<string, number>();
    for (const e of edges) {
      degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
      degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
    }

    const { w, h } = dimensions;
    // Sync simCenter ref with current canvas size so the loop always has the
    // right gravity centre even if a resize fires mid-simulation.
    simCenter.current = { cx: w / 2, cy: h / 2 };

    const realNodes: GraphNode[] = notes.map((n) => ({
      id:      n.id,
      title:   n.title,
      x: 0, y: 0, vx: 0, vy: 0,
      degree:  degree.get(n.id) ?? 0,
      color:   nodeColorMapRef.current.get(n.id) ?? FALLBACK_COLOR,
      isGhost: false,
    }));

    // Apply computed degrees to ghost nodes
    for (const gn of ghostNodes.values()) {
      gn.degree = degree.get(gn.id) ?? 0;
    }

    const allNodes: GraphNode[] = [...realNodes, ...ghostNodes.values()];

    initPositions(allNodes, simCenter.current.cx, simCenter.current.cy, Math.min(w, h) * 0.32);
    simNodes.current = allNodes;
    simEdges.current = edges;

    if (animFrame.current) cancelAnimationFrame(animFrame.current);
    setRunning(true);

    let tick = 0;
    function loop() {
      // Read simCenter each tick so gravity follows resize without restarting.
      const { cx, cy } = simCenter.current;
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

  // Auto-start when note data is ready or changes.
  // Intentionally excludes `dimensions` — resize is handled by updating
  // simCenter.current in the ResizeObserver, which shifts gravity without
  // restarting the simulation (and resetting node positions).
  useEffect(() => {
    if (notesData?.items?.length) startSimulation();
    return () => {
      if (animFrame.current) cancelAnimationFrame(animFrame.current);
    };
  }, [notesData]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Render ─────────────────────────────────────────────────────────────────

  const { w, h } = dimensions;
  const nodeRadius = (n: GraphNode) => Math.max(10, Math.min(22, 10 + n.degree * 2.5));

  const hoveredNeighbors = new Set<string>();
  if (hoveredId) {
    renderEdges.forEach((e) => {
      if (e.source === hoveredId) hoveredNeighbors.add(e.target);
      if (e.target === hoveredId) hoveredNeighbors.add(e.source);
    });
  }

  // Count ghost nodes for the legend hint
  const ghostCount = renderNodes.filter((n) => n.isGhost).length;

  // Only show tags that actually color at least one node in this graph.
  // Without this filter, tags from other domains (e.g. recipe tags) would
  // appear in the legend even though no notes carry them.
  const noteIdsInGraph = new Set((notesData?.items ?? []).map((n) => n.id));
  const visibleTags = tags.filter((_, i) =>
    (tagNoteQueries[i]?.data?.noteIds ?? []).some((id) => noteIdsInGraph.has(id))
  );

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

      {/* Tag legend + ghost hint */}
      <div className="absolute top-3 left-3 z-10 flex flex-col gap-1.5">
        {visibleTags.length > 0 && (
          <div className="flex flex-wrap gap-1.5 max-w-[200px]">
            {visibleTags.map((tag) => (
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
        {ghostCount > 0 && (
          <span className="inline-flex items-center gap-1.5 text-[11px] px-1.5 py-0.5 rounded-full border bg-background/80 text-muted-foreground max-w-fit">
            <svg width="10" height="10" viewBox="0 0 10 10">
              <circle cx="5" cy="5" r="4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="2.5 1.5" />
            </svg>
            {ghostCount} unwritten {ghostCount === 1 ? "idea" : "ideas"} — click to create
          </span>
        )}
      </div>

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
            const isGhostEdge = s.isGhost || t.isGhost;
            return (
              <line
                key={`${e.source}-${e.target}`}
                x1={s.x} y1={s.y}
                x2={t.x} y2={t.y}
                stroke={isHighlighted ? "var(--primary)" : "var(--border)"}
                strokeWidth={isHighlighted ? 2 : 1}
                strokeOpacity={hoveredId && !isHighlighted ? 0.15 : isGhostEdge ? 0.4 : 0.6}
                strokeDasharray={isGhostEdge ? "4 3" : undefined}
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
                onClick={async () => {
                  if (n.isGhost) {
                    if (creatingGhostId) return; // already creating
                    setCreatingGhostId(n.id);
                    try {
                      const token = getAccessToken();
                      const res = await fetch(`${apiBaseUrl}/notes`, {
                        method: "POST",
                        headers: {
                          "Content-Type": "application/json",
                          ...(token ? { Authorization: `Bearer ${token}` } : {}),
                        },
                        // No collection_id — ghost notes always live in global Notes
                        body: JSON.stringify({ title: n.title }),
                      });
                      if (res.ok) {
                        const created = await res.json() as { id: string };
                        // Refresh graph data so the new node becomes real
                        await qc.invalidateQueries({ queryKey: ["get", "/notes"] });
                        onSelect(created.id);
                      }
                    } catch {
                      // silently ignore — graph will retain the ghost node
                    } finally {
                      setCreatingGhostId(null);
                    }
                  } else {
                    onSelect(n.id);
                  }
                }}
                style={{ cursor: "pointer" }}
              >
                {/* Outer ring for selected real nodes */}
                {isSelected && !n.isGhost && (
                  <circle
                    r={r + 5}
                    fill="none"
                    stroke="var(--primary)"
                    strokeWidth={2}
                    opacity={0.6}
                  />
                )}

                {n.isGhost ? (
                  /* Ghost node — dashed ring, no fill, lighter treatment */
                  <>
                    <circle
                      r={r}
                      fill="var(--background)"
                      fillOpacity={isDimmed ? 0.3 : 0.7}
                      stroke={
                        creatingGhostId === n.id
                          ? "var(--primary)"
                          : isHovered
                          ? "var(--primary)"
                          : GHOST_COLOR
                      }
                      strokeWidth={isHovered || creatingGhostId === n.id ? 2 : 1.5}
                      strokeDasharray={creatingGhostId === n.id ? undefined : "4 2.5"}
                      style={{ transition: "fill-opacity 0.15s, stroke 0.15s" }}
                    />
                    {/* Click hint / loading indicator */}
                    {(isHovered || creatingGhostId === n.id) && (
                      <text
                        textAnchor="middle"
                        dominantBaseline="central"
                        fontSize={r * 0.85}
                        fill="var(--primary)"
                        fillOpacity={0.85}
                        style={{ pointerEvents: "none", userSelect: "none" }}
                      >
                        {creatingGhostId === n.id ? "…" : "+"}
                      </text>
                    )}
                  </>
                ) : (
                  /* Real node */
                  <circle
                    r={r}
                    fill={n.color}
                    fillOpacity={isDimmed ? 0.2 : 0.85}
                    stroke={isHovered || isSelected ? "var(--primary)" : "var(--background)"}
                    strokeWidth={isHovered || isSelected ? 2 : 1.5}
                    style={{ transition: "fill-opacity 0.15s, r 0.1s" }}
                  />
                )}

                {/* Label */}
                {showLabel && (
                  <text
                    y={r + 13}
                    textAnchor="middle"
                    fontSize={11}
                    fill={n.isGhost ? "var(--muted-foreground)" : "var(--foreground)"}
                    fillOpacity={isDimmed ? 0.3 : n.isGhost ? 0.7 : 1}
                    style={{
                      fontWeight: isHovered || isSelected ? 600 : 400,
                      pointerEvents: "none",
                      userSelect: "none",
                      fontStyle: n.isGhost ? "italic" : "normal",
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
                    fillOpacity={n.isGhost ? 0.35 : 0.5}
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
