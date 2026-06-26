"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ComponentType,
  type RefObject,
} from "react";
import dynamic from "next/dynamic";
import { forceCollide, forceX, forceY } from "d3-force-3d";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { FileText, StickyNote, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTranslation } from "@/lib/hooks/use-translation";
import {
  BG,
  MIN_HEIGHT,
  withAlpha,
  type GLink,
  type GNode,
  type LegendTopic,
} from "./graph-utils";

// Minimal prop surface we actually use from react-force-graph-2d. The library
// ships broad types; we narrow to our node/link shapes for type-safety.
interface ForceGraphProps {
  graphData: { nodes: GNode[]; links: GLink[] };
  width?: number;
  height?: number;
  nodeId?: string;
  nodeRelSize?: number;
  nodeVal?: (n: GNode) => number;
  linkWidth?: (l: GLink) => number;
  linkColor?: (l: GLink) => string;
  linkCurvature?: number;
  backgroundColor?: string;
  cooldownTicks?: number;
  warmupTicks?: number;
  onEngineStop?: () => void;
  onNodeClick?: (n: GNode) => void;
  onBackgroundClick?: () => void;
  onRenderFramePre?: (ctx: CanvasRenderingContext2D, scale: number) => void;
  autoPauseRedraw?: boolean;
  nodeCanvasObjectMode?: () => string;
  nodeCanvasObject?: (
    node: GNode & { x: number; y: number },
    ctx: CanvasRenderingContext2D,
    scale: number,
  ) => void;
  innerRef?: RefObject<ForceGraphInstance | null>;
}

// Imperative methods we drive on the live graph (force tuning + framing).
interface D3Force {
  strength?: (s: number) => D3Force;
  distance?: (d: number) => D3Force;
  distanceMax?: (d: number) => D3Force;
}
interface ForceGraphInstance {
  d3Force(name: string): D3Force | undefined;
  d3Force(name: string, force: unknown): unknown;
  d3ReheatSimulation(): void;
  zoomToFit(ms?: number, padding?: number): void;
}

// react-force-graph-2d touches `window`; load the client wrapper only on the
// client. The wrapper forwards our ref via the `innerRef` prop.
const ForceGraph2D = dynamic(() => import("./ForceGraphClient"), {
  ssr: false,
}) as unknown as ComponentType<ForceGraphProps>;

interface GraphCanvasProps {
  /** Memoised by the caller so the simulation isn't reset every render. */
  graphData: { nodes: GNode[]; links: GLink[] };
  legend: LegendTopic[];
  /** Change this to re-run the force layout + re-frame (e.g. data/mode). */
  reheatKey: string;
  /** Bipartite ≈ 50, similarity ≈ 90. */
  linkDistance: number;
  legendTitle?: string;
  className?: string;
}

/**
 * Presentational force-directed canvas shared by the documents and notes
 * visualizations. Owns the d3 force tuning, the cluster bubbles, node/label
 * painting, the selected-node overlay, and the collapsible legend. It is
 * agnostic about where nodes/links come from — callers build them.
 */
