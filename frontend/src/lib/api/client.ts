/**
 * Typed fetch wrapper for the Driftline gateway.
 *
 * Route types come from `schema.d.ts`, generated from `contracts/openapi.json`
 * (`npm run gen:api:file`). Routes the gateway does not serve yet are typed by hand
 * in the "pending backend" block below and nowhere else.
 */
import type { paths } from "./schema";

// ---------------------------------------------------------------------------------
// Generated routes: typed from `paths` (schema.d.ts, from contracts/openapi.json).

type JsonResponse<
  P extends keyof paths,
  M extends keyof paths[P],
  S extends number,
> = paths[P][M] extends { responses: Record<S, { content: { "application/json": infer B } }> }
  ? B
  : never;

type JsonBody<P extends keyof paths, M extends keyof paths[P]> = paths[P][M] extends {
  requestBody: { content: { "application/json": infer B } };
}
  ? B
  : never;

export type Health = JsonResponse<"/healthz", "get", 200>;
export type AskRequest = JsonBody<"/v1/ask", "post">;
export type AskAccepted = JsonResponse<"/v1/ask", "post", 202>;
export type JobStatus = JsonResponse<"/v1/jobs/{job_id}", "get", 200>;
export type AnswerSchema = NonNullable<JobStatus["answer"]>;
export type AnswerStatus = AnswerSchema["status"];
export type Claim = AnswerSchema["claims"][number];
export type Citation = Claim["citations"][number];
export type NearestSource = AnswerSchema["nearest_sources"][number];
export type SourceKind = NonNullable<AskRequest["source_kinds"]>[number];

/**
 * The query string of a generated route, e.g. `{ tenant?: string | null; limit?: number }`.
 * Since P6 T0 every tenant-scoped route's query is optional (a bearer key can name the
 * tenant instead), so the generated `query` key itself is optional.
 */
type QueryParams<P extends keyof paths, M extends keyof paths[P]> = paths[P][M] extends {
  parameters: { query?: infer Q };
}
  ? NonNullable<Q>
  : never;

/** Answer watch state; POST and DELETE on the watch route both return it. */
export type WatchState = JsonResponse<"/v1/answers/{answer_id}/watch", "post", 200>;
export type DocumentTimeline = JsonResponse<"/v1/documents/{document_id}/timeline", "get", 200>;
export type TimelineVersion = DocumentTimeline["versions"][number];
export type TimelineRelation = DocumentTimeline["relations"]["outgoing"][number];
export type DriftEventsQuery = QueryParams<"/v1/drift/events", "get">;
export type DriftEventList = JsonResponse<"/v1/drift/events", "get", 200>;
export type DriftEvent = DriftEventList["events"][number];
export type DriftVerdict = DriftEvent["verdict"];
export type ReviewQuery = QueryParams<"/v1/review", "get">;
export type ReviewItemList = JsonResponse<"/v1/review", "get", 200>;
export type ReviewItem = ReviewItemList["items"][number];
export type ReviewKind = ReviewItem["kind"];
export type ResolveRequest = JsonBody<"/v1/review/{item_id}/resolve", "post">;

// ---------------------------------------------------------------------------------
// pending backend: every type and route in this block is typed from the plans, not
// from the OpenAPI document, because the gateway does not serve it yet.
//   /v1/stats                             P5b T4
// When a route lands in contracts/openapi.json, regenerate schema.d.ts, delete its
// PendingRoutes entry and derive its types from `paths` instead. Typecheck fails
// while a route is listed in both places (see `_NoPendingRouteIsGenerated`).

export interface Stats {
  corpus: { documents: number; versions: number; chunks: number };
  drift_events_per_day: { day: string; count: number }[];
  ask_latency_ms: { p50: number | null; p95: number | null };
  cost_per_answer_usd: number | null;
  cache_hit_rate: number | null;
  latest_eval: Record<string, number> | null;
}

interface PendingRoutes {
  "/v1/stats": true;
}

// end pending backend
// ---------------------------------------------------------------------------------

