/**
 * A stub Driftline gateway for browser checks (axe, reduced motion) without the backend
 * stack: a real Node `http` server that serves the contract fixtures in this directory
 * on the gateway's routes, with CORS for the frontend's origin. It replays the answered
 * ask stream and holds the alert stream open with heartbeats, like the gateway does.
 *
 * Playwright starts it from `tests/e2e/stub/global-setup.ts` (`npm run test:e2e:stub`).
 */
import { randomUUID } from "node:crypto";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";

import type { DriftEvent, ReviewItem, Stats } from "@/lib/api/client";

import { ANSWERED_EVENTS } from "./ask-fixtures";
import { BROKEN, LOW_CONFIDENCE, RELATION, alert, alertFrame, driftEvent } from "./drift-fixtures";
import { frame, type FixtureEvent } from "./sse-server";
import { busyStats } from "./stats-fixtures";
import { DOC_ID, TIMELINE } from "./version-timeline-fixtures";

export const STUB_DRIFT_EVENTS: DriftEvent[] = [
  driftEvent({
    id: "e0000000-0000-4000-8000-000000000001",
    document_id: DOC_ID,
    document_title: TIMELINE.title ?? "Metformin label",
    verdict: "changed",
    created_at: "2026-10-20T09:00:00Z",
  }),
  driftEvent({
    id: "e0000000-0000-4000-8000-000000000002",
    document_id: DOC_ID,
    document_title: TIMELINE.title ?? "Metformin label",
    verdict: "broken",
    created_at: "2026-10-21T09:00:00Z",
  }),
];

export const STUB_REVIEW_ITEMS: ReviewItem[] = [LOW_CONFIDENCE, BROKEN, RELATION];

/** The busy-tenant `/v1/stats` payload, shared with the `/stats` unit tests. */
export const STUB_STATS: Stats = busyStats();

export const STUB_ALERT = alert({
  drift_event_id: "e0000000-0000-4000-8000-000000000003",
  document_title: TIMELINE.title ?? "Metformin label",
});

/** How often the alert stream sends `: ping` (the gateway's default is 15 s). */
const HEARTBEAT_MS = 5_000;

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Accept, Authorization, Content-Type, Last-Event-ID",
  "Access-Control-Max-Age": "600",
};

export interface StubGateway {
  url: string;
  close: () => Promise<void>;
}

function json(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { ...CORS, "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
}

function sse(res: ServerResponse): void {
  res.writeHead(200, {
    ...CORS,
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
  });
}

function afterId(req: IncomingMessage): number {
  const header = req.headers["last-event-id"];
  return typeof header === "string" && /^\d+$/.test(header) ? Number(header) : 0;
}

function replay(req: IncomingMessage, res: ServerResponse, events: FixtureEvent[]): void {
  sse(res);
  const after = afterId(req);
  res.end(": ping\n\n" + events.filter((e) => e.id === null || e.id > after).map(frame).join(""));
}

function alertStream(req: IncomingMessage, res: ServerResponse): void {
  sse(res);
  const after = afterId(req);
  res.write(": ping\n\n" + [alertFrame(1, STUB_ALERT)].filter((e) => e.id! > after).map(frame).join(""));
  const timer = setInterval(() => res.write(": ping\n\n"), HEARTBEAT_MS);
  res.on("close", () => clearInterval(timer));
}

function route(req: IncomingMessage, res: ServerResponse, body: string): void {
  const url = new URL(req.url ?? "/", "http://stub");
  const path = url.pathname;
  const method = req.method ?? "GET";
  let m: RegExpMatchArray | null;

  if (method === "OPTIONS") {
    res.writeHead(204, CORS);
    res.end();
    return;
  }
  if (method === "GET" && path === "/healthz") return json(res, 200, { status: "ok" });
  if (method === "GET" && path === "/v1/drift/events") return json(res, 200, { events: STUB_DRIFT_EVENTS });
  if (method === "GET" && path === "/v1/alerts/stream") return alertStream(req, res);
  if (method === "GET" && path === "/v1/review") {
    const kind = url.searchParams.get("kind");
    return json(res, 200, { items: STUB_REVIEW_ITEMS.filter((i) => !kind || i.kind === kind) });
  }
  if (method === "POST" && (m = path.match(/^\/v1\/review\/([^/]+)\/resolve$/))) {
    const item = STUB_REVIEW_ITEMS.find((i) => i.id === m![1]);
    if (!item) return json(res, 404, { detail: { code: "not_found" } });
    const resolution = JSON.parse(body || "{}") as { action?: string; by?: string };
    return json(res, 200, {
      ...item,
      status: "resolved",
      resolution,
      resolved_by: resolution.by ?? "driftline-web",
      resolved_at: new Date().toISOString(),
    });
  }
  if (method === "GET" && (m = path.match(/^\/v1\/documents\/([^/]+)\/timeline$/))) {
    return m[1] === DOC_ID ? json(res, 200, TIMELINE) : json(res, 404, { detail: { code: "not_found" } });
  }
  if (method === "POST" && path === "/v1/ask") {
    const job = randomUUID();
    return json(res, 202, {
      job_id: job,
      events_url: `/v1/ask/${job}/events`,
      status_url: `/v1/jobs/${job}`,
    });
  }
  if (method === "GET" && /^\/v1\/ask\/[^/]+\/events$/.test(path)) return replay(req, res, ANSWERED_EVENTS);
  if ((m = path.match(/^\/v1\/answers\/([^/]+)\/watch$/)) && (method === "POST" || method === "DELETE")) {
    return json(res, 200, { answer_id: m[1], watched: method === "POST" });
  }
  if (method === "GET" && path === "/v1/stats") return json(res, 200, STUB_STATS);
  json(res, 404, { detail: "Not Found" });
}

export async function startStubGateway({ port = 0, host = "127.0.0.1" } = {}): Promise<StubGateway> {
  const server = createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on("data", (chunk: Buffer) => chunks.push(chunk));
    req.on("end", () => route(req, res, Buffer.concat(chunks).toString("utf8")));
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, host, resolve);
  });
  const address = server.address() as AddressInfo;
  return {
    url: `http://${host}:${address.port}`,
    close: () =>
      new Promise<void>((resolve, reject) => {
        server.closeAllConnections();
        server.close((err) => (err ? reject(err) : resolve()));
      }),
  };
}