export function GraphCanvas({
  graphData,
  legend,
  reheatKey,
  linkDistance,
  legendTitle,
  className,
}: GraphCanvasProps) {
  const { t } = useTranslation();
  const [legendOpen, setLegendOpen] = useState(false);
  const [selected, setSelected] = useState<GNode | null>(null);

  const fgRef = useRef<ForceGraphInstance | null>(null);
  // Re-frame the view once after each layout settles for a new graph/mode.
  const shouldZoom = useRef(true);

  // Measure the canvas container so the graph fills the available space. The
  // ref mirror lets the force tuning read the latest aspect ratio without
  // re-running (and thus re-heating) the layout on every resize.
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 360, h: MIN_HEIGHT });
  const sizeRef = useRef(size);
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => {
      const next = {
        w: el.clientWidth,
        h: Math.max(MIN_HEIGHT, el.clientHeight),
      };
      sizeRef.current = next;
      setSize(next);
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Tune the d3 simulation: per-cluster positional forces pull each topic (and
  // its members) into a distinct region, a real collision force stops nodes
  // overlapping, and weak links keep cross-cluster edges from dragging members
  // back toward the centre.
  const applyForces = useCallback((): boolean => {
    const fg = fgRef.current;
    if (!fg) return false;
    // The ref can attach a frame before react-force-graph has built its
    // internal simulation, and the lazily code-split chunk may take many frames
    // to download on a cold first open. If the named forces aren't there yet,
    // report "not ready" so the caller keeps retrying — otherwise the custom
    // clustering/collision forces never apply and every node piles onto its
    // topic hub until a remount (e.g. switching tabs) reapplies them.
    const charge = fg.d3Force("charge");
    if (!charge) return false;
    // Stretch the cluster anchors horizontally on wide canvases so the layout
    // fills the window instead of settling into a circle with empty corners.
    const { w, h } = sizeRef.current;
    const xSpread = Math.min(1.7, Math.max(1, h > 0 ? w / h : 1));
    charge.strength?.(-260);
    charge.distanceMax?.(1200);
    const link = fg.d3Force("link");
    link?.distance?.(linkDistance);
    link?.strength?.(0.05);
    fg.d3Force(
      "x",
      forceX<GNode>((n) => n.ax * xSpread).strength((n) =>
        n.kind === "topic" ? 0.5 : 0.12,
      ),
    );
    fg.d3Force(
      "y",
      forceY<GNode>((n) => n.ay).strength((n) =>
        n.kind === "topic" ? 0.5 : 0.12,
      ),
    );
    fg.d3Force(
      "collide",
      forceCollide<GNode>(
        (n) => Math.max(3, n.val) + (n.kind === "topic" ? 22 : 12),
      )
        .strength(0.9)
        .iterations(2),
    );
    // Arm the one-shot re-frame for the settle this reheat kicks off. Done here
    // (rather than when the retry was scheduled) so a premature engine stop
    // during a slow cold load can't consume the zoom before our forces land.
    shouldZoom.current = true;
    fg.d3ReheatSimulation();
    return true;
  }, [linkDistance]);

  // Re-tune forces and re-frame only when `reheatKey` changes — NOT when the
  // similarity threshold moves (that just adds/removes links).
  useEffect(() => {
    // `reheatKey` re-runs this effect (data/mode change). Retry until the
    // lazily-loaded force-graph instance has attached AND built its simulation,
    // bounded by a wall-clock deadline rather than a fixed frame budget: a cold
    // first open (chunk still downloading) used to blow past the old 30-frame
    // cap before the ref went live, leaving the layout un-forced — every node
    // stacked on its topic hub until a remount.
    void reheatKey;
    let raf = 0;
    const start = performance.now();
    const tick = () => {
      if (applyForces() || performance.now() - start > 15000) return;
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, [reheatKey, applyForces]);

  // Paint a soft, topic-coloured bubble behind each cluster so the regions read
  // as distinct groups (spatially AND by colour) even at a glance.
  const drawClusterBubbles = useCallback(
    (ctx: CanvasRenderingContext2D, scale: number) => {
      const groups = new Map<
        string,
        { color: string; pts: [number, number][] }
      >();
      for (const n of graphData.nodes) {
        if (n.x == null || n.y == null) continue;
        const g = groups.get(n.clusterId) ?? { color: n.color, pts: [] };
        g.pts.push([n.x, n.y]);
        groups.set(n.clusterId, g);
      }
      for (const g of groups.values()) {
        const cx = g.pts.reduce((s, p) => s + p[0], 0) / g.pts.length;
        const cy = g.pts.reduce((s, p) => s + p[1], 0) / g.pts.length;
        let maxR = 0;
        for (const [x, y] of g.pts) {
          maxR = Math.max(maxR, Math.hypot(x - cx, y - cy));
        }
        const r = maxR + 26;
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, 2 * Math.PI);
        ctx.fillStyle = withAlpha(g.color, 0.1);
        ctx.fill();
        ctx.lineWidth = 1.5 / scale;
        ctx.strokeStyle = withAlpha(g.color, 0.3);
        ctx.stroke();
      }
    },
    [graphData],
  );

  return (
    <div className={cn("flex flex-col gap-2 min-h-0", className)}>
      {/* Canvas — fills remaining space; selected-node detail floats over it. */}
      <div
        ref={containerRef}
        className="relative flex-1 min-h-0 rounded-lg border bg-muted/20 overflow-hidden"
      >
        <ForceGraph2D
          innerRef={fgRef}
          graphData={graphData}
          width={size.w}
          height={size.h}
          backgroundColor={BG}
          nodeId="id"
          nodeRelSize={4}
          nodeVal={(n: GNode) => n.val}
          linkWidth={(l: GLink) => l.width}
          linkColor={(l: GLink) => l.color}
          linkCurvature={0.12}
          warmupTicks={40}
          cooldownTicks={160}
          // Keep painting after the layout cools. force-graph's default
          // `autoPauseRedraw` freezes the canvas once the engine stops, which
          // means visual-only changes that don't move nodes (toggling labels,
          // the selection ring) never show up. The simulation still stops; only
          // the (cheap) canvas repaint keeps ticking.
          autoPauseRedraw={false}
          onRenderFramePre={drawClusterBubbles}
          onEngineStop={() => {
            if (shouldZoom.current) {
              // Larger padding = zoom out a bit on open, so the whole graph has
              // breathing room instead of filling the canvas edge-to-edge.
              fgRef.current?.zoomToFit(500, 90);
              shouldZoom.current = false;
            }
          }}
          onNodeClick={(n: GNode) => setSelected(n)}
          onBackgroundClick={() => setSelected(null)}
          nodeCanvasObjectMode={() => "replace"}
          nodeCanvasObject={(
            node: GNode & { x: number; y: number },
            ctx: CanvasRenderingContext2D,
            scale: number,
          ) => {
            const r = Math.max(3, node.val);
            const isTopic = node.kind === "topic";
            const isSel = selected?.id === node.id;
            // Node disc.
            ctx.beginPath();
            ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
            ctx.fillStyle = node.color;
            ctx.fill();
            // Thin white ring on every node for separation; dark when selected.
            ctx.lineWidth = (isSel ? 2.5 : 1) / scale;
            ctx.strokeStyle = isSel ? "#0f172a" : "rgba(255,255,255,0.92)";
            ctx.stroke();

            // Labels: topics + selected always; members when large or zoomed
            // in. White halo keeps them legible over edges.
            const showThis =
              isTopic || isSel || node.val > 9 || scale > 1.6;
            if (!showThis) return;
            const fontSize = Math.max((isTopic ? 11 : 9.5) / scale, 2.5);
            ctx.font = `${isTopic ? 600 : 500} ${fontSize}px Inter, ui-sans-serif, system-ui, sans-serif`;
            ctx.textAlign = "center";
            ctx.textBaseline = "top";
            const max = isTopic ? 26 : 22;
            const label =
              node.label.length > max
                ? `${node.label.slice(0, max - 1)}…`
                : node.label;
            const ly = node.y + r + 1.5 / scale;
            ctx.lineWidth = 3 / scale;
            ctx.strokeStyle = "rgba(248,250,252,0.92)";
            ctx.strokeText(label, node.x, ly);
            ctx.fillStyle = isTopic ? "#0f172a" : "#334155";
            ctx.fillText(label, node.x, ly);
          }}
        />

        {/* Selected-node detail overlay */}
        {selected && (
          <div className="absolute bottom-2 left-2 right-2 max-w-xs rounded-lg border bg-background/95 backdrop-blur p-2 shadow-sm space-y-1">
            <div className="flex items-center gap-1.5 text-xs font-semibold">
              {selected.kind === "doc" ? (
                <FileText className="h-3.5 w-3.5 shrink-0" />
              ) : selected.kind === "note" ? (
                <StickyNote className="h-3.5 w-3.5 shrink-0" />
              ) : (
                <span
                  className="inline-block h-3 w-3 rounded-full shrink-0"
                  style={{ backgroundColor: selected.color }}
                />
              )}
              <span className="truncate" title={selected.label}>
                {selected.label}
              </span>
            </div>
            {selected.detailText && (
              <div className="text-[11px] text-muted-foreground">
                {selected.detailText}
              </div>
            )}
            {selected.detailRows && selected.detailRows.length > 0 && (
              <div className="space-y-0.5 max-h-24 overflow-y-auto">
                {selected.detailRows.map((row) => (
                  <div
                    key={row.label}
                    className="flex items-center justify-between text-[11px] text-muted-foreground"
                  >
                    <span className="truncate">{row.label}</span>
                    {row.value != null && (
                      <span className="tabular-nums">{row.value}</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Topic legend — collapsible to keep the canvas tall in narrow panels. */}
      <Collapsible open={legendOpen} onOpenChange={setLegendOpen}>
        <CollapsibleTrigger asChild>
          <button className="flex items-center gap-1.5 text-[11px] font-semibold text-muted-foreground hover:text-foreground transition-colors">
            <ChevronDown
              className={`h-3.5 w-3.5 transition-transform ${legendOpen ? "" : "-rotate-90"}`}
            />
            {legendTitle ?? t.navyDocs?.graphLegend ?? "Topics"} ({legend.length}
            )
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 pt-1 max-h-28 overflow-y-auto xl:grid-cols-3">
            {legend.map((tp) => (
              <div key={tp.id} className="flex items-center gap-1.5 text-[11px]">
                <span
                  className="inline-block h-2.5 w-2.5 rounded-full shrink-0"
                  style={{ backgroundColor: tp.color }}
                />
                <span className="truncate" title={tp.label}>
                  {tp.label}
                </span>
                {tp.count != null && (
                  <span className="ml-auto tabular-nums text-muted-foreground">
                    {tp.count}
                  </span>
                )}
              </div>
            ))}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}
