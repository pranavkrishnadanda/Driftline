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

/** Plain names for the eval metrics the harness reports. */
const METRIC_LABELS: Record<string, string> = {
  citation_precision: "Citation accuracy",
  citation_recall: "Citation coverage",
  faithfulness: "Faithfulness",
  answer_correctness: "Answer correctness",
  as_of_accuracy: "Right version for the date",
  refusal_accuracy: "Knows when to refuse",
};

export function metricLabel(name: string): string {
  const known = METRIC_LABELS[name];
  if (known) return known;
  const words = name.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** A 0-1 score as a percentage ("88%"); other scales are shown as they are. */
export function formatScoreFriendly(value: number): string {
  return value >= 0 && value <= 1 ? `${Math.round(value * 100)}%` : formatScore(value);
}

const longDay = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

/** An ISO timestamp as "24 Oct 2026". */
export function formatLongDay(iso: string): string {
  const at = Date.parse(iso);
  return Number.isNaN(at) ? iso : longDay.format(at);
}

export const REVIEW_KIND_LABEL: Record<ReviewKind, { one: string; many: string; short: string }> = {
  relation: { one: "document link", many: "Document links", short: "Links" },
  broken_answer: { one: "broken answer", many: "Broken answers", short: "Broken" },
  low_confidence_answer: {
    one: "low-confidence answer",
    many: "Low-confidence answers",
    short: "Unsure",
  },
  answer: { one: "regenerated answer", many: "Regenerated answers", short: "Regenerated" },
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
  /** The exact figures behind the tile, shown on hover. */
  exact: string;
}

function cacheDetail(stats: Stats): string {
  const { hits, misses, reason } = stats.cache;
  if (reason === "redis_unavailable") return "Not available right now";
  if (hits + misses === 0) return "No questions asked yet";
  return `${formatCount(hits)} of ${plural(hits + misses, "question")} reused a saved answer`;
}

export function kpiTiles(stats: Stats): KpiTile[] {
  const { corpus, asks, cost, cache } = stats;
  const sources = corpus.sources.reduce((sum, s) => sum + s.count, 0);
  return [
    {
      id: "corpus",
      title: "Documents",
      value: formatCount(corpus.documents),
      detail: `${plural(corpus.versions, "version")} from ${plural(sources, "source")}`,
      exact: `${plural(corpus.documents, "document")}, ${plural(corpus.versions, "version")}, ${plural(corpus.chunks, "passage")}, ${plural(sources, "source")}`,
    },
    {
      id: "drift",
      title: "Changes detected",
      value: formatCount(stats.drift.total),
      detail: `in the last ${stats.window_days} days`,
      exact: `${plural(stats.drift.total, "drift event")} in the last ${stats.window_days} days`,
    },
    {
      id: "latency",
      title: "Typical answer time",
      value: formatMs(asks.latency.p50_ms),
      detail:
        asks.latency.samples > 0
          ? `Slowest 5%: ${formatMs(asks.latency.p95_ms)}`
          : "No answers yet",
      exact:
        asks.latency.samples > 0
          ? `p50 ${formatCount(Math.round(asks.latency.p50_ms ?? 0))} ms, p95 ${formatCount(Math.round(asks.latency.p95_ms ?? 0))} ms over ${plural(asks.latency.samples, "answer")}`
          : "No finished answers yet",
    },
    {
      id: "cost",
      title: "Cost per answer",
      value: formatUsd(cost.per_answer_usd),
      detail: cost.answers > 0 ? `across ${plural(cost.answers, "answer")}` : "No answers yet",
      exact:
        cost.answers > 0
          ? `$${(cost.per_answer_usd ?? 0).toFixed(6)} per answer, $${cost.answers_cost_usd.toFixed(6)} in total`
          : "No answers yet",
    },
    {
      id: "cache",
      title: "Answers reused",
      value: formatPercent(cache.hit_rate),
      detail: cacheDetail(stats),
      exact: `Cache: ${plural(cache.hits, "hit")}, ${plural(cache.misses, "miss", "misses")}`,
    },
    {
      id: "backlog",
      title: "Waiting for review",
      value: formatCount(backlogTotal(stats)),
      detail: backlogTotal(stats) === 1 ? "item needs a decision" : "items need a decision",
      exact: stats.review_backlog
        .map((b) => `${REVIEW_KIND_LABEL[b.kind].many}: ${formatCount(b.open)}`)
        .join(", "),
    },
  ];
}

// ---------------------------------------------------------------------------------
// Accessible descriptions: each chart's SVG is decorative to assistive tech, so each
// figure carries one of these sentences.

export function describeDrift(stats: Stats): string {
  const days = stats.drift.per_day;
  if (stats.drift.total === 0) return `No changes detected in the last ${stats.window_days} days.`;
  const sum = (key: "still_valid" | "changed" | "broken") => days.reduce((n, d) => n + d[key], 0);
  const busiest = days.reduce((best, d) => (d.total > best.total ? d : best));
  return (
    `${plural(stats.drift.total, "change")} detected in the last ${stats.window_days} days: ` +
    `${formatCount(sum("still_valid"))} still valid, ${formatCount(sum("changed"))} changed, ` +
    `${formatCount(sum("broken"))} broken. ` +
    `Busiest day: ${formatDay(busiest.day)} with ${formatCount(busiest.total)}.`
  );
}

export function describeLatency(stats: Stats): string {
  const { latency } = stats.asks;
  if (latency.samples === 0) return `No answers in the last ${stats.window_days} days.`;
  return (
    `A typical answer took ${formatMs(latency.p50_ms)}; the slowest 5% took ` +
    `${formatMs(latency.p95_ms)} or more (${plural(latency.samples, "answer")}, ` +
    `${plural(latencySeries(stats).length, "day")} with answers).`
  );
}

export function describeCost(stats: Stats): string {
  const { cost } = stats;
  if (cost.answers === 0) return `No answers in the last ${stats.window_days} days.`;
  return (
    `${plural(cost.answers, "answer")} cost ${formatUsd(cost.answers_cost_usd)} in total, ` +
    `${formatUsd(cost.per_answer_usd)} per answer. ` +
    `All model calls: ${formatUsd(cost.llm_cost_usd)} over ${plural(cost.llm_calls, "call")}.`
  );
}

export function describeCache(stats: Stats): string {
  const { hits, misses, hit_rate, reason } = stats.cache;
  if (reason === "redis_unavailable") return "Reuse figures are not available right now.";
  if (hit_rate === null) return "No questions asked yet.";
  return (
    `${formatPercent(hit_rate)} of questions reused a saved answer for the same question ` +
    `and date (${formatCount(hits)} of ${formatCount(hits + misses)}).`
  );
}

export function describeBacklog(stats: Stats): string {
  const total = backlogTotal(stats);
  if (total === 0) return "Nothing is waiting for review.";
  const parts = stats.review_backlog.map((b) => {
    const label = REVIEW_KIND_LABEL[b.kind];
    return plural(b.open, label.one, `${label.one}s`);
  });
  return `${plural(total, "item")} waiting for a person to decide: ${parts.join(", ")}.`;
}

export function describeEval(stats: Stats): string {
  const run = stats.latest_eval;
  if (!run) return "No quality checks yet.";
  const metrics = evalSeries(stats).map(
    (m) => `${m.metric.toLowerCase()} ${formatScoreFriendly(m.score)}`,
  );
  return (
    `Checked on ${formatLongDay(run.created_at)} against the ${run.corpus} question set: ` +
    (metrics.length ? `${metrics.join(", ")}.` : "no scores recorded.")
  );
}
