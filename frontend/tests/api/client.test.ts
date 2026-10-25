// @vitest-environment node
import { afterEach, describe, expect, expectTypeOf, it } from "vitest";

import {
  ApiError,
  createApiClient,
  parseRetryAfter,
  type AnswerSchema,
  type AskAccepted,
  type DocumentTimeline,
  type DriftEventList,
  type JobStatus,
  type ReviewItem,
  type Stats,
  type WatchState,
} from "@/lib/api/client";

import { closedPortUrl, startApiServer, type ApiServer } from "../support/api-server";

const JOB_ID = "6f1c2b0e-3c1a-4c55-9a77-0d4d1d6b2f10";
const ANSWER_ID = "0b8e2f7a-5d36-4a3c-8f61-2a9c4e1d7b55";
const DOC_ID = "c3a1e9d2-7b44-4f0e-9e1a-5f2d8c6b4a33";
const ITEM_ID = "9d4b7c1e-2a5f-4e8b-b3c6-1f0a2e9d8c77";

const CITATION = {
  chunk_id: DOC_ID,
  version_id: DOC_ID,
  quote: "10 mg once daily",
  document_id: DOC_ID,
  title: "Acme tablets label",
  external_id: "acme-label",
  version_no: 3,
  section_path: "Dosage",
  valid_from: "2023-02-14T00:00:00Z",
  valid_to: null,
};

const answer = {
  status: "answered",
  answer: "Take 10 mg once daily.",
  claims: [
    {
      idx: 0,
      text: "Take 10 mg once daily.",
      citations: [CITATION],
      verified: true,
      reason: null,
    },
  ],
  citations: [CITATION],
  dropped_claims: [],
  nearest_sources: [],
  as_of: "2026-10-01T00:00:00Z",
  confidence: 0.92,
  degraded: false,
  cached: false,
  answer_id: ANSWER_ID,
  cost_usd: 0.0031,
} satisfies AnswerSchema;

const accepted = {
  job_id: JOB_ID,
  events_url: `/v1/jobs/${JOB_ID}/events`,
  status_url: `/v1/jobs/${JOB_ID}`,
} satisfies AskAccepted;

const job = {
  job_id: JOB_ID,
  status: "succeeded",
  error: null,
  answer,
  cost_usd: 0.0031,
} satisfies JobStatus;

const V1_ID = "1a2b3c4d-0000-4000-8000-000000000001";
const V2_ID = "1a2b3c4d-0000-4000-8000-000000000002";
const OTHER_DOC_ID = "e7f6a5b4-3c2d-4e1f-9a8b-7c6d5e4f3a21";
const DRIFT_ID = "5e6f7a8b-9c0d-4e1f-a2b3-c4d5e6f7a8b9";

const timeline = {
  document_id: DOC_ID,
  external_id: "acme-label",
  title: "Acme tablets label",
  versions: [
    {
      version_id: V1_ID,
      version_no: 1,
      version_key: "2026-01",
      valid_from: "2026-01-01T00:00:00Z",
      valid_to: "2026-06-01T00:00:00Z",
      diff_from_prev: null,
      created_at: "2026-01-01T00:00:05Z",
    },
    {
      version_id: V2_ID,
      version_no: 2,
      version_key: null,
      valid_from: "2026-06-01T00:00:00Z",
      valid_to: null,
      diff_from_prev: { changed_sections: ["Dosage"] },
      created_at: "2026-06-01T00:00:05Z",
    },
  ],
  relations: {
    outgoing: [
      {
        id: ITEM_ID,
        kind: "supersedes",
        status: "approved",
        confidence: 0.9,
        src_version_id: V2_ID,
        document_id: OTHER_DOC_ID,
        document_title: "Acme tablets label (2025)",
      },
    ],
    incoming: [],
  },
} satisfies DocumentTimeline;

