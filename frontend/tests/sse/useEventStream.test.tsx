import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { AlertStreamEvent, AskEvent } from "@/lib/sse/events";
import { useEventStream } from "@/lib/sse/useEventStream";

import answered from "../fixtures/sse/ask-answered.json";
import expired from "../fixtures/sse/ask-expired.json";
import { EXPIRED_FRAME, alert, alertFrame } from "../support/drift-fixtures";
import {
  startSseServer,
  tokenBurst,
  type FixtureEvent,
  type SseServer,
} from "../support/sse-server";

const ANSWERED = answered.events as FixtureEvent[];
const EXPIRED = expired.events as FixtureEvent[];
const ANSWERED_TEXT = ANSWERED.filter((e) => e.event === "token")
  .map((e) => (e.data as { text: string }).text)
  .join("");
const NON_TOKEN_TYPES = ANSWERED.filter((e) => e.event !== "token").map((e) => e.event);

let server: SseServer | undefined;

afterEach(async () => {
  await server?.close();
  server = undefined;
});

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const FAST = { initialRetryMs: 10, maxRetryMs: 50 };

describe("useEventStream", () => {
  it("streams a contract fixture to completion", async () => {
    server = await startSseServer({ events: ANSWERED, retryMs: 10, chunkSize: 7 });
    const { result } = renderHook(() => useEventStream(server!.url, FAST));

    await waitFor(() => expect(result.current.status).toBe("done"));
    expect(result.current.text).toBe(ANSWERED_TEXT);
    expect(result.current.events.map((e: AskEvent) => e.type)).toEqual(NON_TOKEN_TYPES);
    expect(result.current.final?.answer.status).toBe("answered");
    expect(result.current.lastEventId).toBe("17");
    expect(server.connections).toHaveLength(1);
    expect(server.connections[0].lastEventId).toBeNull();
  });

  it("resumes with Last-Event-ID after the server drops mid-stream, without duplicates or gaps", async () => {
    server = await startSseServer({
      events: ANSWERED,
      retryMs: 10,
      connections: [
        { dropAfter: 5, drop: "destroy" },
        { dropAfter: 6, drop: "end", overlap: 3 },
      ],
    });
    const { result } = renderHook(() => useEventStream(server!.url, FAST));

    await waitFor(() => expect(result.current.status).toBe("done"));
    expect(server.connections.map((c) => c.lastEventId)).toEqual([null, "5", "8"]);
    // The second connection re-sent ids 3-5; the hook dropped them.
    expect(server.connections[1].sentIds.slice(0, 3)).toEqual([3, 4, 5]);
    expect(result.current.text).toBe(ANSWERED_TEXT);
    expect(result.current.events.map((e) => e.type)).toEqual(NON_TOKEN_TYPES);
  });

  it("waits the server's retry interval before reconnecting", async () => {
    server = await startSseServer({
      events: ANSWERED,
      retryMs: 150,
      connections: [{ dropAfter: 2, drop: "end" }],
    });
    const { result } = renderHook(() => useEventStream(server!.url, { initialRetryMs: 1 }));

    await waitFor(() => expect(result.current.status).toBe("done"));
    const [first, second] = server.connections;
    expect(second.at - first.at).toBeGreaterThanOrEqual(140);
  });

  it("honours Retry-After on a 503 and then resumes", async () => {
    server = await startSseServer({
      events: ANSWERED,
      connections: [{ status: 503, retryAfter: "1" }],
    });
    const { result } = renderHook(() => useEventStream(server!.url, FAST));

    await waitFor(() => expect(result.current.status).toBe("reconnecting"));
    await waitFor(() => expect(result.current.status).toBe("done"), { timeout: 3000 });
    const [first, second] = server.connections;
    expect(second.at - first.at).toBeGreaterThanOrEqual(950);
    expect(result.current.text).toBe(ANSWERED_TEXT);
  });

  it("renders the full text of a 5,000-token burst, batched per animation frame", async () => {
    const burst = tokenBurst(5000);
    server = await startSseServer({ events: burst.events });
    let renders = 0;
    const { result } = renderHook(() => {
      renders++;
      return useEventStream(server!.url, FAST);
    });

    await waitFor(() => expect(result.current.status).toBe("done"));
    expect(result.current.text).toBe(burst.text);
    expect(result.current.text.length).toBe(burst.text.length);
    expect(renders).toBeLessThan(500);
  });

  it("stops after a terminal final event and never reconnects", async () => {
    server = await startSseServer({ events: ANSWERED, retryMs: 10 });
    const { result } = renderHook(() => useEventStream(server!.url, FAST));

    await waitFor(() => expect(result.current.status).toBe("done"));
    await sleep(200);
    expect(server.connections).toHaveLength(1);
  });

  it("surfaces events_expired as a typed state and stops", async () => {
    server = await startSseServer({ events: EXPIRED, retryMs: 10 });
    const { result } = renderHook(() => useEventStream(server!.url, FAST));

    await waitFor(() => expect(result.current.status).toBe("expired"));
    expect(result.current.error).toMatchObject({
      type: "error",
      code: "events_expired",
      retryable: false,
    });
    await sleep(200);
    expect(server.connections).toHaveLength(1);
  });

  it("keeps going after a retryable error event", async () => {
    const events: FixtureEvent[] = [
      { id: 1, event: "error", data: { type: "error", code: "provider_slow", retryable: true } },
      ...ANSWERED.map((e) => ({ ...e, id: (e.id as number) + 1 })),
    ];
    server = await startSseServer({ events, retryMs: 10 });
    const { result } = renderHook(() => useEventStream(server!.url, FAST));

    await waitFor(() => expect(result.current.status).toBe("done"));
    expect(result.current.error).toBeNull();
    expect(result.current.events[0]).toMatchObject({ type: "error", code: "provider_slow" });
    expect(result.current.text).toBe(ANSWERED_TEXT);
  });

  it("fails without retrying on a non-retryable HTTP status", async () => {
    server = await startSseServer({ events: ANSWERED, connections: [{ status: 404 }] });
    const { result } = renderHook(() => useEventStream(server!.url, FAST));

    await waitFor(() => expect(result.current.status).toBe("failed"));
    expect(result.current.error).toMatchObject({ code: "http_404", retryable: false });
    await sleep(100);
    expect(server.connections).toHaveLength(1);
  });

  it("aborts the request on unmount, and the server sees the connection close", async () => {
    server = await startSseServer({
      events: ANSWERED.slice(0, 3),
      connections: [{ hold: true }],
    });
    const { result, unmount } = renderHook(() => useEventStream(server!.url, FAST));

    await waitFor(() => expect(result.current.events).toHaveLength(3));
    expect(result.current.status).toBe("open");
    unmount();

    await server.connections[0].closed;
    expect(server.connections[0].closedByClient).toBe(true);
    await sleep(100);
    expect(server.connections).toHaveLength(1);
  });

  it("does nothing while the url is null", async () => {
    const { result } = renderHook(() => useEventStream(null));
    expect(result.current.status).toBe("idle");
    expect(result.current.text).toBe("");
  });

  it("streams an open-ended alert stream, typed by the caller, and resumes it", async () => {
    const one = alert({ drift_event_id: "e1" });
    const two = alert({ drift_event_id: "e2", verdict: "changed" });
    server = await startSseServer({
      events: [alertFrame(1, one), alertFrame(2, two)],
      retryMs: 10,
      connections: [{ dropAfter: 1, drop: "destroy" }, { hold: true }],
    });
    const { result } = renderHook(() => useEventStream<AlertStreamEvent>(server!.url, FAST));

    await waitFor(() => expect(result.current.events).toHaveLength(2));
    const [first, second] = result.current.events;
    expect(first.type === "alert" && first.drift_event_id).toBe("e1");
    expect(second.type === "alert" && second.verdict).toBe("changed");
    // Alerts have no terminal event: the stream stays open after them.
    expect(result.current.status).toBe("open");
    expect(server.connections.map((c) => c.lastEventId)).toEqual([null, "1"]);
  });

  it("keeps a quiet alert stream alive: heartbeats reset the reconnect budget", async () => {
    // A proxy closes an idle stream after each heartbeat, again and again. The server is
    // alive (it answers and pings), so the hook never runs out of attempts.
    server = await startSseServer({ events: [], retryMs: 5 });
    const { result } = renderHook(() =>
      useEventStream<AlertStreamEvent>(server!.url, { ...FAST, maxAttempts: 2 }),
    );

    await waitFor(() => expect(server!.connections.length).toBeGreaterThanOrEqual(6), {
      timeout: 3000,
    });
    expect(result.current.status).not.toBe("failed");
    expect(result.current.error).toBeNull();
  });

  it("still gives up when reconnects never reach a live stream", async () => {
    server = await startSseServer({
      events: [],
      connections: Array.from({ length: 10 }, () => ({ status: 503 })),
    });
    const { result } = renderHook(() =>
      useEventStream<AlertStreamEvent>(server!.url, { ...FAST, maxAttempts: 2 }),
    );

    await waitFor(() => expect(result.current.status).toBe("failed"));
    expect(result.current.error?.code).toBe("reconnect_exhausted");
    expect(server.connections).toHaveLength(3);
  });

  it("reports events_expired on an alert stream as expired", async () => {
    server = await startSseServer({ events: [EXPIRED_FRAME] });
    const { result } = renderHook(() => useEventStream<AlertStreamEvent>(server!.url, FAST));

    await waitFor(() => expect(result.current.status).toBe("expired"));
    expect(result.current.error?.code).toBe("events_expired");
  });
});
