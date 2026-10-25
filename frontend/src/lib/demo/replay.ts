/**
 * Replay timing for recorded SSE streams: the original rhythm, with long waits capped and
 * the whole stream sped up (or gently slowed) to a watchable length.
 */

export interface ReplayTiming {
  /** No single wait between two events is longer than this (ms). */
  maxGapMs: number;
  /** A stream longer than this (after capping) is sped up to exactly this long (ms). */
  maxTotalMs: number;
  /** A stream shorter than this is slowed toward it (ms)... */
  minTotalMs: number;
  /** ...but never by more than this factor. */
  maxStretch: number;
}

/** A real answer (seconds of retrieval, then tokens) streams in about 8 to 15 s. */
export const DEFAULT_TIMING: ReplayTiming = {
  maxGapMs: 1500,
  maxTotalMs: 15_000,
  minTotalMs: 8_000,
  maxStretch: 3,
};

/** The timing replays use (tests speed it up). */
export const replayTiming: ReplayTiming = { ...DEFAULT_TIMING };

export function setReplayTiming(timing: Partial<ReplayTiming>): void {
  Object.assign(replayTiming, DEFAULT_TIMING, timing);
}

/**
 * The wait before each event (ms; the first is measured from the stream opening), given
 * when each one originally arrived. Order is kept: a clock that went backwards waits 0.
 */
export function replaySchedule(atMs: readonly number[], timing: ReplayTiming = DEFAULT_TIMING) {
  const gaps = atMs.map((at, i) => {
    const previous = i === 0 ? 0 : atMs[i - 1];
    const gap = Number.isFinite(at - previous) ? at - previous : 0;
    return Math.min(Math.max(0, gap), timing.maxGapMs);
  });
  const total = gaps.reduce((sum, gap) => sum + gap, 0);
  let scale = 1;
  if (total > timing.maxTotalMs) scale = timing.maxTotalMs / total;
  else if (total > 0 && total < timing.minTotalMs)
    scale = Math.min(timing.minTotalMs / total, timing.maxStretch);
  return gaps.map((gap) => gap * scale);
}

/** Resolves after `ms`, or as soon as `signal` aborts. */
export function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) return resolve();
    const timer = setTimeout(done, ms);
    function done(): void {
      clearTimeout(timer);
      signal.removeEventListener("abort", done);
      resolve();
    }
    signal.addEventListener("abort", done, { once: true });
  });
}
