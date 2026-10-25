import { describe, expect, it } from "vitest";

import {
  INITIAL_INBOX,
  MAX_ALERTS,
  alertStreamUrl,
  inboxReducer,
  type InboxState,
} from "@/lib/drift/inbox";
import type { AlertStreamEvent } from "@/lib/sse/events";

import { EXPIRED_FRAME, alert, driftEvent } from "../support/drift-fixtures";

const expiredEvent = EXPIRED_FRAME.data as AlertStreamEvent;

function ids(state: InboxState): string[] {
  return state.alerts.map((a) => a.id);
}

describe("inboxReducer", () => {
  it("loads history latest first and marks it loaded", () => {
    const state = inboxReducer(INITIAL_INBOX, {
      type: "history",
      events: [
        driftEvent({ id: "h1", created_at: "2026-10-01T00:00:00Z" }),
        driftEvent({ id: "h2", created_at: "2026-10-03T00:00:00Z" }),
      ],
    });
    expect(ids(state)).toEqual(["h2", "h1"]);
    expect(state.historyLoaded).toBe(true);
    expect(state.alerts[0]).toMatchObject({
      verdict: "changed",
      documentTitle: "Storage policy",
      sectionPath: "Storage > Temperature",
      before: "Store below 25 C.",
      after: "Store below 30 C.",
      live: false,
    });
  });

  it("merges live alerts into history without duplicates by drift_event_id", () => {
    let state = inboxReducer(INITIAL_INBOX, {
      type: "history",
      events: [driftEvent({ id: "e1", created_at: "2026-10-01T00:00:00Z" })],
    });
    const live: AlertStreamEvent[] = [
      alert({ drift_event_id: "e1", t: "2026-10-01T00:00:00Z" }),
      alert({ drift_event_id: "e2", t: "2026-10-05T00:00:00Z" }),
    ];
    state = inboxReducer(state, { type: "live", events: live });
    // The hook hands over its whole event list each time: replaying it changes nothing.
    const again = inboxReducer(state, { type: "live", events: live });

    expect(ids(again)).toEqual(["e2", "e1"]);
    expect(again).toEqual(state);
    // The history row keeps the fields only history carries.
    expect(again.alerts[1]).toMatchObject({ sectionPath: "Storage > Temperature", live: true });
  });

  it("keeps a live alert's fields when history for it arrives later", () => {
    let state = inboxReducer(INITIAL_INBOX, {
      type: "live",
      events: [alert({ drift_event_id: "e9", document_title: "Dosing guideline" })],
    });
    state = inboxReducer(state, {
      type: "history",
      events: [driftEvent({ id: "e9", document_title: null, before: null })],
    });
    expect(state.alerts).toHaveLength(1);
    expect(state.alerts[0]).toMatchObject({
      documentTitle: "Dosing guideline",
      before: "Take 10 mg twice daily with food.",
      sectionPath: "Storage > Temperature",
      live: true,
    });
  });

  it("orders by time, newest first, with the id breaking ties", () => {
    const state = inboxReducer(INITIAL_INBOX, {
      type: "live",
      events: [
        alert({ drift_event_id: "b", t: "2026-10-02T00:00:00Z" }),
        alert({ drift_event_id: "a", t: "2026-10-02T00:00:00Z" }),
        alert({ drift_event_id: "c", t: "2026-10-04T00:00:00Z" }),
        alert({ drift_event_id: "d", t: "2026-09-30T00:00:00Z" }),
      ],
    });
    expect(ids(state)).toEqual(["c", "b", "a", "d"]);
  });

  it("returns the same state when nothing new arrives", () => {
    const state = inboxReducer(INITIAL_INBOX, {
      type: "live",
      events: [alert({ drift_event_id: "e1" })],
    });
    expect(inboxReducer(state, { type: "live", events: [alert({ drift_event_id: "e1" })] })).toBe(
      state,
    );
  });

  it("ignores error events in the live list", () => {
    const state = inboxReducer(INITIAL_INBOX, { type: "live", events: [expiredEvent] });
    expect(state.alerts).toEqual([]);
  });

  it(`keeps at most ${MAX_ALERTS} alerts, dropping the oldest`, () => {
    const events = Array.from({ length: MAX_ALERTS + 5 }, (_, i) =>
      alert({
        drift_event_id: `e${i}`,
        t: new Date(Date.UTC(2026, 0, 1) + i * 60_000).toISOString(),
      }),
    );
    const state = inboxReducer(INITIAL_INBOX, { type: "live", events });
    expect(state.alerts).toHaveLength(MAX_ALERTS);
    expect(state.alerts.at(-1)?.id).toBe("e5");
  });

  it("falls back to a history refetch when the stream reports events_expired", () => {
    let state = inboxReducer(INITIAL_INBOX, {
      type: "history",
      events: [driftEvent({ id: "e1" })],
    });
    state = inboxReducer(state, { type: "expired" });
    expect(state.resync).toBe(1);
    expect(state.historyLoaded).toBe(false);
    // What was already shown stays shown while history reloads.
    expect(ids(state)).toEqual(["e1"]);

    state = inboxReducer(state, {
      type: "history",
      events: [driftEvent({ id: "e1" }), driftEvent({ id: "e2", created_at: "2026-10-21T00:00:00Z" })],
    });
    expect(state.historyLoaded).toBe(true);
    expect(ids(state)).toEqual(["e2", "e1"]);
  });
});

describe("alertStreamUrl", () => {
  it("replays the stored log on the first connection", () => {
    expect(alertStreamUrl("http://api:8010", "acme corp", 0)).toBe(
      "http://api:8010/v1/alerts/stream?tenant=acme+corp",
    );
  });

  it("after a resync follows only live alerts, with a URL distinct per resync", () => {
    const one = new URL(alertStreamUrl("http://api:8010", "demo", 1));
    const two = new URL(alertStreamUrl("http://api:8010", "demo", 2));
    expect(one.pathname).toBe("/v1/alerts/stream");
    expect(one.searchParams.get("tenant")).toBe("demo");
    // The gateway clamps a Last-Event-ID beyond its log to the newest id (the tail).
    expect(Number(one.searchParams.get("last_event_id"))).toBe(Number.MAX_SAFE_INTEGER);
    expect(one.toString()).not.toBe(two.toString());
  });
});
