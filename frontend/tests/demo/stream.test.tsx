import { renderHook, waitFor } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { useEventStream } from "@/demo/use-event-stream";
import { DEMO_API_BASE } from "@/lib/demo/config";
import { provideRecording } from "@/lib/demo/recording";
import { replaySchedule, setReplayTiming } from "@/lib/demo/replay";
import { recordedStream, runDemoStream, type StreamEvent } from "@/lib/demo/stream";
import { resolveEventsUrl } from "@/lib/ask/format";
import type { AlertStreamEvent } from "@/lib/sse/events";

import { ANSWERED, ANSWERED_TEXT } from "../support/ask-fixtures";
import { DEMO_RECORDING } from "../support/demo-fixtures";

const ASK = DEMO_RECORDING.asks[0];
const ASK_URL = resolveEventsUrl(ASK.accepted.events_url, DEMO_API_BASE);

beforeAll(() => {
  provideRecording(DEMO_RECORDING);
  // Fast replays: the real timing makes an answer take 8 to 15 s.
  setReplayTiming({ maxTotalMs: 200, minTotalMs: 0 });
});
afterAll(() => setReplayTiming({}));

describe("recordedStream", () => {
  it("finds an ask's events by its events URL, and the alert stream", () => {
    expect(recordedStream(DEMO_RECORDING, ASK_URL)).toEqual({
      events: ASK.events,
      openEnded: false,
    });
    expect(recordedStream(DEMO_RECORDING, `${DEMO_API_BASE}/v1/alerts/stream?tenant=demo`)).toEqual(
      { events: DEMO_RECORDING.alerts, openEnded: true },
    );
    expect(
      recordedStream(DEMO_RECORDING, `${DEMO_API_BASE}/v1/alerts/stream?tenant=demo&resync=1`)
        ?.events,
    ).toEqual([]);
    expect(recordedStream(DEMO_RECORDING, `${DEMO_API_BASE}/v1/ask/nope/events`)).toBeNull();
  });
});

describe("runDemoStream", () => {
  it("replays a recorded stream in order and in full, then ends on final", async () => {
    const got: { event: StreamEvent; id: string | null }[] = [];
    const statuses: string[] = [];
    let terminal: unknown = null;
    await runDemoStream(
      ASK_URL,
      {
        event: (event, id) => got.push({ event, id }),
        status: (s) => statuses.push(s),
        terminal: (t) => {
          terminal = t;
        },
      },
      new AbortController().signal,
    );
    expect(got.map((g) => g.event)).toEqual(ASK.events.map((e) => e.data));
    expect(got.map((g) => g.id)).toEqual(ASK.events.map((e) => e.id));
    expect(statuses).toEqual(["connecting", "open"]);
    expect(terminal).toEqual({ status: "done", error: null });
  });

  it("keeps the recorded timing's order with the real schedule", () => {
    const delays = replaySchedule(ASK.events.map((e) => e.at_ms));
    expect(delays).toHaveLength(ASK.events.length);
    expect(delays.every((d) => d >= 0)).toBe(true);
  });

  it("fails a stream the recording does not hold, without inventing one", async () => {
    let terminal: unknown = null;
    await runDemoStream(
      `${DEMO_API_BASE}/v1/ask/unknown/events`,
      { event: () => undefined, status: () => undefined, terminal: (t) => (terminal = t) },
      new AbortController().signal,
    );
    expect(terminal).toMatchObject({ status: "failed", error: { code: "http_404" } });
  });
});

describe("useEventStream (demo build)", () => {
  it("builds the same state as the network hook from the replay", async () => {
    const { result } = renderHook(() => useEventStream(ASK_URL));
    await waitFor(() => expect(result.current.status).toBe("done"));
    expect(result.current.text).toBe(ANSWERED_TEXT);
    expect(result.current.final?.answer).toEqual(ANSWERED);
    expect(result.current.events.filter((e) => e.type === "token")).toEqual([]);
    expect(result.current.events.length).toBe(ASK.events.filter((e) => e.event !== "token").length);
    expect(result.current.lastEventId).toBe(ASK.events.at(-1)?.id);
  });

  it("replays the alert stream and stays open", async () => {
    const { result } = renderHook(() =>
      useEventStream<AlertStreamEvent>(`${DEMO_API_BASE}/v1/alerts/stream?tenant=demo`),
    );
    await waitFor(() => expect(result.current.events).toHaveLength(DEMO_RECORDING.alerts.length));
    expect(result.current.status).toBe("open");
  });

  it("stays idle without a URL", () => {
    const { result } = renderHook(() => useEventStream(null));
    expect(result.current.status).toBe("idle");
  });
});
