"use client";

/**
 * The version time axis and its scrubber. anime.js owns the scrubber's motion: the
 * thumb and the progress bar are positioned only through `animate` / `utils.set`, never
 * by React props, so the two never fight over the same attribute. Motion (motion.dev)
 * is not used on any element here.
 */
import { animate, utils } from "animejs";
import {
  useCallback,
  useId,
  useLayoutEffect,
  useRef,
  type KeyboardEvent,
  type PointerEvent,
} from "react";

import { formatDay, versionValueText } from "@/lib/timeline/format";
import { nearestVersionIndex, type TimelineLayout } from "@/lib/timeline/layout";
import { cn } from "@/lib/utils";

/** Axis width in SVG user units; `layoutTimeline` is computed against it. */
export const AXIS_WIDTH = 1000;
const PAD = 12;
const VIEW_WIDTH = AXIS_WIDTH + 2 * PAD;
const HEIGHT = 48;
const TRACK_Y = 18;
const TRACK_H = 12;
const SCRUB_MS = 450;

export interface VersionAxisProps {
  layout: TimelineLayout;
  selectedIndex: number;
  onSelect: (index: number) => void;
  reducedMotion: boolean;
}

export function VersionAxis({ layout, selectedIndex, onSelect, reducedMotion }: VersionAxisProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const thumbRef = useRef<SVGGElement>(null);
  const progressRef = useRef<SVGRectElement>(null);
  const placed = useRef(false);
  const dragging = useRef(false);
  const gradientId = `${useId()}-open-end`;

  const items = layout.items;
  const selected = items[selectedIndex];
  const targetX = selected?.x ?? 0;

  /** Move the scrubber to `x`: tweened by anime.js, or set at once under reduced motion. */
  const moveTo = useCallback(
    (x: number, tween: boolean) => {
      const thumb = thumbRef.current;
      const progress = progressRef.current;
      if (!thumb || !progress) return;
      if (!tween || reducedMotion) {
        utils.set(thumb, { x });
        utils.set(progress, { width: x });
        return;
      }
      animate(thumb, { x, duration: SCRUB_MS, ease: "outQuint" });
      animate(progress, { width: x, duration: SCRUB_MS, ease: "outQuint" });
    },
    [reducedMotion],
  );

  useLayoutEffect(() => {
    if (dragging.current) return;
    // The first placement is never animated.
    moveTo(targetX, placed.current);
    placed.current = true;
  }, [targetX, moveTo]);

  useLayoutEffect(() => {
    const thumb = thumbRef.current;
    const progress = progressRef.current;
    return () => {
      if (thumb) utils.remove(thumb);
      if (progress) utils.remove(progress);
    };
  }, []);

  function pointerX(event: PointerEvent<SVGSVGElement>): number | null {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return null;
    const x = ((event.clientX - rect.left) / rect.width) * VIEW_WIDTH - PAD;
    return Math.min(AXIS_WIDTH, Math.max(0, x));
  }

  function scrub(event: PointerEvent<SVGSVGElement>) {
    const x = pointerX(event);
    if (x === null) return;
    // Direct manipulation: the thumb follows the pointer, and the version under it is selected.
    moveTo(x, false);
    const index = nearestVersionIndex(layout, x);
    if (index >= 0 && index !== selectedIndex) onSelect(index);
  }

  function onPointerDown(event: PointerEvent<SVGSVGElement>) {
    if (event.button !== 0) return;
    dragging.current = true;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    event.currentTarget.focus();
    scrub(event);
  }

  function onPointerMove(event: PointerEvent<SVGSVGElement>) {
    if (dragging.current) scrub(event);
  }

  function onPointerUp(event: PointerEvent<SVGSVGElement>) {
    if (!dragging.current) return;
    dragging.current = false;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    const x = pointerX(event);
    const index = x === null ? selectedIndex : nearestVersionIndex(layout, x);
    if (index !== selectedIndex && index >= 0) onSelect(index);
    // Snap onto the selected version's start.
    moveTo(items[index >= 0 ? index : selectedIndex]?.x ?? 0, true);
  }

  function onKeyDown(event: KeyboardEvent<SVGSVGElement>) {
    const last = items.length - 1;
    const next: Record<string, number> = {
      ArrowLeft: selectedIndex - 1,
      ArrowDown: selectedIndex - 1,
      PageDown: selectedIndex - 1,
      ArrowRight: selectedIndex + 1,
      ArrowUp: selectedIndex + 1,
      PageUp: selectedIndex + 1,
      Home: 0,
      End: last,
    };
    if (!(event.key in next)) return;
    event.preventDefault();
    const index = Math.min(last, Math.max(0, next[event.key]));
    if (index !== selectedIndex) onSelect(index);
  }

  const pct = (x: number) => `${((x + PAD) / VIEW_WIDTH) * 100}%`;

  return (
    <div className="flex flex-col gap-1">
      <div className="relative h-5 text-xs text-muted-foreground" aria-hidden="true">
        {items.map((item, i) => {
          const room = (items[i + 1]?.x ?? AXIS_WIDTH) - item.x;
          if (room < 28 && i !== selectedIndex) return null;
          return (
            <span
              key={item.versionId}
              className={cn(
                "absolute -translate-x-1/2 tabular-nums",
                i === selectedIndex && "font-semibold text-foreground",
              )}
              style={{ left: pct(item.x) }}
            >
              v{item.versionNo}
            </span>
          );
        })}
      </div>
      <svg
        ref={svgRef}
        role="slider"
        tabIndex={0}
        aria-label="Version"
        aria-orientation="horizontal"
        aria-valuemin={items[0]?.versionNo ?? 0}
        aria-valuemax={items[items.length - 1]?.versionNo ?? 0}
        aria-valuenow={selected?.versionNo ?? 0}
        aria-valuetext={selected ? versionValueText(selected) : undefined}
        viewBox={`${-PAD} 0 ${VIEW_WIDTH} ${HEIGHT}`}
        preserveAspectRatio="none"
        className="h-12 w-full cursor-pointer touch-none select-none rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onKeyDown={onKeyDown}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" x2="1" y1="0" y2="0">
            <stop offset="0%" stopColor="currentColor" stopOpacity="0.35" />
            <stop offset="100%" stopColor="currentColor" stopOpacity="0.05" />
          </linearGradient>
        </defs>
        <rect x={0} y={TRACK_Y} width={AXIS_WIDTH} height={TRACK_H} rx={3} className="fill-muted" />
        {items.map((item, i) => (
          <rect
            key={item.versionId}
            data-testid={`segment-v${item.versionNo}`}
            x={item.x}
            y={TRACK_Y}
            width={Math.max(0, item.x2 - item.x)}
            height={TRACK_H}
            className={cn(
              "text-primary",
              item.openEnded ? "" : i % 2 === 0 ? "fill-primary/25" : "fill-primary/15",
            )}
            fill={item.openEnded ? `url(#${gradientId})` : undefined}
          />
        ))}
        {/* anime.js sets this rect's width; React never re-renders the attribute. */}
        <rect
          ref={progressRef}
          data-testid="scrubber-progress"
          x={0}
          y={TRACK_Y + TRACK_H - 3}
          width={0}
          height={3}
          className="fill-primary"
        />
        {items.map((item) => (
          <line
            key={item.versionId}
            x1={item.x}
            x2={item.x}
            y1={TRACK_Y - 4}
            y2={TRACK_Y + TRACK_H + 4}
            vectorEffect="non-scaling-stroke"
            className="stroke-foreground/50"
            strokeWidth={1}
          />
        ))}
        {/* anime.js owns this group's transform. */}
        <g ref={thumbRef} data-testid="scrubber-thumb">
          <line
            x1={0}
            x2={0}
            y1={4}
            y2={HEIGHT - 4}
            vectorEffect="non-scaling-stroke"
            strokeWidth={3}
            strokeLinecap="round"
            className="stroke-primary"
          />
          <rect x={-5} y={2} width={10} height={10} rx={2} className="fill-primary" />
        </g>
      </svg>
      <div className="flex justify-between text-xs text-muted-foreground tabular-nums">
        <span>{formatDay(layout.start)}</span>
        <span>{items[items.length - 1]?.openEnded ? "now" : formatDay(layout.end)}</span>
      </div>
    </div>
  );
}