const driftEvents = {
  events: [
    {
      id: DRIFT_ID,
      answer_id: ANSWER_ID,
      claim_idx: 0,
      verdict: "changed",
      before: "Take 10 mg once daily.",
      after: "Take 5 mg once daily.",
      diff: "-10 mg\n+5 mg",
      section_path: "Dosage",
      old_version_id: V1_ID,
      new_version_id: V2_ID,
      document_id: DOC_ID,
      document_title: "Acme tablets label",
      created_at: "2026-06-01T00:01:00Z",
    },
  ],
} satisfies DriftEventList;

const item = {
  id: ITEM_ID,
  kind: "low_confidence_answer",
  ref_id: ANSWER_ID,
  payload: { confidence: 0.41 },
  status: "open",
} satisfies ReviewItem;

const stats = {
  corpus: { documents: 12, versions: 30, chunks: 900 },
  drift_events_per_day: [{ day: "2026-10-24", count: 3 }],
  ask_latency_ms: { p50: 1800, p95: 5200 },
  cost_per_answer_usd: 0.004,
  cache_hit_rate: 0.25,
  latest_eval: null,
} satisfies Stats;

let server: ApiServer | undefined;

afterEach(async () => {
  await server?.close();
  server = undefined;
});

async function rejection(promise: Promise<unknown>): Promise<ApiError> {
  const error = await promise.then(
    () => {
      throw new Error("expected the call to reject");
    },
    (e: unknown) => e,
  );
  expect(error).toBeInstanceOf(ApiError);
  return error as ApiError;
}

