"use client";

/**
 * A React Flow edge whose stroke is drawn in by anime.js (`svg.createDrawable` plus a
 * `draw` tween). Under reduced motion the path is rendered fully drawn and anime.js
 * never touches it. Motion (motion.dev) is not used on these elements.
 */
import { EdgeLabelRenderer, getBezierPath, type EdgeProps } from "@xyflow/react";
import { animate, svg } from "animejs";
import { createContext, useContext, useLayoutEffect, useRef } from "react";

import type { DrawnEdge } from "@/lib/timeline/graph";
import { cn } from "@/lib/utils";

/** Whether edges should be drawn statically (reduced motion). */
export const StaticEdgesContext = createContext(true);

const DRAW_MS = 900;
const STAGGER_MS = 140;

export function DrawnEdgeView({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  label,
  markerEnd,
  data,
}: EdgeProps<DrawnEdge>) {
  const staticEdges = useContext(StaticEdgesContext);
  const pathRef = useRef<SVGPathElement>(null);
  const [path, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });
  const order = data?.order ?? 0;
  const pending = data?.status !== "accepted";

  useLayoutEffect(() => {
    const el = pathRef.current;
    if (staticEdges || !el || typeof el.getTotalLength !== "function") return;
    const drawing = animate(svg.createDrawable(el), {
      draw: ["0 0", "0 1"],
      duration: DRAW_MS,
      delay: 150 + order * STAGGER_MS,
      ease: "inOutQuad",
    });
    // Revert restores the plain, fully drawn path (no dash styles left behind).
    return () => {
      drawing.revert();
    };
  }, [staticEdges, order]);

  return (
    <>
      <path
        ref={pathRef}
        id={id}
        d={path}
        fill="none"
        markerEnd={markerEnd}
        // Not dashed for pending relations: the drawable owns stroke-dasharray.
        className={cn("react-flow__edge-path", pending && "opacity-50")}
        data-testid="drawn-edge"
      />
      {label ? (
        <EdgeLabelRenderer>
          <div
            className="nodrag nopan pointer-events-none absolute rounded-sm border border-border bg-background px-1.5 py-0.5 text-[11px] text-foreground"
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}
