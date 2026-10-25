/**
 * The drift inbox's state: alerts streamed live from `/v1/alerts/stream`, merged with
 * the history from `GET /v1/drift/events`. Pure; no React, network or clock.
 *
 * Both sources describe the same drift events, so they are merged by `drift_event_id`
 * (the history row's `id`) and never shown twice. When the stream reports
 * `events_expired` (the alerts it missed were trimmed from the log), the inbox refetches
 * history and reconnects at the live tail (`resync`).
 */
import type { DriftEvent, DriftVerdict } from "@/lib/api/client";
import type { AlertEvent, AlertStreamEvent } from "@/lib/sse/events";

export interface DriftAlert {
  /** The drift event id (`drift_event_id` on the stream, `id` in history). */
  id: string;
  answerId: string;
  verdict: DriftVerdict;
  documentTitle: string | null;
  /** History only. */
  documentId: string | null;
  /** History only. */
  sectionPath: string | null;
  /** History only. */
  claimIdx: number | null;
  oldVersionId: string | null;
  newVersionId: string | null;
  /** The cited section in the old version; null when there was none. */
  before: string | null;
  /** The same section in the new version; null when it is gone. */
  after: string | null;
  /** ISO time of the verdict. */
  at: string;
  /** Arrived over the stream while the inbox was open. */
  live: boolean;
}

export interface InboxState {
  /** Newest first, at most `MAX_ALERTS`. */
  alerts: DriftAlert[];
  /** False until history loads, and again while it reloads after a resync. */
  historyLoaded: boolean;
  /** Bumped on `events_expired`: refetch history and reconnect at the tail. */
  resync: number;
}

export type InboxAction =
  | { type: "history"; events: DriftEvent[] }
  /** Every event the stream has delivered so far (replaying old ones is harmless). */
  | { type: "live"; events: AlertStreamEvent[] }
  | { type: "expired" };

export const MAX_ALERTS = 200;

export const INITIAL_INBOX: InboxState = { alerts: [], historyLoaded: false, resync: 0 };

function fromHistory(event: DriftEvent): DriftAlert {
  return {
    id: event.id,
    answerId: event.answer_id,
    verdict: event.verdict,
    documentTitle: event.document_title ?? null,
    documentId: event.document_id ?? null,
    sectionPath: event.section_path ?? null,
    claimIdx: event.claim_idx,
    oldVersionId: event.old_version_id ?? null,
    newVersionId: event.new_version_id ?? null,
    before: event.before ?? null,
    after: event.after ?? null,
    at: event.created_at,
    live: false,
  };
}

function fromStream(event: AlertEvent): DriftAlert {
  return {
    id: event.drift_event_id,
    answerId: event.answer_id,
    verdict: event.verdict,
    documentTitle: event.document_title,
    documentId: null,
    sectionPath: null,
    claimIdx: null,
    oldVersionId: event.old_version_id,
    newVersionId: event.new_version_id,
    before: event.before ?? null,
    after: event.after ?? null,
    at: event.t,
    live: true,
  };
}

/** One alert from both sources: every field either side knows, live if either is. */
function combine(known: DriftAlert, incoming: DriftAlert): DriftAlert {
  const merged = { ...known };
  for (const key of Object.keys(incoming) as (keyof DriftAlert)[]) {
    if (merged[key] === null && incoming[key] !== null) {
      (merged as Record<string, unknown>)[key] = incoming[key];
    }
  }
  merged.live = known.live || incoming.live;
  return merged;
}

function same(a: DriftAlert, b: DriftAlert): boolean {
  return (Object.keys(a) as (keyof DriftAlert)[]).every((key) => a[key] === b[key]);
}

function byNewest(a: DriftAlert, b: DriftAlert): number {
  const at = Date.parse(b.at) - Date.parse(a.at);
  if (at !== 0 && !Number.isNaN(at)) return at;
  return a.id < b.id ? 1 : a.id > b.id ? -1 : 0;
}

function merge(alerts: DriftAlert[], incoming: DriftAlert[]): DriftAlert[] {
  const byId = new Map(alerts.map((a) => [a.id, a]));
  let changed = false;
  for (const alert of incoming) {
    const known = byId.get(alert.id);
    const next = known ? combine(known, alert) : alert;
    if (!known || !same(known, next)) {
      byId.set(alert.id, next);
      changed = true;
    }
  }
  if (!changed) return alerts;
  return [...byId.values()].sort(byNewest).slice(0, MAX_ALERTS);
}

export function inboxReducer(state: InboxState, action: InboxAction): InboxState {
  switch (action.type) {
    case "history": {
      const alerts = merge(state.alerts, action.events.map(fromHistory));
      return { ...state, alerts, historyLoaded: true };
    }
    case "live": {
      const incoming = action.events
        .filter((e): e is AlertEvent => e.type === "alert")
        .map(fromStream);
      const alerts = merge(state.alerts, incoming);
      return alerts === state.alerts ? state : { ...state, alerts };
    }
    case "expired":
      return { ...state, historyLoaded: false, resync: state.resync + 1 };
  }
}

/**
 * The alert stream's URL. The first connection replays whatever the gateway still
 * stores. After a resync it starts at the tail: the gateway clamps a `last_event_id`
 * beyond its log to the newest id, so only new alerts follow (history covers the rest).
 * Each resync gets its own URL, which is what restarts `useEventStream`.
 */
export function alertStreamUrl(baseUrl: string, tenant: string, resync: number): string {
  const url = new URL(`${baseUrl.replace(/\/+$/, "")}/v1/alerts/stream`);
  url.searchParams.set("tenant", tenant);
  if (resync > 0) {
    url.searchParams.set("last_event_id", String(Number.MAX_SAFE_INTEGER));
    url.searchParams.set("resync", String(resync));
  }
  return url.toString();
}
