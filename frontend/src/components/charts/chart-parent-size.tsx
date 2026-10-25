"use client";

import { useParentSize } from "@visx/responsive";
import { type CSSProperties, type ReactNode, useState } from "react";

export interface ChartParentSizeProps {
  children: (size: { width: number; height: number }) => ReactNode;
  className?: string;
  debounceTime?: number;
  style?: CSSProperties;
}

/** Below this, a measurement is a layout blip, not a real size (charts need 10 px). */
const MIN_SIZE = 10;

/**
 * Drop-in for visx `<ParentSize>` without its `overflow: hidden` measuring
 * layer, so tooltips, markers, and strokes at the chart edge aren't clipped.
 *
 * Driftline: once the parent has been measured, a momentary 0×0 reading is ignored
 * and the last real size kept. Browsers report one while they re-lay out the page (a
 * full-page capture, a resize, print preview); passing it on made every chart return
 * `null`, unmount, and replay its grow-from-zero entrance, so the page showed empty
 * chart boxes.
 */
export function ParentSize({ children, className, debounceTime, style }: ChartParentSizeProps) {
  const { parentRef, width, height } = useParentSize({ debounceTime });
  const [lastGood, setLastGood] = useState<{ width: number; height: number } | null>(null);
  const measured = width >= MIN_SIZE && height >= MIN_SIZE;
  if (measured && (lastGood?.width !== width || lastGood?.height !== height)) {
    setLastGood({ width, height });
  }
  const size = measured ? { width, height } : (lastGood ?? { width, height });
  return (
    <div
      className={className}
      style={{ position: "relative", width: "100%", height: "100%", ...style }}
    >
      <div ref={parentRef} style={{ position: "absolute", inset: 0 }}>
        {children(size)}
      </div>
    </div>
  );
}
