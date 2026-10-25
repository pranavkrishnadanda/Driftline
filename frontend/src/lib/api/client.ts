/**
 * Typed fetch wrapper for the Driftline gateway.
 *
 * Route types come from `schema.d.ts`, generated from `contracts/openapi.json`
 * (`npm run gen:api:file`). Routes the gateway does not serve yet are typed by hand
 * in the "pending backend" block below and nowhere else.
 */
import type { paths } from "./schema";

// ---------------------------------------------------------------------------------
// pending backend: every type and route in this block is typed from the plans, not
// from the OpenAPI document, because the gateway does not serve it yet.
//   /v1/ask, /v1/jobs/{id}                P3 T7 (shapes from agents/schemas.py)
//   /v1/answers/{id}/watch, timeline      P4 T4
//   /v1/review, /v1/review/{id}/resolve   P4 T5
//   /v1/stats                             P5b T4
// When a route lands in contracts/openapi.json, regenerate schema.d.ts, delete its
// PendingRoutes entry and derive its types from `paths` instead. Typecheck fails
// while a route is listed in both places (see `_NoPendingRouteIsGenerated`).

export type SourceKind = "openfda" | "git_docs" | "upload";
export type AnswerStatus = "answered" | "insufficient_evidence" | "refused";

export interface Citation {
  chunk_id: string;
  version_id: string;
  quote: string;
}

export interface Claim {
  idx: number;
  text: string;
  citations: Citation[];
  verified: boolean;
  reason: string | null;
}

export interface NearestSource {
  document_id: string;
  external_id: string;
  title: string;
  version_id: string;
  version_no: number;
  section_path: string;
  valid_from: string;
  valid_to: string | null;
}

export interface AnswerSchema {
  status: AnswerStatus;
  answer: string;
  claims: Claim[];
  citations: Citation[];
  dropped_claims: Claim[];
  nearest_sources: NearestSource[];
  as_of: string;
  confidence: number;
  degraded: boolean;
  cached: boolean;
  answer_id: string | null;
  cost_usd: number;
}

export interface AskRequest {
  question: string;
  tenant: string;
  as_of?: string | null;
  source_kinds?: SourceKind[] | null;
}

export interface AskAccepted {
  job_id: string;
  events_url: string;
  status_url: string;
}

export interface JobStatus {
  job_id: string;
  status: string;
  error: string | null;
  answer: AnswerSchema | null;
  cost_usd: number;
}

export interface WatchResult {
  answer_id: string;
  watched: boolean;
}

export interface TimelineVersion {
  version_id: string;
  version_no: number;
  valid_from: string;
  valid_to: string | null;
  diff_from_prev: unknown;
}

export interface TimelineRelation {
  kind: string;
  document_id: string;
  status: string;
}

export interface DocumentTimeline {
  document_id: string;
  versions: TimelineVersion[];
  relations_in: TimelineRelation[];
  relations_out: TimelineRelation[];
}

export type ReviewKind = "relation" | "broken_answer" | "low_confidence_answer";

export interface ReviewItem {
  id: string;
  kind: ReviewKind;
  ref_id: string;
  payload: Record<string, unknown>;
  status: string;
}

export interface ReviewQuery {
  tenant: string;
  kind?: ReviewKind;
}

export interface ResolveRequest {
  action: "approve" | "edit" | "reject";
  edit?: Record<string, unknown> | null;
  by: string;
}

export interface Stats {
  corpus: { documents: number; versions: number; chunks: number };
  drift_events_per_day: { day: string; count: number }[];
  ask_latency_ms: { p50: number | null; p95: number | null };
  cost_per_answer_usd: number | null;
  cache_hit_rate: number | null;
  latest_eval: Record<string, number> | null;
}

interface PendingRoutes {
  "/v1/ask": true;
  "/v1/jobs/{job_id}": true;
  "/v1/answers/{answer_id}/watch": true;
  "/v1/documents/{document_id}/timeline": true;
  "/v1/review": true;
  "/v1/review/{item_id}/resolve": true;
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

export type Health =
  paths["/healthz"]["get"]["responses"][200]["content"]["application/json"];

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

function errorCode(status: number, detail: unknown): string | null {
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const code = (detail as { code?: unknown }).code;
    if (typeof code === "string") return code;
  }
  return status === 422 ? "validation_error" : null;
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

  async function request<T>(
    method: "GET" | "POST",
    route: Route,
    init: {
      params?: Record<string, string>;
      query?: Record<string, string | undefined>;
      body?: unknown;
      signal?: AbortSignal;
    } = {},
  ): Promise<T> {
    const url = new URL(baseUrl + expand(route, init.params ?? {}));
    for (const [key, value] of Object.entries(init.query ?? {})) {
      if (value !== undefined) url.searchParams.set(key, value);
    }
    const headers: Record<string, string> = { Accept: "application/json" };
    if (init.body !== undefined) headers["Content-Type"] = "application/json";

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
    health: (opts: RequestOptions = {}) => request<Health>("GET", "/healthz", opts),

    ask: (body: AskRequest, opts: RequestOptions = {}) =>
      request<AskAccepted>("POST", "/v1/ask", { body, ...opts }),

    job: (jobId: string, opts: RequestOptions = {}) =>
      request<JobStatus>("GET", "/v1/jobs/{job_id}", { params: { job_id: jobId }, ...opts }),

    watch: (answerId: string, opts: RequestOptions = {}) =>
      request<WatchResult>("POST", "/v1/answers/{answer_id}/watch", {
        params: { answer_id: answerId },
        ...opts,
      }),

    timeline: (documentId: string, opts: RequestOptions = {}) =>
      request<DocumentTimeline>("GET", "/v1/documents/{document_id}/timeline", {
        params: { document_id: documentId },
        ...opts,
      }),

    review: (query: ReviewQuery, opts: RequestOptions = {}) =>
      request<ReviewItem[]>("GET", "/v1/review", {
        query: { tenant: query.tenant, kind: query.kind },
        ...opts,
      }),

    resolve: (itemId: string, body: ResolveRequest, opts: RequestOptions = {}) =>
      request<ReviewItem>("POST", "/v1/review/{item_id}/resolve", {
        params: { item_id: itemId },
        body,
        ...opts,
      }),

    stats: (opts: RequestOptions = {}) => request<Stats>("GET", "/v1/stats", opts),
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
