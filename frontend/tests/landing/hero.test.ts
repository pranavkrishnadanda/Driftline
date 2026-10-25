import { describe, expect, it } from "vitest";

import { HERO_VERSIONS, asOfBoard, documentLines, versionStops } from "@/lib/landing/hero";

describe("versionStops", () => {
  it("spaces the versions evenly between the insets", () => {
    expect(versionStops(3, { width: 640, inset: 120 })).toEqual([120, 320, 520]);
  });

  it("centres a single version", () => {
    expect(versionStops(1, { width: 640, inset: 120 })).toEqual([320]);
  });

  it("returns nothing for no versions", () => {
    expect(versionStops(0, { width: 640, inset: 120 })).toEqual([]);
  });
});

describe("documentLines", () => {
  it("shows the first version's sections unchanged", () => {
    const lines = documentLines(HERO_VERSIONS, 0);
    expect(lines.every((l) => l.state === "same")).toBe(true);
    expect(lines).toHaveLength(HERO_VERSIONS[0].sections);
  });

  it("marks the section a later version changed, and keeps it changed after", () => {
    const changed = HERO_VERSIONS[1].changed!;
    expect(documentLines(HERO_VERSIONS, 1)[changed].state).toBe("changed");
    expect(documentLines(HERO_VERSIONS, 2)[changed].state).toBe("changed");
  });

  it("adds the sections a later version adds, at the end", () => {
    const v3 = documentLines(HERO_VERSIONS, 2);
    expect(v3).toHaveLength(HERO_VERSIONS[2].sections);
    expect(v3.at(-1)!.state).toBe("added");
    expect(documentLines(HERO_VERSIONS, 1)).toHaveLength(HERO_VERSIONS[1].sections);
  });

  it("gives a changed section a different width from the original", () => {
    const changed = HERO_VERSIONS[1].changed!;
    expect(documentLines(HERO_VERSIONS, 1)[changed].width).not.toBe(
      documentLines(HERO_VERSIONS, 0)[changed].width,
    );
  });

  it("rejects a version index outside the list", () => {
    expect(() => documentLines(HERO_VERSIONS, 3)).toThrow(RangeError);
  });
});

describe("asOfBoard", () => {
  it("prints the version and its start date in departure-board capitals", () => {
    expect(asOfBoard({ label: "v2", validFrom: "2024-06-01" })).toBe("V2 AS OF 2024-06-01");
  });
});
