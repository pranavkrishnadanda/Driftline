/**
 * A demo recording assembled from the contract and stub fixtures, for testing the demo
 * transport and build without a captured run. It is test data only: the shipped demo
 * replays `public/demo/recording.json`, captured from a real run by
 * `scripts/capture-demo.ts`.
 */
import type { AskRequest } from "@/lib/api/client";
import type { DemoRecording, RecordedAsk, RecordedEvent } from "@/lib/demo/recording";

import { ANSWERED, ANSWERED_EVENTS } from "./ask-fixtures";
import { alertFrame } from "./drift-fixtures";
import type { FixtureEvent } from "./sse-server";
import { STUB_ALERT, STUB_DRIFT_EVENTS, STUB_REVIEW_ITEMS, STUB_STATS } from "./stub-gateway";
import { DOC_ID, TIMELINE } from "./version-timeline-fixtures";

/** Each fixture event `stepMs` after the previous one. */
export function timed(events: FixtureEvent[], stepMs: number): RecordedEvent[] {
  return events.map((e, i) => ({
    at_ms: (i + 1) * stepMs,
    id: e.id === null ? null : String(e.id),
    event: e.event,
    data: e.data,
  }));
}

function recordedAsk(n: number, request: AskRequest): RecordedAsk {
  const jobId = `00000000-0000-4000-8000-00000000000${n}`;
  return {
    request,
    accepted: {
      job_id: jobId,
      events_url: `/v1/ask/${jobId}/events`,
      status_url: `/v1/jobs/${jobId}`,
    },
    events: timed(ANSWERED_EVENTS, 40),
    job: { job_id: jobId, status: "done", answer: ANSWERED, cost_usd: 0 } as RecordedAsk["job"],
  };
}

export const DEMO_RECORDING: DemoRecording = {
  version: 1,
  recorded_at: "2026-10-25T12:00:00Z",
  source: "test fixtures",
  tenant: "demo",
  asks: [
    recordedAsk(1, {
      question: "How often should ALT be checked?",
      tenant: "demo",
      as_of: "2024-06-01T00:00:00Z",
    }),
    recordedAsk(2, { question: "How often should ALT be checked?", tenant: "demo" }),
    recordedAsk(3, { question: "What is the maximum daily dose of metformin?", tenant: "demo" }),
  ],
  drift_events: STUB_DRIFT_EVENTS,
  alerts: timed([alertFrame(1, STUB_ALERT)], 10),
  review: STUB_REVIEW_ITEMS,
  timelines: { [DOC_ID]: TIMELINE },
  stats: STUB_STATS,
};
