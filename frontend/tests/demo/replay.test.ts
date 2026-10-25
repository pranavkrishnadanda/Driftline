import { describe, expect, it } from "vitest";

import { DEFAULT_TIMING, replaySchedule } from "@/lib/demo/replay";

const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);

describe("replaySchedule", () => {
  it("keeps the original rhythm when it is already a watchable length", () => {
    expect(replaySchedule([2000, 4000, 5500, 7000, 8500, 10_000])).toEqual([
      1500, 1500, 1500, 1500, 1500, 1500,
    ]);
    expect(replaySchedule([1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000])).toEqual(
      Array(9).fill(1000),
    );
  });

  it("caps a long wait between two events", () => {
    const delays = replaySchedule([0, 60_000, 60_100], { ...DEFAULT_TIMING, minTotalMs: 0 });
    expect(delays).toEqual([0, 1500, 100]);
  });

  it("speeds a long answer up to the maximum length, in proportion", () => {
    // 40 s of tokens 100 ms apart.
    const at = Array.from({ length: 400 }, (_, i) => (i + 1) * 100);
    const delays = replaySchedule(at);
    expect(sum(delays)).toBeCloseTo(DEFAULT_TIMING.maxTotalMs);
    expect(new Set(delays.map((d) => d.toFixed(6))).size).toBe(1);
  });

  it("slows a short stream toward the minimum, at most maxStretch times", () => {
    expect(sum(replaySchedule([500, 1000]))).toBeCloseTo(3000);
    expect(sum(replaySchedule([2000, 4000]))).toBeCloseTo(DEFAULT_TIMING.minTotalMs);
  });

  it("never waits a negative time when the clock went backwards", () => {
    expect(replaySchedule([100, 50, 80], { ...DEFAULT_TIMING, minTotalMs: 0 })).toEqual([
      100, 0, 30,
    ]);
  });
});
