import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AskView } from "@/components/ask/ask-view";
import { createApiClient, type AskAccepted, type JobStatus } from "@/lib/api/client";

import expired from "../fixtures/sse/ask-expired.json";
import {
  closedPortUrl,
  startApiServer,
  type ApiServer,
  type FixtureResponse,
} from "../support/api-server";
import {
  ANSWERED,
  ANSWERED_EVENTS,
  ANSWERED_TEXT,
  REVIEW_APPROVED_EVENTS,
  REVIEW_WAITING_EVENTS,
  finalFrame,
  insufficientAnswer,
} from "../support/ask-fixtures";
import { startSseServer, type FixtureEvent, type SseServer } from "../support/sse-server";

const JOB_ID = "6f1c2b0e-3c1a-4c55-9a77-0d4d1d6b2f10";
const FAST = { initialRetryMs: 10, maxRetryMs: 50, maxAttempts: 2 };

let api: ApiServer | undefined;
let sse: SseServer | undefined;
let rejections: unknown[] = [];
const onRejection = (reason: unknown) => rejections.push(reason);
const onWindowRejection = (event: PromiseRejectionEvent) => rejections.push(event.reason);

beforeEach(() => {
  rejections = [];
  process.on("unhandledRejection", onRejection);
  window.addEventListener("unhandledrejection", onWindowRejection);
});

afterEach(async () => {
  // Let any stray rejection surface before checking.
  await new Promise((r) => setTimeout(r, 20));
  process.off("unhandledRejection", onRejection);
  window.removeEventListener("unhandledrejection", onWindowRejection);
  await api?.close();
  await sse?.close();
  api = undefined;
  sse = undefined;
  expect(rejections).toEqual([]);
});

function accepted(eventsUrl: string): FixtureResponse {
  return {
    status: 202,
    json: {
      job_id: JOB_ID,
      events_url: eventsUrl,
      status_url: `/v1/jobs/${JOB_ID}`,
    } satisfies AskAccepted,
  };
}

async function setup(
  events: FixtureEvent[],
  extra: Parameters<typeof startSseServer>[0] = { events },
) {
  sse = await startSseServer({ retryMs: 10, ...extra, events });
  const routes: Record<string, FixtureResponse> = { "POST /v1/ask": accepted(sse.url) };
  api = await startApiServer(routes);
  return routes;
}

function renderView(baseUrl: string, tenants = ["demo", "pharma"]) {
  const user = userEvent.setup();
  render(<AskView client={createApiClient({ baseUrl })} tenants={tenants} streamOptions={FAST} />);
  return user;
}

async function ask(
  user: ReturnType<typeof userEvent.setup>,
  question = "How often should ALT be checked?",
) {
  await user.click(screen.getByRole("textbox", { name: "Question" }));
  await user.keyboard(`${question}{Enter}`);
}

function askBodies() {
  return api!.requests
    .filter((r) => r.method === "POST" && r.url === "/v1/ask")
    .map((r) => JSON.parse(r.body) as Record<string, unknown>);
}

