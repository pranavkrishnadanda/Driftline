import { beforeEach, describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/client";
import { getLastMatch } from "@/lib/demo/ask-store";
import { createDemoClient, resetDemoSession } from "@/lib/demo/client";
import { DEMO_API_BASE } from "@/lib/demo/config";
import { provideRecording } from "@/lib/demo/recording";

import { DEMO_RECORDING } from "../support/demo-fixtures";

beforeEach(() => {
  provideRecording(DEMO_RECORDING);
  resetDemoSession();
});

describe("the demo API client", () => {
  const client = createDemoClient();

  it("reports the recording's stand-in origin", () => {
    expect(client.baseUrl).toBe(DEMO_API_BASE);
  });

  it("answers an ask with the recorded job of the closest question, and records the match", async () => {
    const accepted = await client.ask({ question: "maximum metformin dose", tenant: "demo" });
    expect(accepted).toEqual(DEMO_RECORDING.asks[2].accepted);
    expect(getLastMatch()).toMatchObject({
      exact: false,
      asked: { question: "maximum metformin dose", as_of: null },
    });
    const job = await client.job(accepted.job_id);
    expect(job).toEqual(DEMO_RECORDING.asks[2].job);
  });

  it("serves the recorded drift history, timeline and stats", async () => {
    expect((await client.driftEvents({ tenant: "demo", limit: 1 })).events).toEqual(
      DEMO_RECORDING.drift_events.slice(0, 1),
    );
    const [id] = Object.keys(DEMO_RECORDING.timelines);
    expect(await client.timeline(id, "demo")).toEqual(DEMO_RECORDING.timelines[id]);
    expect(await client.stats({ tenant: "demo" })).toEqual(DEMO_RECORDING.stats);
  });

  it("is a 404 for a document the recording does not hold", async () => {
    await expect(
      client.timeline("11111111-1111-4111-8111-111111111111", "demo"),
    ).rejects.toMatchObject({ status: 404 });
  });

  it("resolves a review item for this visit only, and a second resolve is a 409", async () => {
    const open = (await client.review({ tenant: "demo" })).items;
    expect(open.map((i) => i.id)).toEqual(DEMO_RECORDING.review.map((i) => i.id));
    const [first] = open;

    const resolved = await client.resolve(first.id, { action: "approve", by: "visitor" }, "demo");
    expect(resolved).toMatchObject({ id: first.id, status: "resolved", resolved_by: "visitor" });
    expect((await client.review({ tenant: "demo" })).items.map((i) => i.id)).not.toContain(
      first.id,
    );
    expect(
      (await client.review({ tenant: "demo", status: "resolved" })).items.map((i) => i.id),
    ).toEqual([first.id]);

    const again = client.resolve(first.id, { action: "approve", by: "visitor" }, "demo");
    await expect(again).rejects.toBeInstanceOf(ApiError);
    await expect(again).rejects.toMatchObject({ status: 409, code: "already_resolved" });

    // Nothing persists: a new visit starts from the recording again.
    resetDemoSession();
    expect((await client.review({ tenant: "demo" })).items).toHaveLength(open.length);
  });

  it("filters review items by kind", async () => {
    const items = (await client.review({ tenant: "demo", kind: "broken_answer" })).items;
    expect(items.every((i) => i.kind === "broken_answer")).toBe(true);
    expect(items.length).toBeGreaterThan(0);
  });

  it("toggles watching without a server", async () => {
    expect(await client.unwatch("a1", "demo")).toEqual({ answer_id: "a1", watched: false });
    expect(await client.watch("a1", "demo")).toEqual({ answer_id: "a1", watched: true });
  });

  it("honours an aborted signal", async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(client.stats({}, { signal: controller.signal })).rejects.toMatchObject({
      name: "AbortError",
    });
  });
});
