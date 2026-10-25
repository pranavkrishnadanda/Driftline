import { describe, expect, it } from "vitest";

import { matchAsk, questionTokens, tokenOverlap } from "@/lib/demo/match";

import { DEMO_RECORDING } from "../support/demo-fixtures";

const ASKS = DEMO_RECORDING.asks;
const TODAY = DEMO_RECORDING.recorded_at;

describe("questionTokens", () => {
  it("keeps content words, lower-cased, without stop words or plurals", () => {
    expect([...questionTokens("What are the Warnings on the labels?")]).toEqual([
      "warning",
      "label",
    ]);
  });
});

describe("tokenOverlap", () => {
  it("is shared words over all words", () => {
    expect(tokenOverlap(new Set(["a1", "b1"]), new Set(["b1", "c1"]))).toBeCloseTo(1 / 3);
    expect(tokenOverlap(new Set(), new Set())).toBe(0);
  });
});

describe("matchAsk", () => {
  it("matches a recorded question on its recorded date exactly", () => {
    const match = matchAsk("How often should ALT be checked?", "2024-06-01T00:00:00Z", ASKS, TODAY);
    expect(match).toMatchObject({ index: 0, exact: true, score: 1 });
  });

  it("ignores case and spacing for an exact match", () => {
    const match = matchAsk("  how often SHOULD alt be   checked? ", null, ASKS, TODAY);
    expect(match).toMatchObject({ index: 1, exact: true });
  });

  it("picks the recording of the same question nearest the asked date", () => {
    expect(matchAsk("How often should ALT be checked?", "2023-01-01", ASKS, TODAY)?.index).toBe(0);
    expect(matchAsk("How often should ALT be checked?", "2026-09-01", ASKS, TODAY)?.index).toBe(1);
  });

  it("maps a typed question to the recorded one sharing the most words, never exact", () => {
    const match = matchAsk("max daily metformin dose for adults", null, ASKS, TODAY);
    expect(match?.ask.request.question).toBe("What is the maximum daily dose of metformin?");
    expect(match?.exact).toBe(false);
  });

  it("still returns a recording for an unrelated question (the demo never invents one)", () => {
    const match = matchAsk("zebra quantum", null, ASKS, TODAY);
    expect(match).not.toBeNull();
    expect(match?.exact).toBe(false);
    expect(match?.score).toBe(0);
  });

  it("returns null only when nothing was recorded", () => {
    expect(matchAsk("anything", null, [], TODAY)).toBeNull();
  });
});
