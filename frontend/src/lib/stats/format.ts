/**
 * Pure formatting and chart-data transforms for the `/stats` view. Every number comes
 * from `GET /v1/stats`; missing data reads as a dash or a sentence, never as a made-up 0.
 */
import type { ReviewKind, Stats } from "@/lib/api/client";

const DASH = "—";

const count = new Intl.NumberFormat("en-US");
const seconds = new Intl.NumberFormat("en-US", { maximumSignificantDigits: 3 });
const smallUsd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumSignificantDigits: 3,
});
const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const score = new Intl.NumberFormat("en-US", { maximumFractionDigits: 3 });
const dayLabel = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});

export function formatCount(n: number): string {
  return count.format(n);
}

export function formatMs(ms: number | null): string {
  if (ms === null) return DASH;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${seconds.format(ms / 1000)} s`;
}

export function formatUsd(value: number | null): string {
  if (value === null) return DASH;
  if (value === 0) return usd.format(0);
  return value >= 1 ? usd.format(value) : smallUsd.format(value);
}

export function formatPercent(rate: number | null): string {
  if (rate === null) return DASH;
  return `${Math.round(rate * 1000) / 10}%`;
}

export function formatScore(value: number): string {
  return score.format(value);
}

/** An ISO day (`YYYY-MM-DD`, a UTC day) as UTC midnight. */
export function utcDate(day: string): Date {
  return new Date(`${day}T00:00:00Z`);
}

/** `2026-10-25` -> `Oct 25` (the day is a UTC day, so it is read in UTC). */
export function formatDay(day: string): string {
  return dayLabel.format(utcDate(day));
}

export function metricLabel(name: string): string {
  const words = name.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export const REVIEW_KIND_LABEL: Record<ReviewKind, { one: string; many: string; short: string }> = {
  relation: { one: "relation", many: "Relations", short: "Relations" },
  broken_answer: { one: "broken answer", many: "Broken answers", short: "Broken" },
  low_confidence_answer: {
    one: "low-confidence answer",
    many: "Low-confidence answers",
    short: "Low conf.",
  },
  answer: { one: "answer", many: "Answers", short: "Answers" },
};

function plural(n: number, one: string, many = `${one}s`): string {
  return `${formatCount(n)} ${n === 1 ? one : many}`;
}

// ---------------------------------------------------------------------------------
// Chart data. Bklit time-series charts take a `Date` x value; bar charts take a label.

export interface DriftBar extends Record<string, unknown> {
  day: string;
  still_valid: number;
  changed: number;
  broken: number;
}

/** One bar per day of the window (empty days included), stacked by verdict. */
export function driftSeries(stats: Stats): DriftBar[] {
  return stats.drift.per_day.map((d) => ({
    day: formatDay(d.day),
    still_valid: d.still_valid,
    changed: d.changed,
    broken: d.broken,
  }));
}

export interface LatencyPoint extends Record<string, unknown> {
  date: Date;
  p50: number;
  p95: number;
}

/** Only days with finished asks: a day without asks has no latency, not 0 ms. */
export function latencySeries(stats: Stats): LatencyPoint[] {
  return stats.asks.per_day.flatMap((d) =>
    d.asks > 0 && d.p50_ms !== null && d.p95_ms !== null
      ? [{ date: utcDate(d.day), p50: d.p50_ms, p95: d.p95_ms }]
      : [],
  );
}

export interface CostPoint extends Record<string, unknown> {
  date: Date;
  perAnswer: number;
}

/** Only days with answers. */
export function costSeries(stats: Stats): CostPoint[] {
  return stats.cost.per_day.flatMap((d) =>
    d.answers > 0 && d.per_answer_usd !== null
      ? [{ date: utcDate(d.day), perAnswer: d.per_answer_usd }]
      : [],
  );
}

export interface BacklogBar extends Record<string, unknown> {
  kind: string;
  open: number;
}

export function backlogSeries(stats: Stats): BacklogBar[] {
  return stats.review_backlog.map((b) => ({ kind: REVIEW_KIND_LABEL[b.kind].short, open: b.open }));
}

export interface EvalBar extends Record<string, unknown> {
  metric: string;
  score: number;
}

/** The latest eval run's metrics; empty when there has been no run. */
export function evalSeries(stats: Stats): EvalBar[] {
  return Object.entries(stats.latest_eval?.metrics ?? {}).map(([name, value]) => ({
    metric: metricLabel(name),
    score: value,
  }));
}

export function backlogTotal(stats: Stats): number {
  return stats.review_backlog.reduce((sum, b) => sum + b.open, 0);
}

// ---------------------------------------------------------------------------------
// KPI tiles

export interface KpiTile {
  id: "corpus" | "drift" | "latency" | "cost" | "cache" | "backlog";
  title: string;
  value: string;
  detail: string;
}

function cacheDetail(stats: Stats): string {
  const { hits, misses, reason } = stats.cache;
  if (reason === "redis_unavailable") return "Cache counters unavailable";
  if (hits + misses === 0) return "No cache lookups yet";
  return `${plural(hits, "hit")} · ${plural(misses, "miss", "misses")}`;
}

export function kpiTiles(stats: Stats): KpiTile[] {
  const { corpus, asks, cost } = stats;
  const sources = corpus.sources.reduce((sum, s) => sum + s.count, 0);
  return [
    {
      id: "corpus",
      title: "Documents",
      value: formatCount(corpus.documents),
      detail: `${plural(corpus.versions, "version")} · ${plural(corpus.chunks, "chunk")} · ${plural(sources, "source")}`,
    },
    {
      id: "drift",
      title: "Drift events",
      value: formatCount(stats.drift.total),
      detail: `last ${stats.window_days} days`,
    },
    {
      id: "latency",
      title: "Ask latency",
      value: formatMs(asks.latency.p95_ms),
      detail:
        asks.latency.samples > 0
          ? `p95 · p50 ${formatMs(asks.latency.p50_ms)} · ${plural(asks.latency.samples, "ask")}`
          : "No finished asks yet",
    },
    {
      id: "cost",
      title: "Cost per answer",
      value: formatUsd(cost.per_answer_usd),
      detail: cost.answers > 0 ? plural(cost.answers, "answer") : "No answers yet",
    },
    {
      id: "cache",
      title: "Cache hit rate",
      value: formatPercent(stats.cache.hit_rate),
      detail: cacheDetail(stats),
    },
    {
      id: "backlog",
      title: "Review backlog",
      value: formatCount(backlogTotal(stats)),
      detail: "open items",
    },
  ];
}

// ---------------------------------------------------------------------------------
// Accessible descriptions: each chart's SVG is decorative to assistive tech, so each
// figure carries one of these sentences.

export function describeDrift(stats: Stats): string {
  const days = stats.drift.per_day;
  if (stats.drift.total === 0) return `No drift events in the last ${stats.window_days} days.`;
  const sum = (key: "still_valid" | "changed" | "broken") => days.reduce((n, d) => n + d[key], 0);
  const busiest = days.reduce((best, d) => (d.total > best.total ? d : best));
  return (
    `${plural(stats.drift.total, "drift event")} in the last ${stats.window_days} days: ` +
    `${formatCount(sum("still_valid"))} still valid, ${formatCount(sum("changed"))} changed, ` +
    `${formatCount(sum("broken"))} broken. ` +
    `Busiest day: ${formatDay(busiest.day)} with ${formatCount(busiest.total)}.`
  );
}

export function describeLatency(stats: Stats): string {
  const { latency } = stats.asks;
  if (latency.samples === 0) return `No finished asks in the last ${stats.window_days} days.`;
  return (
    `Ask latency over ${plural(latency.samples, "ask")}: p50 ${formatMs(latency.p50_ms)}, ` +
    `p95 ${formatMs(latency.p95_ms)}. Plotted on ${plural(latencySeries(stats).length, "day")} with asks.`
  );
}

export function describeCost(stats: Stats): string {
  const { cost } = stats;
  if (cost.answers === 0) return `No answers in the last ${stats.window_days} days.`;
  return (
    `${plural(cost.answers, "answer")} cost ${formatUsd(cost.answers_cost_usd)} in total, ` +
    `${formatUsd(cost.per_answer_usd)} per answer. ` +
    `All LLM calls: ${formatUsd(cost.llm_cost_usd)} over ${plural(cost.llm_calls, "call")}.`
  );
}

export function describeCache(stats: Stats): string {
  const { hits, misses, hit_rate, reason } = stats.cache;
  if (reason === "redis_unavailable") return "The cache counters could not be read.";
  if (hit_rate === null) return "No cache lookups yet, so there is no hit rate.";
  return `Cache hit rate ${formatPercent(hit_rate)}: ${plural(hits, "hit")} and ${plural(misses, "miss", "misses")}.`;
}

export function describeBacklog(stats: Stats): string {
  const total = backlogTotal(stats);
  if (total === 0) return "The review queue is empty.";
  const parts = stats.review_backlog.map((b) => {
    const label = REVIEW_KIND_LABEL[b.kind];
    return plural(b.open, label.one, `${label.one}s`);
  });
  return `${plural(total, "open review item")}: ${parts.join(", ")}.`;
}

export function describeEval(stats: Stats): string {
  const run = stats.latest_eval;
  if (!run) return "No eval runs yet.";
  const metrics = evalSeries(stats).map((m) => `${m.metric} ${formatScore(m.score)}`);
  return (
    `Latest eval run ${run.git_sha.slice(0, 7)} on corpus ${run.corpus}: ` +
    (metrics.length ? `${metrics.join(", ")}.` : "no numeric metrics.")
  );
}
