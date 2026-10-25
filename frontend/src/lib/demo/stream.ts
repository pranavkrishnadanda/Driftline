/**
 * The demo build's SSE transport: `useEventStream` hands it the same sink as the network
 * loop, and it replays the recorded events for the URL in order and in full.
 */
import type { ErrorEvent } from "@/lib/sse/events";

import { loadRecording, type DemoRecording, type RecordedEvent } from "./recording";
import { replaySchedule, replayTiming, sleep, type ReplayTiming } from "./replay";

/** Any SSE event: a JSON object with a `type` (as `useEventStream` takes it). */
export interface StreamEvent {
  type: string;
}

export type Terminal = { status: "done" | "expired" | "failed"; error: ErrorEvent | null };

/** Where a replay delivers: the same three channels as `useEventStream`'s network loop. */
export interface StreamSink<E extends StreamEvent> {
  event: (event: E, id: string | null) => void;
  status: (status: "connecting" | "open" | "reconnecting") => void;
  terminal: (terminal: Terminal) => void;
}

function clientError(code: string, message: string): ErrorEvent {
  return { type: "error", code, message, retryable: false };
}

export interface RecordedStream {
  events: RecordedEvent[];
  /** The alert stream stays open after its replay, like the gateway's. */
  openEnded: boolean;
}

/** The recording behind an SSE URL built from the demo client's base URL, or null. */
export function recordedStream(recording: DemoRecording, url: string): RecordedStream | null {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (parsed.pathname === "/v1/alerts/stream") {
    // A resync reconnects at the tail: nothing new has happened since the recording.
    const resync = Number(parsed.searchParams.get("resync") ?? 0);
    return { events: resync > 0 ? [] : recording.alerts, openEnded: true };
  }
  const ask = recording.asks.find(
    (a) =>
      new URL(a.accepted.events_url, `${parsed.protocol}//${parsed.host}/`).pathname ===
      parsed.pathname,
  );
  return ask ? { events: ask.events, openEnded: false } : null;
}

/** Replay the recorded stream for `url` into `sink` until it ends or `signal` aborts. */
export async function runDemoStream<E extends StreamEvent>(
  url: string,
  sink: StreamSink<E>,
  signal: AbortSignal,
  timing: ReplayTiming = replayTiming,
): Promise<void> {
  sink.status("connecting");
  let recording: DemoRecording;
  try {
    recording = await loadRecording();
  } catch (error) {
    if (signal.aborted) return;
    sink.terminal({
      status: "failed",
      error: clientError(
        "demo_unavailable",
        error instanceof Error ? error.message : String(error),
      ),
    });
    return;
  }
  if (signal.aborted) return;
  const stream = recordedStream(recording, url);
  if (!stream) {
    sink.terminal({
      status: "failed",
      error: clientError("http_404", "this demo has no recording of that stream"),
    });
    return;
  }

  sink.status("open");
  const delays = replaySchedule(
    stream.events.map((e) => e.at_ms),
    timing,
  );
  for (const [i, recorded] of stream.events.entries()) {
    await sleep(delays[i], signal);
    if (signal.aborted) return;
    const event = recorded.data as E;
    sink.event(event, recorded.id);
    if (event.type === "final") {
      sink.terminal({ status: "done", error: null });
      return;
    }
    const error = event as unknown as ErrorEvent;
    if (event.type === "error" && !error.retryable) {
      sink.terminal({
        status: error.code === "events_expired" ? "expired" : "failed",
        error,
      });
      return;
    }
  }
  // Open-ended (alerts), or an ask that was still waiting when recorded: stay connected.
  await new Promise<void>((resolve) => {
    if (signal.aborted) return resolve();
    signal.addEventListener("abort", () => resolve(), { once: true });
  });
}
