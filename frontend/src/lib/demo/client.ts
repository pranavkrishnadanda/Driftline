/**
 * The recorded demo's API client: the same interface as the gateway client, answered from
 * the recording. Nothing is invented: an ask returns the recorded ask closest to the
 * question (see `matchAsk`), and an id the recording does not hold is a 404.
 *
 * Watching and resolving review items work for the visit only (kept in memory, so they
 * survive moving between views and reset on reload); nothing is persisted anywhere.
 */
import {
  ApiError,
  type ApiClient,
  type ReviewItem,
  type ReviewQuery,
  type WatchState,
} from "../api/client";

import { setLastMatch } from "./ask-store";
import { DEMO_API_BASE } from "./config";
import { matchAsk } from "./match";
import { loadRecording, type DemoRecording } from "./recording";

interface Session {
  /** Review items resolved during this visit, by id. */
  resolved: Map<string, ReviewItem>;
  /** Watch state changed during this visit, by answer id. */
  watched: Map<string, boolean>;
}

const session: Session = { resolved: new Map(), watched: new Map() };

/** Forget what this visit resolved or (un)watched (tests). */
export function resetDemoSession(): void {
  session.resolved.clear();
  session.watched.clear();
}

async function recorded(signal: AbortSignal | undefined): Promise<DemoRecording> {
  signal?.throwIfAborted();
  const recording = await loadRecording();
  signal?.throwIfAborted();
  return recording;
}

function notFound(code: string): ApiError {
  return new ApiError(404, { code, detail: { code } });
}

function reviewItems(recording: DemoRecording, query: ReviewQuery): ReviewItem[] {
  const status = query.status ?? "open";
  const items = recording.review
    .map((item) => session.resolved.get(item.id) ?? item)
    .filter((item) => item.status === status && (!query.kind || item.kind === query.kind));
  return items.slice(0, query.limit ?? 100);
}

export function createDemoClient(): ApiClient {
  return {
    baseUrl: DEMO_API_BASE,

    health: async (opts = {}) => {
      await recorded(opts.signal);
      return { status: "ok" };
    },

    ask: async (body, opts = {}) => {
      const recording = await recorded(opts.signal);
      const match = matchAsk(body.question, body.as_of, recording.asks, recording.recorded_at);
      if (!match) throw new ApiError(503, { code: "demo_empty", detail: { code: "demo_empty" } });
      setLastMatch({ ...match, asked: { question: body.question, as_of: body.as_of ?? null } });
      return match.ask.accepted;
    },

    job: async (jobId, opts = {}) => {
      const recording = await recorded(opts.signal);
      const ask = recording.asks.find((a) => a.accepted.job_id === jobId);
      if (!ask) throw notFound("unknown_job");
      return ask.job;
    },

    watch: async (answerId, _tenant, opts = {}): Promise<WatchState> => {
      await recorded(opts.signal);
      session.watched.set(answerId, true);
      return { answer_id: answerId, watched: true };
    },

    unwatch: async (answerId, _tenant, opts = {}): Promise<WatchState> => {
      await recorded(opts.signal);
      session.watched.set(answerId, false);
      return { answer_id: answerId, watched: false };
    },

    driftEvents: async (query, opts = {}) => {
      const recording = await recorded(opts.signal);
      return { events: recording.drift_events.slice(0, query.limit ?? 100) };
    },

    timeline: async (documentId, _tenant, opts = {}) => {
      const recording = await recorded(opts.signal);
      const timeline = recording.timelines[documentId];
      if (!timeline) throw notFound("unknown_document");
      return timeline;
    },

    review: async (query = {}, opts = {}) => {
      const recording = await recorded(opts.signal);
      return { items: reviewItems(recording, query) };
    },

    resolve: async (itemId, body, _tenant, opts = {}) => {
      const recording = await recorded(opts.signal);
      const item = recording.review.find((i) => i.id === itemId);
      if (!item) throw notFound("unknown_review_item");
      if (session.resolved.has(itemId) || item.status === "resolved") {
        throw new ApiError(409, {
          code: "already_resolved",
          detail: { code: "already_resolved" },
        });
      }
      const resolved: ReviewItem = {
        ...item,
        status: "resolved",
        resolution: { action: body.action, ...(body.edit ? { edit: body.edit } : {}) },
        resolved_by: body.by,
        resolved_at: new Date().toISOString(),
      };
      session.resolved.set(itemId, resolved);
      return resolved;
    },

    stats: async (_query = {}, opts = {}) => (await recorded(opts.signal)).stats,
  };
}