type _NoPendingRouteIsGenerated = Extract<keyof PendingRoutes, keyof paths>;
const _pendingRoutesAreNotGenerated: [_NoPendingRouteIsGenerated] extends [never] ? true : false =
  true;
void _pendingRoutesAreNotGenerated;

/** A route template the client may call: generated from OpenAPI, or pending backend. */
type Route = keyof paths | keyof PendingRoutes;

/** Every failed call rejects with this, except an abort (which keeps its AbortError). */
export class ApiError extends Error {
  /** The HTTP status, or 0 when no response arrived (refused, DNS, CORS, reset). */
  readonly status: number;
  /** Seconds to wait before retrying, from `Retry-After`; null when absent or invalid. */
  readonly retryAfter: number | null;
  /** `detail.code` from the gateway, `validation_error` for 422, or a client-side code. */
  readonly code: string | null;
  /** The parsed error body's `detail` (or the raw text when the body is not JSON). */
  readonly detail: unknown;

  constructor(
    status: number,
    init: { retryAfter?: number | null; code?: string | null; detail?: unknown; cause?: unknown },
  ) {
    super(
      status === 0
        ? "Driftline API unreachable"
        : `Driftline API error ${status}${init.code ? ` (${init.code})` : ""}`,
      { cause: init.cause },
    );
    this.name = "ApiError";
    this.status = status;
    this.retryAfter = init.retryAfter ?? null;
    this.code = init.code ?? null;
    this.detail = init.detail;
  }
}

/** `Retry-After` as whole seconds: delay-seconds, or an HTTP date relative to `now`. */
export function parseRetryAfter(value: string | null, now: number = Date.now()): number | null {
  const text = value?.trim();
  if (!text) return null;
  if (/^\d+$/.test(text)) return Number(text);
  if (!/[a-z]/i.test(text)) return null;
  const at = Date.parse(text);
  if (Number.isNaN(at)) return null;
  return Math.max(0, Math.ceil((at - now) / 1000));
}

export interface RequestOptions {
  signal?: AbortSignal;
}

export interface ApiClientOptions {
  /** Defaults to NEXT_PUBLIC_DRIFTLINE_API, then http://localhost:8010. */
  baseUrl?: string;
  /**
   * A per-tenant API key, sent as `Authorization: Bearer <key>` on every call and never
   * put in a URL (query strings end up in access logs). Without one the gateway goes by
   * the `tenant` name (dev mode). With one, `tenant` may be left out; when it is given
   * it must be the key's tenant, or the call fails with 403 `tenant_mismatch`.
   */
  apiKey?: string;
}

const DEFAULT_BASE_URL = "http://localhost:8010";

function isAbort(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

function expand(route: Route, params: Record<string, string>): string {
  return route.replace(/\{(\w+)\}/g, (_, name: string) => {
    const value = params[name];
    if (value === undefined) throw new Error(`missing path parameter ${name} for ${route}`);
    return encodeURIComponent(value);
  });
}

/**
 * The code for a failed status whose body names none. 401 and 403 take the gateway's
 * own auth codes (P6 T0): 401 is a missing or invalid API key, and 403 has one meaning
 * in the contract, a key that is not the named tenant's.
 */
const STATUS_CODES: Record<number, string> = {
  401: "unauthorized",
  403: "tenant_mismatch",
  422: "validation_error",
};

function errorCode(status: number, detail: unknown): string | null {
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const code = (detail as { code?: unknown }).code;
    if (typeof code === "string") return code;
  }
  return STATUS_CODES[status] ?? null;
}

function errorDetail(text: string): unknown {
  try {
    const body: unknown = JSON.parse(text);
    if (body && typeof body === "object" && "detail" in body) return body.detail;
    return body;
  } catch {
    return text;
  }
}

