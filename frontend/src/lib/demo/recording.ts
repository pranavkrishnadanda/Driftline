/**
 * The recorded demo's bundle: every response a real run of the stack returned, captured
 * by `scripts/capture-demo.ts` and replayed by the demo client and stream.
 */
import type {
  AskAccepted,
  AskRequest,
  DocumentTimeline,
  DriftEvent,
  JobStatus,
  ReviewItem,
  Stats,
} from "@/lib/api/client";

import { DEMO_BASE_PATH, DEMO_RECORDING_FILE } from "./config";

/** One SSE event as it arrived: `at_ms` after the stream was opened. */
export interface RecordedEvent {
  at_ms: number;
  id: string | null;
  event: string;
  data: unknown;
}

export interface RecordedAsk {
  /** The request exactly as it was sent (tenant included). */
  request: AskRequest;
  accepted: AskAccepted;
  /** The whole `GET /v1/ask/{id}/events` stream, in arrival order. */
  events: RecordedEvent[];
  /** `GET /v1/jobs/{id}` once the stream ended. */
  job: JobStatus;
}

export interface DemoRecording {
  version: 1;
  /** ISO time the capture finished. */
  recorded_at: string;
  /** How the data was produced, in a sentence (e.g. models and corpus). */
  source: string;
  tenant: string;
  asks: RecordedAsk[];
  /** `GET /v1/drift/events`, latest first. */
  drift_events: DriftEvent[];
  /** The alert stream (`GET /v1/alerts/stream`) as it replayed. */
  alerts: RecordedEvent[];
  /** `GET /v1/review` (every kind and status). */
  review: ReviewItem[];
  /** `GET /v1/documents/{id}/timeline` per document id. */
  timelines: Record<string, DocumentTimeline>;
  stats: Stats;
}

let cached: Promise<DemoRecording> | null = null;

/** The recording, fetched once per page load. */
export function loadRecording(): Promise<DemoRecording> {
  if (!cached) {
    cached = fetch(`${DEMO_BASE_PATH}${DEMO_RECORDING_FILE}`).then(async (response) => {
      if (!response.ok) throw new Error(`demo recording returned ${response.status}`);
      return (await response.json()) as DemoRecording;
    });
    // A failed load may be retried (the next call fetches again).
    cached.catch(() => {
      cached = null;
    });
  }
  return cached;
}

/** Use this recording instead of fetching one (tests and scripts that already hold it). */
export function provideRecording(recording: DemoRecording): void {
  cached = Promise.resolve(recording);
}