describe("api client: success", () => {
  it("ask() posts the question as JSON and returns the typed 202 body", async () => {
    server = await startApiServer({ "POST /v1/ask": { status: 202, json: accepted } });
    const api = createApiClient({ baseUrl: server.url });

    const result = await api.ask({ question: "What is the dose?", tenant: "acme" });

    expectTypeOf(result).toEqualTypeOf<AskAccepted>();
    expect(result).toEqual(accepted);
    const [req] = server.requests;
    expect(req.method).toBe("POST");
    expect(req.headers["content-type"]).toBe("application/json");
    expect(JSON.parse(req.body)).toEqual({ question: "What is the dose?", tenant: "acme" });
  });

  it("job() returns the job with its typed answer", async () => {
    server = await startApiServer({ [`GET /v1/jobs/${JOB_ID}`]: { status: 200, json: job } });
    const result = await createApiClient({ baseUrl: server.url }).job(JOB_ID);

    expectTypeOf(result).toEqualTypeOf<JobStatus>();
    expect(result.answer?.claims[0].citations[0].quote).toBe("10 mg once daily");
  });

  it("watch(), timeline(), review(), resolve() and stats() hit their routes", async () => {
    server = await startApiServer({
      [`POST /v1/answers/${ANSWER_ID}/watch`]: {
        status: 200,
        json: { answer_id: ANSWER_ID, watched: true },
      },
      [`GET /v1/documents/${DOC_ID}/timeline`]: { status: 200, json: timeline },
      "GET /v1/review": { status: 200, json: [item] },
      [`POST /v1/review/${ITEM_ID}/resolve`]: {
        status: 200,
        json: { ...item, status: "resolved" },
      },
      "GET /v1/stats": { status: 200, json: stats },
    });
    const api = createApiClient({ baseUrl: server.url });

    const watched = await api.watch(ANSWER_ID, "acme");
    expectTypeOf(watched).toEqualTypeOf<WatchState>();
    expect(watched.watched).toBe(true);

    const docTimeline = await api.timeline(DOC_ID, "acme");
    expectTypeOf(docTimeline).toEqualTypeOf<DocumentTimeline>();
    expect(docTimeline).toEqual(timeline);
    expect(docTimeline.relations.outgoing[0].document_id).toBe(OTHER_DOC_ID);
    expect((await api.review({ tenant: "acme", kind: "relation" }))[0].id).toBe(ITEM_ID);
    const resolved = await api.resolve(ITEM_ID, { action: "approve", by: "reviewer@acme" });
    expectTypeOf(resolved).toEqualTypeOf<ReviewItem>();
    expect(resolved.status).toBe("resolved");
    expect((await api.stats()).ask_latency_ms.p95).toBe(5200);

    expect(server.requests.map((r) => `${r.method} ${r.url}`)).toEqual([
      `POST /v1/answers/${ANSWER_ID}/watch?tenant=acme`,
      `GET /v1/documents/${DOC_ID}/timeline?tenant=acme`,
      "GET /v1/review?tenant=acme&kind=relation",
      `POST /v1/review/${ITEM_ID}/resolve`,
      "GET /v1/stats",
    ]);
    expect(JSON.parse(server.requests[3].body)).toEqual({
      action: "approve",
      by: "reviewer@acme",
    });
  });

  it("unwatch() sends DELETE with the tenant and returns the watch state", async () => {
    server = await startApiServer({
      [`DELETE /v1/answers/${ANSWER_ID}/watch`]: {
        status: 200,
        json: { answer_id: ANSWER_ID, watched: false },
      },
    });
    const result = await createApiClient({ baseUrl: server.url }).unwatch(ANSWER_ID, "acme");

    expectTypeOf(result).toEqualTypeOf<WatchState>();
    expect(result).toEqual({ answer_id: ANSWER_ID, watched: false });
    const [req] = server.requests;
    expect(`${req.method} ${req.url}`).toBe(`DELETE /v1/answers/${ANSWER_ID}/watch?tenant=acme`);
    expect(req.body).toBe("");
  });

  it("driftEvents() sends tenant and limit and returns the typed event list", async () => {
    server = await startApiServer({ "GET /v1/drift/events": { status: 200, json: driftEvents } });
    const api = createApiClient({ baseUrl: server.url });

    const result = await api.driftEvents({ tenant: "acme", limit: 20 });
    expectTypeOf(result).toEqualTypeOf<DriftEventList>();
    expect(result).toEqual(driftEvents);
    expect(result.events[0].verdict).toBe("changed");

    await api.driftEvents({ tenant: "acme" });
    expect(server.requests.map((r) => r.url)).toEqual([
      "/v1/drift/events?tenant=acme&limit=20",
      "/v1/drift/events?tenant=acme",
    ]);
  });

  it("health() is typed from the generated OpenAPI schema", async () => {
    server = await startApiServer({ "GET /healthz": { status: 200, json: { status: "ok" } } });
    const result = await createApiClient({ baseUrl: server.url }).health();

    expectTypeOf(result).toEqualTypeOf<{ [key: string]: string }>();
    expect(result).toEqual({ status: "ok" });
  });

  it("encodes path segments", async () => {
    server = await startApiServer({ "GET /v1/jobs/a%2Fb": { status: 200, json: job } });
    await createApiClient({ baseUrl: server.url }).job("a/b");
    expect(server.requests[0].url).toBe("/v1/jobs/a%2Fb");
  });

  it("exposes its base URL without a trailing slash, for resolving events_url", () => {
    expect(createApiClient({ baseUrl: "http://127.0.0.1:9/" }).baseUrl).toBe("http://127.0.0.1:9");
  });
});

