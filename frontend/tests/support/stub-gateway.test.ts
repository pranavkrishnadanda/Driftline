/**
 * The stub gateway the browser checks run against: the real API client and SSE hook talk
 * to it over sockets, so its fixtures are known to match what the views expect.
 */
import { renderHook, waitFor } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { ApiError, createApiClient } from "@/lib/api/client";
import { resolveEventsUrl } from "@/lib/ask/format";
import type { AlertStreamEvent } from "@/lib/sse/events";
import { useEventStream } from "@/lib/sse/useEventStream";

import { ANSWERED_TEXT } from "./ask-fixtures";
import { STUB_ALERT, STUB_DRIFT_EVENTS, startStubGateway, type StubGateway } from "./stub-gateway";
import { DOC_ID, TIMELINE } from "./version-timeline-fixtures";

let gateway: StubGateway;

beforeAll(async () => {
  gateway = await startStubGateway();
});
afterAll(async () => {
  await gateway.close();
});

describe("stub gateway", () => {
  it("serves the views' REST routes with the contract fixtures", async () => {
    const client = createApiClient({ baseUrl: gateway.url });
    expect((await client.driftEvents({ tenant: "demo" })).events).toEqual(STUB_DRIFT_EVENTS);
    expect(await client.timeline(DOC_ID, "demo")).toEqual(TIMELINE);
    expect((await client.review({ tenant: "demo", kind: "broken_answer" })).items.map((i) => i.kind)).toEqual([
      "broken_answer",
    ]);
    await expect(client.timeline("00000000-0000-4000-8000-000000000000")).rejects.toBeInstanceOf(ApiError);
  });

  it("answers CORS preflights for the frontend's origin", async () => {
    const res = await fetch(`${gateway.url}/v1/ask`, {
      method: "OPTIONS",
      headers: {
        Origin: "http://localhost:3100",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
      },
    });
    expect(res.status).toBe(204);
    expect(res.headers.get("access-control-allow-origin")).toBe("*");
    expect(res.headers.get("access-control-allow-headers")).toMatch(/Last-Event-ID/);
  });

  it("queues an ask and replays the answered stream", async () => {
    const client = createApiClient({ baseUrl: gateway.url });
    const accepted = await client.ask({ question: "What is the dose?", tenant: "demo" });
    const url = resolveEventsUrl(accepted.events_url, gateway.url);
    const { result } = renderHook(() => useEventStream(url));
    await waitFor(() => expect(result.current.status).toBe("done"));
    expect(result.current.text).toBe(ANSWERED_TEXT);
  });

  it("holds the alert stream open after its alert", async () => {
    const { result } = renderHook(() =>
      useEventStream<AlertStreamEvent>(`${gateway.url}/v1/alerts/stream?tenant=demo`),
    );
    await waitFor(() => expect(result.current.events).toHaveLength(1));
    expect(result.current.events[0]).toEqual(STUB_ALERT);
    expect(result.current.status).toBe("open");
  });
});
