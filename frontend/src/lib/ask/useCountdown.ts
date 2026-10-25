"use client";

import { useEffect, useState } from "react";

import { secondsLeft } from "./format";

export interface Deadline {
  /** When the wait started (ms epoch). */
  start: number;
  /** When it ends (ms epoch). */
  until: number;
}

/** Whole seconds left until `deadline.until`, re-rendering as it counts down; 0 when null. */
export function useCountdown(deadline: Deadline | null, tickMs = 250): number {
  // No clock read during render (it breaks prerendering): until the first tick, the
  // deadline's own start stands in for "now" below.
  const [now, setNow] = useState(0);
  const until = deadline?.until ?? null;

  useEffect(() => {
    if (until === null) return;
    const timer = setInterval(() => {
      const at = Date.now();
      setNow(at);
      if (at >= until) clearInterval(timer);
    }, tickMs);
    return () => clearInterval(timer);
  }, [until, tickMs]);

  if (!deadline) return 0;
  // `now` may predate this deadline until the first tick.
  return secondsLeft(deadline.until, Math.max(now, deadline.start));
}