describe("AskView: answering", () => {
  it("asks through the client, streams the events and renders the final answer with citations", async () => {
    await setup(ANSWERED_EVENTS);
    const user = renderView(api!.url);

    await ask(user);

    const answer = await screen.findByRole("region", { name: "Answer" });
    expect(answer).toHaveTextContent(ANSWERED.answer);
    expect(within(answer).getByRole("button", { name: /Citation 1/ })).toBeInTheDocument();
    expect(askBodies()).toEqual([{ question: "How often should ALT be checked?", tenant: "demo" }]);
    expect(sse!.connections).toHaveLength(1);
    // The question stays visible above its answer.
    expect(screen.getByText("How often should ALT be checked?")).toBeInTheDocument();
  });

  it("shows the agent timeline above the answer, lit in graph order", async () => {
    await setup(ANSWERED_EVENTS);
    const user = renderView(api!.url);

    await ask(user);

    const answer = await screen.findByRole("region", { name: "Answer" });
    const timeline = screen.getByRole("region", { name: "Agent timeline" });
    // Above the answer in document order.
    expect(
      timeline.compareDocumentPosition(answer) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    const lit = [...timeline.querySelectorAll<HTMLElement>("[data-lit-order]")]
      .sort((a, b) => Number(a.dataset.litOrder) - Number(b.dataset.litOrder))
      .map((el) => el.dataset.node);
    expect(lit).toEqual([
      "classify",
      "cache",
      "plan",
      "subagent",
      "merge",
      "draft",
      "verify",
      "respond",
    ]);
    expect(timeline.querySelector('[aria-live="polite"]')).toHaveTextContent(
      "Done: 1 of 1 claims verified.",
    );
  });

  it("shows the streamed text while the answer is being written", async () => {
    const progress = ANSWERED_EVENTS.filter((e) => e.event !== "final");
    await setup(progress, { events: progress, connections: [{ hold: true }] });
    const user = renderView(api!.url);

    await ask(user);

    const live = await screen.findByRole("region", { name: "Answer in progress" });
    await waitFor(() => expect(live).toHaveTextContent(ANSWERED_TEXT));
    expect(screen.getByRole("button", { name: "Stop response" })).toBeInTheDocument();
  });

  it("stops the stream when the user presses Stop", async () => {
    const progress = ANSWERED_EVENTS.filter((e) => e.event !== "final");
    await setup(progress, { events: progress, connections: [{ hold: true }] });
    const user = renderView(api!.url);

    await ask(user);
    await screen.findByRole("region", { name: "Answer in progress" });
    await user.click(screen.getByRole("button", { name: "Stop response" }));

    await sse!.connections[0].closed;
    expect(sse!.connections[0].closedByClient).toBe(true);
    expect(await screen.findByText(/Stopped/)).toBeInTheDocument();
  });

  it("shows an explicit refusal with the nearest sources for insufficient evidence", async () => {
    await setup([finalFrame(insufficientAnswer(), 1)]);
    const user = renderView(api!.url);

    await ask(user);

    expect(
      await screen.findByRole("heading", { name: "Not enough evidence to answer" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Nearest sources" })).toHaveTextContent(
      "Acme tablets label",
    );
  });

  it("recovers the answer from the job status when the stream has expired", async () => {
    const routes = await setup(expired.events as FixtureEvent[]);
    routes[`GET /v1/jobs/${JOB_ID}`] = {
      status: 200,
      json: {
        job_id: JOB_ID,
        status: "succeeded",
        error: null,
        answer: ANSWERED,
        cost_usd: 0.0042,
      } satisfies JobStatus,
    };
    const user = renderView(api!.url);

    await ask(user);

    expect(await screen.findByRole("region", { name: "Answer" })).toHaveTextContent(
      ANSWERED.answer,
    );
  });
});

describe("AskView: human review", () => {
  it("shows 'Waiting for human review' when the stream pauses at the review step", async () => {
    await setup(REVIEW_WAITING_EVENTS, {
      events: REVIEW_WAITING_EVENTS,
      connections: [{ hold: true }],
    });
    const user = renderView(api!.url);

    await ask(user);

    const pending = await screen.findByRole("region", { name: "Waiting for human review" });
    expect(pending).toHaveTextContent(ANSWERED_TEXT);
    expect(pending).toHaveTextContent("confidence is below the review threshold");
    expect(screen.getByRole("status")).toHaveTextContent("Waiting for human review.");
    const timeline = screen.getByRole("region", { name: "Agent timeline" });
    expect(timeline.querySelector('[data-node="review"]')).toHaveAttribute(
      "data-status",
      "waiting",
    );
    // Not an error, and not an endless spinner: the prompt is free again.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Answer in progress" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop response" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send message" })).toBeInTheDocument();
    // The stream stays open for the reviewer's decision.
    await new Promise((r) => setTimeout(r, 100));
    expect(sse!.connections).toHaveLength(1);
    expect(sse!.connections[0].closedByClient).toBe(false);
    expect(screen.getByRole("region", { name: "Waiting for human review" })).toBeInTheDocument();
  });

  it("renders the answer once the reviewer resolves it and the stream resumes", async () => {
    const waitingId = REVIEW_WAITING_EVENTS.at(-1)!.id!;
    await setup(REVIEW_APPROVED_EVENTS, {
      events: REVIEW_APPROVED_EVENTS,
      connections: [{ dropAfter: REVIEW_WAITING_EVENTS.length, drop: "end" }],
    });
    const user = renderView(api!.url);

    await ask(user);

    expect(await screen.findByRole("region", { name: "Answer" })).toHaveTextContent(
      ANSWERED.answer,
    );
    expect(sse!.connections[1].lastEventId).toBe(String(waitingId));
    expect(
      screen.queryByRole("region", { name: "Waiting for human review" }),
    ).not.toBeInTheDocument();
  });

  it("treats an expired stream whose job is needs_review as waiting, not failed", async () => {
    const routes = await setup(expired.events as FixtureEvent[]);
    routes[`GET /v1/jobs/${JOB_ID}`] = {
      status: 200,
      json: {
        job_id: JOB_ID,
        status: "needs_review",
        error: null,
        answer: null,
        cost_usd: 0,
      } satisfies JobStatus,
    };
    const user = renderView(api!.url);

    await ask(user);

    expect(
      await screen.findByRole("region", { name: "Waiting for human review" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("AskView: tenant and as-of", () => {
  it("sends the selected tenant and the picked as-of date", async () => {
    await setup(ANSWERED_EVENTS);
    const user = renderView(api!.url);

    await user.click(screen.getByRole("combobox", { name: "Tenant" }));
    await user.click(await screen.findByRole("option", { name: "pharma" }));
    expect(screen.getByRole("combobox", { name: "Tenant" })).toHaveTextContent("pharma");

    await user.click(screen.getByRole("button", { name: /As of/ }));
    const grid = await screen.findByRole("grid");
    const first = within(grid)
      .getAllByRole("button")
      .find((b) => b.textContent === "1" && !b.closest("[data-outside]"))!;
    await user.click(first);

    const now = new Date();
    const month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
    expect(screen.getByRole("button", { name: /As of/ })).not.toHaveTextContent("Today");

    await ask(user);
    await screen.findByRole("region", { name: "Answer" });
    expect(askBodies()).toEqual([
      {
        question: "How often should ALT be checked?",
        tenant: "pharma",
        as_of: `${month}-01T00:00:00Z`,
      },
    ]);
  });
});

describe("AskView: failures", () => {
  it("honours Retry-After on a 429 with a countdown, then retries", async () => {
    const routes = await setup(ANSWERED_EVENTS);
    routes["POST /v1/ask"] = {
      status: 429,
      json: { detail: { code: "backpressure", backlog: 99 } },
      headers: { "Retry-After": "1" },
    };
    const user = renderView(api!.url);

    await ask(user);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/busy/i);
    expect(alert).toHaveTextContent("0:01");
    const retry = within(alert).getByRole("button", { name: /Retry/ });
    expect(retry).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();

    routes["POST /v1/ask"] = accepted(sse!.url);
    await waitFor(() => expect(retry).toBeEnabled(), { timeout: 3000 });
    expect(alert).toHaveTextContent("0:00");
    await user.click(retry);

    expect(await screen.findByRole("region", { name: "Answer" })).toHaveTextContent(
      ANSWERED.answer,
    );
    expect(askBodies()).toHaveLength(2);
    expect(askBodies()[1]).toEqual(askBodies()[0]);
  });

  it("shows backend-down with a retry button when the gateway can't be reached", async () => {
    const user = renderView(await closedPortUrl());

    await ask(user);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The Driftline API can't be reached.");
    const retry = within(alert).getByRole("button", { name: "Retry" });
    expect(retry).toBeEnabled();

    await user.click(retry);
    expect(await screen.findByRole("alert")).toHaveTextContent("can't be reached");
  });

  it("recovers through the retry button once the gateway is back", async () => {
    const routes = await setup(ANSWERED_EVENTS);
    routes["POST /v1/ask"] = { status: 503, json: { detail: "down" } };
    const user = renderView(api!.url);

    await ask(user);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("unavailable (503)");

    routes["POST /v1/ask"] = accepted(sse!.url);
    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("region", { name: "Answer" })).toHaveTextContent(
      ANSWERED.answer,
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("offers a retry when the event stream fails", async () => {
    const routes = await setup(ANSWERED_EVENTS, {
      events: ANSWERED_EVENTS,
      connections: [{ status: 404 }],
    });
    const user = renderView(api!.url);

    await ask(user);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/stream/i);

    // A new ask gets a new job, so a new events URL.
    routes["POST /v1/ask"] = accepted(`${sse!.url}?job=2`);
    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("region", { name: "Answer" })).toHaveTextContent(
      ANSWERED.answer,
    );
    expect(askBodies()).toHaveLength(2);
  });

  it("explains an unknown tenant without a retry loop", async () => {
    const routes = await setup(ANSWERED_EVENTS);
    routes["POST /v1/ask"] = { status: 404, json: { detail: { code: "unknown_tenant" } } };
    const user = renderView(api!.url);

    await ask(user);

    expect(await screen.findByRole("alert")).toHaveTextContent("Unknown tenant");
  });
});
