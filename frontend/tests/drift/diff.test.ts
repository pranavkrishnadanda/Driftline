import { describe, expect, it } from "vitest";

import { MAX_DIFF_CELLS, diffWords } from "@/lib/drift/diff";

describe("diffWords", () => {
  it("marks changed words and keeps the shared ones", () => {
    expect(diffWords("Take 10 mg twice daily.", "Take 20 mg once daily.")).toEqual([
      { op: "equal", text: "Take " },
      { op: "delete", text: "10" },
      { op: "insert", text: "20" },
      { op: "equal", text: " mg " },
      { op: "delete", text: "twice" },
      { op: "insert", text: "once" },
      { op: "equal", text: " daily." },
    ]);
  });

  it("reads back to the before and after texts", () => {
    const before = "Store below 25 C in a dry place.\nKeep away from light.";
    const after = "Store below 30 C.\nKeep away from light and heat.";
    const parts = diffWords(before, after);
    const side = (skip: string) =>
      parts
        .filter((p) => p.op !== skip)
        .map((p) => p.text)
        .join("");
    expect(side("insert")).toBe(before);
    expect(side("delete")).toBe(after);
  });

  it("handles a section that was added or removed", () => {
    expect(diffWords(null, "New section.")).toEqual([{ op: "insert", text: "New section." }]);
    expect(diffWords("Old section.", null)).toEqual([{ op: "delete", text: "Old section." }]);
    expect(diffWords(null, null)).toEqual([]);
    expect(diffWords("Same.", "Same.")).toEqual([{ op: "equal", text: "Same." }]);
  });

  it("falls back to a whole replacement when the texts are too long to align", () => {
    const words = Math.ceil(Math.sqrt(MAX_DIFF_CELLS)) + 1;
    const before = Array.from({ length: words }, (_, i) => `a${i}`).join(" ");
    const after = Array.from({ length: words }, (_, i) => `b${i}`).join(" ");
    expect(diffWords(before, after)).toEqual([
      { op: "delete", text: before },
      { op: "insert", text: after },
    ]);
  });
});
