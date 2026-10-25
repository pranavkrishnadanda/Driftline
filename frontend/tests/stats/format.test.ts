import { describe, expect, it } from "vitest";

import {
  backlogSeries,
  costSeries,
  describeBacklog,
  describeCache,
  describeCost,
  describeDrift,
  describeEval,
  describeLatency,
  driftSeries,
  evalSeries,
  formatCount,
  formatDay,
  formatMs,
  formatPercent,
  formatUsd,
  kpiTiles,
  latencySeries,
  metricLabel,
} from "@/lib/stats/format";

import { busyStats, emptyStats } from "../support/stats-fixtures";

describe("formatters", () => {
  it("formatCount groups thousands", () => {
    expect(formatCount(0)).toBe("0");
    expect(formatCount(1234)).toBe("1,234");
  });

  it("formatMs picks ms or seconds, and shows a dash for no data", () => {
    expect(formatMs(null)).toBe("—");
    expect(formatMs(850.4)).toBe("850 ms");
    expect(formatMs(1800)).toBe("1.8 s");
    expect(formatMs(5240.5)).toBe("5.24 s");
    expect(formatMs(65_000)).toBe("65 s");
  });

  it("formatUsd keeps sub-cent costs readable", () => {
    expect(formatUsd(null)).toBe("—");
    expect(formatUsd(0)).toBe("$0.00");
    expect(formatUsd(0.0045)).toBe("$0.0045");
    expect(formatUsd(0.013456)).toBe("$0.0135");
    expect(formatUsd(1.5)).toBe("$1.50");
  });

  it("formatPercent rounds to one decimal only when needed", () => {
    expect(formatPercent(null)).toBe("—");
    expect(formatPercent(0.25)).toBe("25%");
    expect(formatPercent(1 / 3)).toBe("33.3%");
    expect(formatPercent(1)).toBe("100%");
  });

  it("formatDay reads an ISO day in UTC", () => {
    expect(formatDay("2026-10-25")).toBe("Oct 25");
    expect(formatDay("2026-01-01")).toBe("Jan 1");
  });

  it("metricLabel humanises eval metric names", () => {
    expect(metricLabel("citation_precision")).toBe("Citation accuracy");
    expect(metricLabel("faithfulness")).toBe("Faithfulness");
    expect(metricLabel("some_new_metric")).toBe("Some new metric");
  });
});

describe("chart transforms", () => {
  it("driftSeries keeps every day of the window, stacked by verdict", () => {
    const series = driftSeries(busyStats());
    expect(series).toHaveLength(30);
    expect(series.at(-1)).toEqual({
      day: "Oct 25",
      still_valid: 0,
      changed: 2,
      broken: 1,
    });
    expect(series.at(-3)).toMatchObject({ day: "Oct 23", still_valid: 1 });
  });

  it("latencySeries plots only days with asks, as UTC dates", () => {
    const series = latencySeries(busyStats());
    expect(series).toEqual([
      { date: new Date("2026-10-24T00:00:00Z"), p50: 2100, p95: 2100 },
      { date: new Date("2026-10-25T00:00:00Z"), p50: 1500, p95: 4800 },
    ]);
    expect(latencySeries(emptyStats())).toEqual([]);
  });

  it("costSeries plots only days with answers", () => {
    expect(costSeries(busyStats())).toEqual([
      { date: new Date("2026-10-22T00:00:00Z"), perAnswer: 0.0055 },
      { date: new Date("2026-10-25T00:00:00Z"), perAnswer: 0.004 },
    ]);
    expect(costSeries(emptyStats())).toEqual([]);
  });

  it("backlogSeries labels every review kind", () => {
    expect(backlogSeries(busyStats())).toEqual([
      { kind: "Links", open: 2 },
      { kind: "Broken", open: 1 },
      { kind: "Unsure", open: 0 },
      { kind: "Regenerated", open: 0 },
    ]);
  });

  it("evalSeries lists the latest run's metrics, or nothing without a run", () => {
    expect(evalSeries(busyStats())).toEqual([
      { metric: "Citation accuracy", score: 0.88 },
      { metric: "Faithfulness", score: 0.91 },
    ]);
    expect(evalSeries(emptyStats())).toEqual([]);
  });
});

describe("KPI tiles", () => {
  it("summarise corpus, drift, latency, cost and cache", () => {
    const tiles = kpiTiles(busyStats());
    expect(tiles.map((t) => [t.id, t.value])).toEqual([
      ["corpus", "12"],
      ["drift", "4"],
      ["latency", "1.8 s"],
      ["cost", "$0.0045"],
      ["cache", "25%"],
      ["backlog", "3"],
    ]);
    const corpus = tiles.find((t) => t.id === "corpus")!;
    expect(corpus.detail).toBe("31 versions from 3 sources");
    expect(corpus.exact).toBe("12 documents, 31 versions, 1,234 passages, 3 sources");
    const latency = tiles.find((t) => t.id === "latency")!;
    expect(latency.title).toBe("Typical answer time");
    expect(latency.detail).toBe("Slowest 5%: 5.24 s");
    expect(latency.exact).toBe("p50 1,800 ms, p95 5,241 ms over 5 answers");
  });

  it("show dashes, not zeros dressed up as numbers, when there is no data", () => {
    const tiles = kpiTiles(emptyStats());
    expect(tiles.find((t) => t.id === "latency")!.value).toBe("—");
    expect(tiles.find((t) => t.id === "cost")!.value).toBe("—");
    expect(tiles.find((t) => t.id === "cache")!.value).toBe("—");
    expect(tiles.find((t) => t.id === "cache")!.detail).toBe("No questions asked yet");
  });
});

describe("accessible chart descriptions", () => {
  it("describe each chart in words", () => {
    const stats = busyStats();
    expect(describeDrift(stats)).toBe(
      "4 changes detected in the last 30 days: 1 still valid, 2 changed, 1 broken. Busiest day: Oct 25 with 3.",
    );
    expect(describeLatency(stats)).toBe(
      "A typical answer took 1.8 s; the slowest 5% took 5.24 s or more (5 answers, 2 days with answers).",
    );
    expect(describeCost(stats)).toBe(
      "3 answers cost $0.0135 in total, $0.0045 per answer. All model calls: $0.021 over 9 calls.",
    );
    expect(describeCache(stats)).toBe(
      "25% of questions reused a saved answer for the same question and date (1 of 4).",
    );
    expect(describeBacklog(stats)).toBe(
      "3 items waiting for a person to decide: 2 document links, 1 broken answer, 0 low-confidence answers, 0 regenerated answers.",
    );
    expect(describeEval(stats)).toBe(
      "Checked on 24 Oct 2026 against the pharma question set: citation accuracy 88%, faithfulness 91%.",
    );
  });

  it("say plainly when there is nothing to show", () => {
    const stats = emptyStats();
    expect(describeDrift(stats)).toBe("No changes detected in the last 30 days.");
    expect(describeLatency(stats)).toBe("No answers in the last 30 days.");
    expect(describeCost(stats)).toBe("No answers in the last 30 days.");
    expect(describeCache(stats)).toBe("No questions asked yet.");
    expect(describeBacklog(stats)).toBe("Nothing is waiting for review.");
    expect(describeEval(stats)).toBe("No quality checks yet.");
  });
});
