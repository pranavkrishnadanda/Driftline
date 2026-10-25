import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { DriftInbox } from "@/components/drift/drift-inbox";
import { createApiClient } from "@/lib/api/client";

import { startApiServer, type ApiServer, type FixtureResponse } from "../support/api-server";
import { BROKEN, EXPIRED_FRAME, alert, alertFrame, driftEvent } from "../support/drift-fixtures";
import { startSseServer, type SseServer, type SseServerOptions } from "../support/sse-server";

const FAST = { initialRetryMs: 10, maxRetryMs: 50, maxAttempts: 3 };
const OTHER_ANSWER = "a2222222-2222-4222-8222-222222222222";

let api: ApiServer | undefined;
let sse: SseServer | undefined;
let rejections: unknown[] = [];
const onRejection = (reason: unknown) => rejections.push(reason);

beforeEach(() => {
  rejections = [];
  process.on("unhandledRejection", onRejection);
});

afterEach(async () => {
  await new Promise((r) => setTimeout(r, 20));
  process.off("unhandledRejection", onRejection);
  await api?.close();
  await sse?.close();
  api = undefined;
  sse = undefined;
  expect(rejections).toEqual([]);
});

async function setup(
  routes: Record<string, FixtureResponse | FixtureResponse[]>,
  stream: SseServerOptions,
) {
  api = await startApiServer({
    "GET /v1/review": { status: 200, json: { items: [] } },
    ...routes,
  });
  sse = await startSseServer({ retryMs: 10, ...stream });
  const client = createApiClient({ baseUrl: api.url });
  const user = userEvent.setup();
  render(
    <DriftInbox
      tenants={["demo", "acme"]}
      client={client}
      streamBaseUrl={new URL(sse.url).origin}
      streamOptions={FAST}
    />,
  );
  return { user };
}

const alertList = () => screen.getByRole("list", { name: "Drift alerts" });
const alertTitles = () =>
  within(alertList())
    .getAllByRole("article")
    .map((a) => within(a).getByRole("heading").textContent);

