#!/usr/bin/env bun
/**
 * Records a real run of the Driftline stack into the recorded demo's bundle
 * (`public/demo/recording.json`), which the demo build replays on GitHub Pages.
 *
 * Two steps, around the ingest of the newer document versions:
 *
 *   # 1. Older versions ingested: ask the plan's questions, record each SSE stream with
 *   #    its timing and the job, and watch every answer so drift re-checks it.
 *   bun scripts/capture-demo.ts asks --gateway http://127.0.0.1:18110 --tenant demo \
 *     --plan scripts/demo-plan.json --state /tmp/demo-state.json
 *
 *   # 2. Newer versions ingested and drift settled: record drift events, the alert
 *   #    stream, the review queue, every cited or drifted document's timeline and stats.
 *   bun scripts/capture-demo.ts finish --gateway http://127.0.0.1:18110 --tenant demo \
 *     --state /tmp/demo-state.json --out public/demo/recording.json --source "..."
 *
 * The plan is a JSON array of `{ "question": "...", "as_of": "YYYY-MM-DD" | null,
 * "watch": true }`. `DRIFTLINE_API_KEY` (optional) is sent as a bearer key and never
 * written anywhere. The bundle is checked for anything that looks like a secret.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { parseArgs } from "node:util";

import type {
  AskAccepted,
  AskRequest,
  DocumentTimeline,
  DriftEventList,
  JobStatus,
  ReviewItemList,
  Stats,
} from "../src/lib/api/client";
import type { DemoRecording, RecordedAsk, RecordedEvent } from "../src/lib/demo/recording";
import { createSseParser } from "../src/lib/sse/parse";

interface PlannedAsk {
  question: string;
  as_of?: string | null;
  watch?: boolean;
}

interface CaptureState {
  tenant: string;
  asks: RecordedAsk[];
}

const { positionals, values } = parseArgs({
  allowPositionals: true,
  options: {
    gateway: { type: "string" },
    tenant: { type: "string", default: "demo" },
    plan: { type: "string" },
    state: { type: "string" },
    out: { type: "string" },
    source: { type: "string", default: "" },
    "alert-seconds": { type: "string", default: "5" },
    "ask-timeout": { type: "string", default: "240" },
  },
});

const gateway = (values.gateway ?? "").replace(/\/+$/, "");
if (!gateway) throw new Error("--gateway is required");
const tenant = values.tenant ?? "demo";
const apiKey = process.env.DRIFTLINE_API_KEY?.trim() || null;

function headers(extra: Record<string, string> = {}): Record<string, string> {
  return {
    Accept: "application/json",
    ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
    ...extra,
  };
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const url = new URL(gateway + path);
  if (!url.searchParams.has("tenant")) url.searchParams.set("tenant", tenant);
  const response = await fetch(url, {
    method,
    headers: headers(body === undefined ? {} : { "Content-Type": "application/json" }),
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(60_000),
  });
  const text = await response.text();
  if (!response.ok)
    throw new Error(`${method} ${path} -> ${response.status}: ${text.slice(0, 300)}`);
  return JSON.parse(text) as T;
}

/** Read an SSE stream, timing each event from when the response opened. */
async function recordStream(
  path: string,
  { until, timeoutMs }: { until: (event: RecordedEvent) => boolean; timeoutMs: number },
): Promise<RecordedEvent[]> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const events: RecordedEvent[] = [];
  const url = new URL(gateway + path);
  if (!url.searchParams.has("tenant")) url.searchParams.set("tenant", tenant);
  try {
    const response = await fetch(url, {
      headers: headers({ Accept: "text/event-stream" }),
      signal: controller.signal,
    });
    if (!response.ok || !response.body) throw new Error(`GET ${path} -> ${response.status}`);
    const opened = performance.now();
    let done = false;
    const parser = createSseParser({
      onMessage: (message) => {
        if (done) return;
        const event: RecordedEvent = {
          at_ms: Math.round(performance.now() - opened),
          id: message.id,
          event: message.type,
          data: JSON.parse(message.data),
        };
        events.push(event);
        if (until(event)) done = true;
      },
    });
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    while (!done) {
      const { done: ended, value } = await reader.read();
      if (ended) break;
      parser.feed(decoder.decode(value, { stream: true }));
    }
    await reader.cancel().catch(() => undefined);
  } catch (error) {
    if (!controller.signal.aborted) throw error;
  } finally {
    clearTimeout(timer);
  }
  return events;
}

function terminal(event: RecordedEvent): boolean {
  const data = event.data as { type?: string; retryable?: boolean };
  return data.type === "final" || (data.type === "error" && data.retryable === false);
}