export function createApiClient(options: ApiClientOptions = {}) {
  const baseUrl = (
    options.baseUrl ??
    process.env.NEXT_PUBLIC_DRIFTLINE_API ??
    DEFAULT_BASE_URL
  ).replace(/\/+$/, "");
  const apiKey = options.apiKey?.trim() || null;

  async function request<T>(
    method: "GET" | "POST" | "DELETE",
    route: Route,
    init: {
      params?: Record<string, string>;
      query?: Record<string, string | number | null | undefined>;
      body?: unknown;
      signal?: AbortSignal;
    } = {},
  ): Promise<T> {
    const url = new URL(baseUrl + expand(route, init.params ?? {}));
    for (const [key, value] of Object.entries(init.query ?? {})) {
      if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
    }
    const headers: Record<string, string> = { Accept: "application/json" };
    if (init.body !== undefined) headers["Content-Type"] = "application/json";
    if (apiKey) headers.Authorization = `Bearer ${apiKey}`;

    let response: Response;
    let text: string;
    try {
      response = await fetch(url, {
        method,
        headers,
        body: init.body === undefined ? undefined : JSON.stringify(init.body),
        signal: init.signal,
      });
      text = await response.text();
    } catch (error) {
      if (isAbort(error)) throw error;
      throw new ApiError(0, { code: "network_error", cause: error });
    }

    if (!response.ok) {
      const detail = errorDetail(text);
      throw new ApiError(response.status, {
        retryAfter: parseRetryAfter(response.headers.get("Retry-After")),
        code: errorCode(response.status, detail),
        detail,
      });
    }
    try {
      return JSON.parse(text) as T;
    } catch (error) {
      throw new ApiError(response.status, { code: "invalid_json", detail: text, cause: error });
    }
  }

  return {
    /** The gateway origin this client calls; relative URLs it returns resolve against it. */
    baseUrl,

    health: (opts: RequestOptions = {}) => request<Health>("GET", "/healthz", opts),

    ask: (body: AskRequest, opts: RequestOptions = {}) =>
      request<AskAccepted>("POST", "/v1/ask", { body, ...opts }),

    job: (jobId: string, opts: RequestOptions = {}) =>
      request<JobStatus>("GET", "/v1/jobs/{job_id}", { params: { job_id: jobId }, ...opts }),

    /** Re-check the answer whenever a document it cites changes. */
    watch: (answerId: string, tenant?: string | null, opts: RequestOptions = {}) =>
      request<WatchState>("POST", "/v1/answers/{answer_id}/watch", {
        params: { answer_id: answerId },
        query: { tenant },
        ...opts,
      }),

    unwatch: (answerId: string, tenant?: string | null, opts: RequestOptions = {}) =>
      request<WatchState>("DELETE", "/v1/answers/{answer_id}/watch", {
        params: { answer_id: answerId },
        query: { tenant },
        ...opts,
      }),

    /** Drift verdicts on the tenant's answers, latest first. */
    driftEvents: (query: DriftEventsQuery, opts: RequestOptions = {}) =>
      request<DriftEventList>("GET", "/v1/drift/events", {
        query: { tenant: query.tenant, limit: query.limit },
        ...opts,
      }),

    timeline: (documentId: string, tenant?: string | null, opts: RequestOptions = {}) =>
      request<DocumentTimeline>("GET", "/v1/documents/{document_id}/timeline", {
        params: { document_id: documentId },
        query: { tenant },
        ...opts,
      }),

    /** The tenant's review items, oldest first. */
    review: (query: ReviewQuery = {}, opts: RequestOptions = {}) =>
      request<ReviewItemList>("GET", "/v1/review", {
        query: { tenant: query.tenant, kind: query.kind, status: query.status, limit: query.limit },
        ...opts,
      }),

    /** Approve, edit or reject a review item. An already-resolved item is a 409 `ApiError`. */
    resolve: (
      itemId: string,
      body: ResolveRequest,
      tenant?: string | null,
      opts: RequestOptions = {},
    ) =>
      request<ReviewItem>("POST", "/v1/review/{item_id}/resolve", {
        params: { item_id: itemId },
        query: { tenant },
        body,
        ...opts,
      }),

    stats: (opts: RequestOptions = {}) => request<Stats>("GET", "/v1/stats", opts),
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