describe("DriftInbox", () => {
  it("merges live alerts into history without duplicates, newest first", async () => {
    await setup(
      {
        "GET /v1/drift/events": {
          status: 200,
          json: {
            events: [
              driftEvent({
                id: "e1",
                document_title: "Storage policy",
                created_at: "2026-10-19T09:00:00Z",
              }),
            ],
          },
        },
      },
      {
        events: [
          // A replay of the history row, then a new alert.
          alertFrame(
            1,
            alert({
              drift_event_id: "e1",
              document_title: "Storage policy",
              t: "2026-10-19T09:00:00Z",
            }),
          ),
          alertFrame(
            2,
            alert({
              drift_event_id: "e2",
              document_title: "Dosing guideline",
              t: "2026-10-21T09:00:00Z",
            }),
          ),
        ],
        connections: [{ hold: true }],
      },
    );

    await waitFor(() => expect(alertTitles()).toEqual(["Dosing guideline", "Storage policy"]));
    expect(sse!.connections[0].url).toBe("/v1/alerts/stream?tenant=demo");
    expect(api!.requests.find((r) => r.url.startsWith("/v1/drift/events"))?.url).toContain(
      "tenant=demo",
    );
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Live"));
  });

  it("shows each alert's verdict, document and a readable before/after diff", async () => {
    await setup(
      { "GET /v1/drift/events": { status: 200, json: { events: [] } } },
      {
        events: [
          alertFrame(
            1,
            alert({
              drift_event_id: "e1",
              verdict: "broken",
              before: "Take 10 mg twice daily.",
              after: "Take 20 mg once daily.",
            }),
          ),
        ],
        connections: [{ hold: true }],
      },
    );

    const card = await screen.findByRole("article", { name: /Dosing guideline/ });
    expect(within(card).getByText("Broken")).toBeInTheDocument();
    const diff = within(card).getByRole("group", { name: "Before and after" });
    const removed = [...diff.querySelectorAll("del")].map((d) => d.textContent);
    const added = [...diff.querySelectorAll("ins")].map((d) => d.textContent);
    expect(removed.join(" ")).toContain("10");
    expect(removed.join(" ")).toContain("twice");
    expect(added.join(" ")).toContain("20");
    expect(added.join(" ")).toContain("once");
  });

  it("offers Send to review only when the answer has an open broken item", async () => {
    await setup(
      {
        "GET /v1/drift/events": {
          status: 200,
          json: {
            events: [
              driftEvent({
                id: "e1",
                answer_id: BROKEN.ref_id,
                document_title: "Dosing guideline",
              }),
              driftEvent({
                id: "e2",
                answer_id: OTHER_ANSWER,
                document_title: "Storage policy",
                created_at: "2026-10-01T00:00:00Z",
              }),
            ],
          },
        },
        "GET /v1/review": { status: 200, json: { items: [BROKEN] } },
      },
      { events: [], connections: [{ hold: true }] },
    );

    const broken = await screen.findByRole("article", { name: /Dosing guideline/ });
    const link = await within(broken).findByRole("link", { name: "Send to review" });
    expect(link).toHaveAttribute("href", `/review?item=${BROKEN.id}`);
    const other = screen.getByRole("article", { name: /Storage policy/ });
    expect(within(other).queryByRole("link", { name: "Send to review" })).toBeNull();
    expect(api!.requests.find((r) => r.url.startsWith("/v1/review"))?.url).toContain(
      "kind=broken_answer",
    );
  });

  it("opens an answer's details from the keyboard and can stop watching it", async () => {
    const { user } = await setup(
      {
        "GET /v1/drift/events": {
          status: 200,
          json: { events: [driftEvent({ id: "e1", document_title: "Storage policy" })] },
        },
        [`DELETE /v1/answers/${driftEvent({ id: "x" }).answer_id}/watch`]: {
          status: 200,
          json: { answer_id: driftEvent({ id: "x" }).answer_id, watched: false },
        },
      },
      { events: [], connections: [{ hold: true }] },
    );

    const card = await screen.findByRole("article", { name: /Storage policy/ });
    const open = within(card).getByRole("button", { name: "Open answer" });
    expect(open).toHaveAttribute("aria-expanded", "false");
    open.focus();
    await user.keyboard("{Enter}");
    expect(open).toHaveAttribute("aria-expanded", "true");
    const details = within(card).getByRole("region", { name: "Answer details" });
    expect(details).toHaveTextContent(driftEvent({ id: "x" }).answer_id);
    expect(details).toHaveTextContent("Storage > Temperature");

    await user.click(within(details).getByRole("button", { name: "Stop watching" }));
    await within(details).findByRole("button", { name: "Watch again" });
    expect(api!.requests.some((r) => r.method === "DELETE")).toBe(true);
  });

  it("refetches history and reconnects at the tail when the stream expired", async () => {
    await setup(
      {
        "GET /v1/drift/events": [
          {
            status: 200,
            json: { events: [driftEvent({ id: "e1", document_title: "Storage policy" })] },
          },
          {
            status: 200,
            json: {
              events: [
                driftEvent({ id: "e1", document_title: "Storage policy" }),
                driftEvent({
                  id: "e2",
                  document_title: "Missed while away",
                  created_at: "2026-10-20T00:00:00Z",
                }),
              ],
            },
          },
        ],
      },
      {
        events: [],
        connections: [
          { events: [EXPIRED_FRAME] },
          {
            hold: true,
            events: [
              alertFrame(
                7,
                alert({
                  drift_event_id: "e3",
                  document_title: "Live after resync",
                  t: "2026-10-22T00:00:00Z",
                }),
              ),
            ],
          },
        ],
      },
    );

    await waitFor(() =>
      expect(alertTitles()).toEqual(["Live after resync", "Missed while away", "Storage policy"]),
    );
    expect(api!.requests.filter((r) => r.url.startsWith("/v1/drift/events"))).toHaveLength(2);
    const resumed = new URL(sse!.connections[1].url, "http://x");
    expect(resumed.searchParams.get("last_event_id")).toBe(String(Number.MAX_SAFE_INTEGER));
  });

  it("shows a retry when history fails to load", async () => {
    const { user } = await setup(
      {
        "GET /v1/drift/events": [
          { status: 500, json: { detail: "boom" } },
          {
            status: 200,
            json: { events: [driftEvent({ id: "e1", document_title: "Storage policy" })] },
          },
        ],
      },
      { events: [], connections: [{ hold: true }] },
    );

    const failure = await screen.findByRole("alert");
    expect(failure).toHaveTextContent("Could not load drift history");
    await user.click(within(failure).getByRole("button", { name: "Retry" }));
    await screen.findByRole("article", { name: /Storage policy/ });
  });

  it("shows an empty state when there are no alerts", async () => {
    await setup(
      { "GET /v1/drift/events": { status: 200, json: { events: [] } } },
      { events: [], connections: [{ hold: true }] },
    );
    await screen.findByText(/No drift yet/);
  });
});