describe("api client: error mapping", () => {
  it("maps 404 to ApiError with the backend's error code", async () => {
    server = await startApiServer({
      "POST /v1/ask": { status: 404, json: { detail: { code: "unknown_tenant" } } },
    });
    const error = await rejection(
      createApiClient({ baseUrl: server.url }).ask({ question: "q", tenant: "nope" }),
    );

    expect(error.status).toBe(404);
    expect(error.code).toBe("unknown_tenant");
    expect(error.retryAfter).toBeNull();
  });

  it("maps 422 to ApiError carrying the validation detail", async () => {
    const detail = [{ loc: ["body", "question"], msg: "Field required", type: "missing" }];
    server = await startApiServer({ "POST /v1/ask": { status: 422, json: { detail } } });
    const error = await rejection(
      createApiClient({ baseUrl: server.url }).ask({ question: "", tenant: "acme" }),
    );

    expect(error.status).toBe(422);
    expect(error.code).toBe("validation_error");
    expect(error.detail).toEqual(detail);
  });

  it("maps a non-JSON error body to ApiError without a code", async () => {
    server = await startApiServer({ "GET /v1/stats": { status: 502, raw: "Bad Gateway" } });
    const error = await rejection(createApiClient({ baseUrl: server.url }).stats());

    expect(error.status).toBe(502);
    expect(error.code).toBeNull();
    expect(error.detail).toBe("Bad Gateway");
  });

  it("maps 429 with Retry-After in seconds", async () => {
    server = await startApiServer({
      "POST /v1/ask": {
        status: 429,
        json: { detail: { code: "backpressure", backlog: 250 } },
        headers: { "Retry-After": "7" },
      },
    });
    const error = await rejection(
      createApiClient({ baseUrl: server.url }).ask({ question: "q", tenant: "acme" }),
    );

    expect(error.status).toBe(429);
    expect(error.code).toBe("backpressure");
    expect(error.retryAfter).toBe(7);
  });

  it("maps 429 with Retry-After as an HTTP date", async () => {
    const at = new Date(Date.now() + 30_000).toUTCString();
    server = await startApiServer({
      "POST /v1/ask": { status: 429, json: { detail: {} }, headers: { "Retry-After": at } },
    });
    const error = await rejection(
      createApiClient({ baseUrl: server.url }).ask({ question: "q", tenant: "acme" }),
    );

    expect(error.status).toBe(429);
    expect(error.retryAfter).toBeGreaterThanOrEqual(28);
    expect(error.retryAfter).toBeLessThanOrEqual(30);
  });

  it("maps a refused connection to ApiError status 0", async () => {
    const api = createApiClient({ baseUrl: await closedPortUrl() });
    const error = await rejection(api.stats());

    expect(error.status).toBe(0);
    expect(error.code).toBe("network_error");
    expect(error.retryAfter).toBeNull();
    expect(error.cause).toBeInstanceOf(Error);
  });

  it("maps a 200 with an unparseable body to ApiError", async () => {
    server = await startApiServer({ "GET /v1/stats": { status: 200, raw: "not json" } });
    const error = await rejection(createApiClient({ baseUrl: server.url }).stats());

    expect(error.status).toBe(200);
    expect(error.code).toBe("invalid_json");
  });

  it("lets an aborted request reject with the AbortError, not ApiError", async () => {
    server = await startApiServer({ "GET /v1/stats": { status: 200, json: stats } });
    const controller = new AbortController();
    controller.abort();
    const error = await createApiClient({ baseUrl: server.url })
      .stats({ signal: controller.signal })
      .catch((e: unknown) => e);

    expect(error).not.toBeInstanceOf(ApiError);
    expect((error as Error).name).toBe("AbortError");
  });
});

describe("parseRetryAfter", () => {
  const now = Date.parse("2026-10-25T12:00:00Z");

  it("reads delay-seconds", () => {
    expect(parseRetryAfter("0", now)).toBe(0);
    expect(parseRetryAfter(" 120 ", now)).toBe(120);
  });

  it("reads an HTTP date relative to now, rounding up", () => {
    expect(parseRetryAfter("Sun, 25 Oct 2026 12:00:45 GMT", now)).toBe(45);
    expect(parseRetryAfter("Sun, 25 Oct 2026 12:00:45 GMT", now + 500)).toBe(45);
  });

  it("clamps a date in the past to 0", () => {
    expect(parseRetryAfter("Sun, 25 Oct 2026 11:59:00 GMT", now)).toBe(0);
  });

  it("returns null for a missing or malformed header", () => {
    expect(parseRetryAfter(null, now)).toBeNull();
    expect(parseRetryAfter("", now)).toBeNull();
    expect(parseRetryAfter("-5", now)).toBeNull();
    expect(parseRetryAfter("1.5", now)).toBeNull();
    expect(parseRetryAfter("soon", now)).toBeNull();
  });
});
