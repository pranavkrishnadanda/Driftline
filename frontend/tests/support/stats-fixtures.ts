/**
 * `GET /v1/stats` fixtures shaped by contracts/openapi.json (through the generated
 * client type `Stats`). The window is 30 UTC days ending 2026-10-25.
 */
import type { Stats } from "@/lib/api/client";

export const LAST_DAY = "2026-10-25";

/** The 30 ISO days of the window, oldest first. */
export function windowDays(last: string = LAST_DAY, count = 30): string[] {
  const end = Date.parse(`${last}T00:00:00Z`);
  return Array.from({ length: count }, (_, i) =>
    new Date(end - (count - 1 - i) * 86_400_000).toISOString().slice(0, 10),
  );
}

/** A tenant with no activity at all: zeros and nulls everywhere. */
export function emptyStats(): Stats {
  const days = windowDays();
  return {
    tenant: "demo",
    generated_at: `${LAST_DAY}T15:30:00Z`,
    window_days: 30,
    corpus: {
      documents: 0,
      versions: 0,
      chunks: 0,
      sources: [
        { kind: "openfda", count: 0 },
        { kind: "git_docs", count: 0 },
        { kind: "upload", count: 0 },
      ],
    },
    drift: {
      total: 0,
      per_day: days.map((day) => ({ day, still_valid: 0, changed: 0, broken: 0, total: 0 })),
    },
    asks: {
      latency: { p50_ms: null, p95_ms: null, samples: 0 },
      per_day: days.map((day) => ({ day, asks: 0, p50_ms: null, p95_ms: null })),
    },
    cost: {
      answers: 0,
      answers_cost_usd: 0,
      per_answer_usd: null,
      llm_calls: 0,
      llm_cost_usd: 0,
      per_day: days.map((day) => ({ day, answers: 0, per_answer_usd: null })),
    },
    cache: { hits: 0, misses: 0, hit_rate: null, reason: "no_lookups" },
    review_backlog: [
      { kind: "relation", open: 0 },
      { kind: "broken_answer", open: 0 },
      { kind: "low_confidence_answer", open: 0 },
      { kind: "answer", open: 0 },
    ],
    latest_eval: null,
  };
}

/** A busy tenant: activity on the last three days and a latest eval run. */
export function busyStats(): Stats {
  const stats = emptyStats();
  const n = stats.drift.per_day.length;
  stats.corpus = {
    documents: 12,
    versions: 31,
    chunks: 1234,
    sources: [
      { kind: "openfda", count: 2 },
      { kind: "git_docs", count: 1 },
      { kind: "upload", count: 0 },
    ],
  };
  stats.drift.per_day[n - 1] = { ...stats.drift.per_day[n - 1], changed: 2, broken: 1, total: 3 };
  stats.drift.per_day[n - 3] = { ...stats.drift.per_day[n - 3], still_valid: 1, total: 1 };
  stats.drift.total = 4;
  stats.asks.latency = { p50_ms: 1800, p95_ms: 5240.5, samples: 5 };
  stats.asks.per_day[n - 1] = { ...stats.asks.per_day[n - 1], asks: 4, p50_ms: 1500, p95_ms: 4800 };
  stats.asks.per_day[n - 2] = { ...stats.asks.per_day[n - 2], asks: 1, p50_ms: 2100, p95_ms: 2100 };
  stats.cost = {
    answers: 3,
    answers_cost_usd: 0.0135,
    per_answer_usd: 0.0045,
    llm_calls: 9,
    llm_cost_usd: 0.021,
    per_day: stats.cost.per_day.map((d, i) =>
      i === n - 1
        ? { ...d, answers: 2, per_answer_usd: 0.004 }
        : i === n - 4
          ? { ...d, answers: 1, per_answer_usd: 0.0055 }
          : d,
    ),
  };
  stats.cache = { hits: 1, misses: 3, hit_rate: 0.25, reason: null };
  stats.review_backlog = [
    { kind: "relation", open: 2 },
    { kind: "broken_answer", open: 1 },
    { kind: "low_confidence_answer", open: 0 },
    { kind: "answer", open: 0 },
  ];
  stats.latest_eval = {
    git_sha: "bbbbbbb1234",
    corpus: "pharma",
    created_at: "2026-10-24T12:00:00Z",
    metrics: { citation_precision: 0.88, faithfulness: 0.91 },
  };
  return stats;
}