async function captureAsks(planPath: string, statePath: string): Promise<void> {
  const plan = JSON.parse(readFileSync(planPath, "utf8")) as PlannedAsk[];
  const state: CaptureState = { tenant, asks: [] };
  for (const planned of plan) {
    const request: AskRequest = { question: planned.question, tenant };
    if (planned.as_of) request.as_of = `${planned.as_of.slice(0, 10)}T00:00:00Z`;
    const accepted = await call<AskAccepted>("POST", "/v1/ask", request);
    const events = await recordStream(accepted.events_url, {
      until: terminal,
      timeoutMs: Number(values["ask-timeout"]) * 1000,
    });
    const job = await call<JobStatus>("GET", accepted.status_url);
    const answerId = job.answer?.answer_id;
    if (planned.watch !== false && answerId) {
      await call("POST", `/v1/answers/${answerId}/watch`);
    }
    const last = events.at(-1);
    console.log(
      `asked ${JSON.stringify(planned.question)} as of ${planned.as_of ?? "today"}: ` +
        `${events.length} events in ${last?.at_ms ?? 0} ms, ${job.status}, ` +
        `${job.answer?.status ?? "no answer"}, $${job.cost_usd.toFixed(4)}`,
    );
    state.asks.push({ request, accepted, events, job });
    writeFileSync(statePath, JSON.stringify(state, null, 2));
  }
}

/** Every document an answer cites or nearly cites. */
function citedDocuments(asks: RecordedAsk[]): string[] {
  const ids = new Set<string>();
  for (const ask of asks) {
    const answer = ask.job.answer;
    if (!answer) continue;
    for (const claim of answer.claims) {
      for (const citation of claim.citations)
        if (citation.document_id) ids.add(citation.document_id);
    }
    for (const source of answer.nearest_sources)
      if (source.document_id) ids.add(source.document_id);
  }
  return [...ids];
}

const SECRET =
  /sk-ant-[A-Za-z0-9_-]{8,}|ANTHROPIC_API_KEY|DRIFTLINE_ANTHROPIC|Bearer\s+[A-Za-z0-9._-]{12,}/;

async function finish(statePath: string, outPath: string): Promise<void> {
  const state = JSON.parse(readFileSync(statePath, "utf8")) as CaptureState;
  const drift = await call<DriftEventList>("GET", "/v1/drift/events?limit=200");
  const alerts = await recordStream("/v1/alerts/stream", {
    until: () => false,
    timeoutMs: Number(values["alert-seconds"]) * 1000,
  });
  const review = await call<ReviewItemList>("GET", "/v1/review?limit=200");
  const stats = await call<Stats>("GET", "/v1/stats");

  const timelines: Record<string, DocumentTimeline> = {};
  const queue = [
    ...citedDocuments(state.asks),
    ...drift.events.flatMap((e) => (e.document_id ? [e.document_id] : [])),
  ];
  // The documents above, plus the ones their relations point at (one hop).
  for (let hop = 0; hop < 2; hop++) {
    const next: string[] = [];
    for (const id of queue) {
      if (timelines[id]) continue;
      try {
        timelines[id] = await call<DocumentTimeline>("GET", `/v1/documents/${id}/timeline`);
      } catch (error) {
        console.warn(`skipped the timeline of ${id}: ${(error as Error).message}`);
        continue;
      }
      if (hop === 0) {
        const { incoming, outgoing } = timelines[id].relations;
        for (const r of [...incoming, ...outgoing]) next.push(r.document_id);
      }
    }
    queue.splice(0, queue.length, ...next);
  }

  const recording: DemoRecording = {
    version: 1,
    recorded_at: new Date().toISOString(),
    source: values.source ?? "",
    tenant: state.tenant,
    asks: state.asks,
    drift_events: drift.events,
    alerts,
    review: review.items,
    timelines,
    stats,
  };
  const text = `${JSON.stringify(recording, null, 1)}\n`;
  const leak = text.match(SECRET);
  if (leak)
    throw new Error(
      `refusing to write: the bundle contains a secret-like string (${leak[0].slice(0, 12)}…)`,
    );
  writeFileSync(outPath, text);
  console.log(
    `wrote ${outPath}: ${state.asks.length} asks, ${drift.events.length} drift events, ` +
      `${alerts.length} alerts, ${review.items.length} review items, ` +
      `${Object.keys(timelines).length} timelines`,
  );
}

const [command] = positionals;
if (command === "asks") {
  if (!values.plan || !values.state) throw new Error("asks needs --plan and --state");
  await captureAsks(values.plan, values.state);
} else if (command === "finish") {
  if (!values.state || !values.out) throw new Error("finish needs --state and --out");
  await finish(values.state, values.out);
} else {
  throw new Error("usage: capture-demo.ts asks|finish [options]");
}
