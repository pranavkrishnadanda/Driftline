import { describe, expect, it } from "vitest";

import { layoutTimeline, nearestVersionIndex } from "@/lib/timeline/layout";

import { version } from "../support/version-timeline-fixtures";

const NOW = new Date("2026-02-10T00:00:00Z");

describe("layoutTimeline", () => {
  it("places versions proportionally to their valid_from on the axis", () => {
    const layout = layoutTimeline(
      [
        version(1, "2026-01-01T00:00:00Z", "2026-01-11T00:00:00Z"),
        version(2, "2026-01-11T00:00:00Z", "2026-01-31T00:00:00Z"),
        version(3, "2026-01-31T00:00:00Z", "2026-02-10T00:00:00Z"),
      ],
      400,
      { now: NOW },
    );
    // 40 days over 400 units: 10 units per day.
    expect(layout.items.map((i) => [i.versionNo, i.x, i.x2])).toEqual([
      [1, 0, 100],
      [2, 100, 300],
      [3, 300, 400],
    ]);
    expect(layout.items.every((i) => !i.openEnded)).toBe(true);
    expect(layout.start.toISOString()).toBe("2026-01-01T00:00:00.000Z");
    expect(layout.end.toISOString()).toBe("2026-02-10T00:00:00.000Z");
  });

  it("runs the open-ended current version to the right edge at now", () => {
    const layout = layoutTimeline(
      [
        version(1, "2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z"),
        version(2, "2026-01-31T00:00:00Z", null),
      ],
      400,
      { now: NOW },
    );
    expect(layout.items.map((i) => [i.x, i.x2, i.openEnded])).toEqual([
      [0, 300, false],
      [300, 400, true],
    ]);
    expect(layout.end.toISOString()).toBe(NOW.toISOString());
  });

  it("keeps a visible open-ended segment when the current version starts after now", () => {
    const layout = layoutTimeline(
      [
        version(1, "2026-01-01T00:00:00Z", "2026-03-01T00:00:00Z"),
        version(2, "2026-03-01T00:00:00Z", null),
      ],
      400,
      { now: NOW, minGap: 16 },
    );
    const current = layout.items[1];
    expect(current.openEnded).toBe(true);
    expect(current.x2).toBe(400);
    expect(current.x2 - current.x).toBeGreaterThanOrEqual(16);
  });

  it("spans the whole axis with a single version", () => {
    const layout = layoutTimeline([version(1, "2026-01-01T00:00:00Z", null)], 400, { now: NOW });
    expect(layout.items).toHaveLength(1);
    expect(layout.items[0]).toMatchObject({ x: 0, x2: 400, openEnded: true, versionNo: 1 });
  });

  it("spans the axis with a single version that starts exactly now", () => {
    const layout = layoutTimeline([version(1, "2026-02-10T00:00:00Z", null)], 400, { now: NOW });
    expect(layout.items[0]).toMatchObject({ x: 0, x2: 400, openEnded: true });
  });

  it("separates versions that start on the same day by at least minGap", () => {
    const layout = layoutTimeline(
      [
        version(1, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00.001Z"),
        version(2, "2026-01-01T00:00:00.001Z", "2026-01-01T09:00:00Z"),
        version(3, "2026-01-01T09:00:00Z", null),
      ],
      400,
      { now: NOW, minGap: 16 },
    );
    const xs = layout.items.map((i) => i.x);
    expect(xs[0]).toBe(0);
    expect(xs[1] - xs[0]).toBeGreaterThanOrEqual(16);
    expect(xs[2] - xs[1]).toBeGreaterThanOrEqual(16);
    // Each segment ends where the next begins, and the current one reaches the edge.
    expect(layout.items[0].x2).toBe(xs[1]);
    expect(layout.items[1].x2).toBe(xs[2]);
    expect(layout.items[2].x2).toBe(400);
  });

  it("pulls crowded versions back inside the axis instead of overflowing it", () => {
    const layout = layoutTimeline(
      [
        version(1, "2026-01-01T00:00:00Z", "2026-02-09T23:00:00Z"),
        version(2, "2026-02-09T23:00:00Z", "2026-02-09T23:30:00Z"),
        version(3, "2026-02-09T23:30:00Z", null),
      ],
      400,
      { now: NOW, minGap: 16 },
    );
    const xs = layout.items.map((i) => i.x);
    expect(xs[2]).toBeLessThanOrEqual(400 - 16);
    expect(xs[2] - xs[1]).toBeGreaterThanOrEqual(16);
    expect(xs[1] - xs[0]).toBeGreaterThanOrEqual(16);
  });

  it("sorts versions by valid_from and returns nothing for no versions", () => {
    const layout = layoutTimeline(
      [
        version(2, "2026-01-21T00:00:00Z", null),
        version(1, "2026-01-01T00:00:00Z", "2026-01-21T00:00:00Z"),
      ],
      400,
      { now: NOW },
    );
    expect(layout.items.map((i) => i.versionNo)).toEqual([1, 2]);
    expect(layoutTimeline([], 400, { now: NOW }).items).toEqual([]);
  });
});

describe("nearestVersionIndex", () => {
  const layout = layoutTimeline(
    [
      version(1, "2026-01-01T00:00:00Z", "2026-01-11T00:00:00Z"),
      version(2, "2026-01-11T00:00:00Z", "2026-01-31T00:00:00Z"),
      version(3, "2026-01-31T00:00:00Z", null),
    ],
    400,
    { now: NOW },
  );

  it("picks the version whose segment contains the position", () => {
    expect(nearestVersionIndex(layout, 0)).toBe(0);
    expect(nearestVersionIndex(layout, 99)).toBe(0);
    expect(nearestVersionIndex(layout, 100)).toBe(1);
    expect(nearestVersionIndex(layout, 299)).toBe(1);
    expect(nearestVersionIndex(layout, 350)).toBe(2);
  });

  it("clamps positions outside the axis", () => {
    expect(nearestVersionIndex(layout, -50)).toBe(0);
    expect(nearestVersionIndex(layout, 9999)).toBe(2);
  });
});
