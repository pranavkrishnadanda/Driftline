import { describe, expect, it } from "vitest";

import { diffToRows } from "@/lib/timeline/diff";

describe("diffToRows", () => {
  it("maps each section path to a before/after row, in path order", () => {
    const result = diffToRows({
      added: ["B > Renal"],
      removed: ["C > Old"],
      changed: ["A > Dose"],
      unchanged: ["A > Intro"],
    });
    expect(result.rows).toEqual([
      { path: "A > Dose", status: "changed", before: true, after: true },
      { path: "A > Intro", status: "unchanged", before: true, after: true },
      { path: "B > Renal", status: "added", before: false, after: true },
      { path: "C > Old", status: "removed", before: true, after: false },
    ]);
    expect(result.counts).toEqual({ added: 1, removed: 1, changed: 1, unchanged: 1 });
    expect(result.first).toBe(false);
    expect(result.adjusted).toBeNull();
  });

  it("marks the first version (no predecessor) instead of inventing rows", () => {
    const result = diffToRows(null);
    expect(result.first).toBe(true);
    expect(result.rows).toEqual([]);
    expect(result.counts).toEqual({ added: 0, removed: 0, changed: 0, unchanged: 0 });
  });

  it("reports a valid_from the store had to adjust", () => {
    const result = diffToRows({
      added: [],
      removed: [],
      changed: ["A"],
      unchanged: [],
      valid_from_adjusted: {
        requested: "2026-01-01T00:00:00+00:00",
        applied: "2026-01-01T00:00:00.001000+00:00",
      },
    });
    expect(result.adjusted).toEqual({
      requested: "2026-01-01T00:00:00+00:00",
      applied: "2026-01-01T00:00:00.001000+00:00",
    });
  });

  it("ignores malformed lists and non-string entries rather than throwing", () => {
    const result = diffToRows({ added: "B", changed: ["A", 3, null], removed: null });
    expect(result.rows).toEqual([{ path: "A", status: "changed", before: true, after: true }]);
    expect(result.first).toBe(false);
  });

  it("keeps the first classification when a path appears in two lists", () => {
    const result = diffToRows({ added: ["A"], changed: ["A"], removed: [], unchanged: [] });
    expect(result.rows).toEqual([{ path: "A", status: "added", before: false, after: true }]);
  });
});
