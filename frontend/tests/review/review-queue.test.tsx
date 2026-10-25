import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ReviewQueue } from "@/components/review/review-queue";
import { createApiClient, type ReviewItem } from "@/lib/api/client";

import { startApiServer, type ApiServer, type FixtureResponse } from "../support/api-server";
import { BROKEN, LEGACY_ANSWER, LOW_CONFIDENCE, RELATION } from "../support/drift-fixtures";

let api: ApiServer | undefined;
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
  api = undefined;
  expect(rejections).toEqual([]);
});

const ALL = [LOW_CONFIDENCE, BROKEN, RELATION, LEGACY_ANSWER];

function resolved(item: ReviewItem, action: string, edit: unknown = null): FixtureResponse {
  return {
    status: 200,
    json: {
      ...item,
      status: "resolved",
      resolution: { action, edit },
      resolved_by: "driftline-web",
      resolved_at: "2026-10-25T10:00:00Z",
    },
  };
}

async function setup(
  routes: Record<string, FixtureResponse | FixtureResponse[]>,
  props: { focusItem?: string } = {},
) {
  api = await startApiServer({
    "GET /v1/review": { status: 200, json: { items: ALL } },
    ...routes,
  });
  const user = userEvent.setup();
  render(
    <ReviewQueue
      tenants={["demo"]}
      client={createApiClient({ baseUrl: api.url })}
      reviewer="driftline-web"
      {...props}
    />,
  );
  await screen.findByRole("region", { name: /Low-confidence answers/ });
  return { user };
}

const itemCard = (name: RegExp | string) => screen.getByRole("article", { name });
/** The broken and legacy answer items read alike, so pick them by id. */
const byId = (id: string) => {
  const card = document.querySelector<HTMLElement>(`article[data-item-id="${id}"]`);
  if (!card) throw new Error(`no review item ${id}`);
  return card;
};
const resolveRequests = () => api!.requests.filter((r) => r.url.includes("/resolve"));

describe("ReviewQueue", () => {
  it("groups items by kind", async () => {
    await setup({});
    const groups = screen
      .getAllByRole("region")
      .map((r) => within(r).getByRole("heading", { level: 2 }).textContent);
    expect(groups).toEqual(["Low-confidence answers", "Broken answers", "Relations", "Answers"]);
    expect(screen.getByRole("region", { name: "Relations" })).toHaveTextContent("1 item");
    expect(api!.requests[0].url).toContain("tenant=demo");
  });

  it("approves an item, removing it at once", async () => {
    const { user } = await setup({
      [`POST /v1/review/${LOW_CONFIDENCE.id}/resolve`]: resolved(LOW_CONFIDENCE, "approve"),
    });
    const card = itemCard(/What is the maximum daily dose/);
    await user.click(within(card).getByRole("button", { name: "Approve" }));

    expect(screen.queryByRole("article", { name: /What is the maximum daily dose/ })).toBeNull();
    await waitFor(() => expect(resolveRequests()).toHaveLength(1));
    expect(JSON.parse(resolveRequests()[0].body)).toEqual({
      action: "approve",
      by: "driftline-web",
    });
    expect(resolveRequests()[0].url).toContain("tenant=demo");
    await screen.findByText(/Approved/);
  });

  it("rejects an item", async () => {
    const { user } = await setup({
      [`POST /v1/review/${RELATION.id}/resolve`]: resolved(RELATION, "reject"),
    });
    await user.click(within(itemCard(/Amends SOP-12/)).getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(resolveRequests()).toHaveLength(1));
    expect(JSON.parse(resolveRequests()[0].body)).toEqual({
      action: "reject",
      by: "driftline-web",
    });
    await screen.findByText(/Rejected/);
    expect(screen.queryByRole("article", { name: /Amends SOP-12/ })).toBeNull();
  });

  it("edits an answer inline and sends the correction", async () => {
    const { user } = await setup({
      [`POST /v1/review/${LOW_CONFIDENCE.id}/resolve`]: resolved(LOW_CONFIDENCE, "edit"),
    });
    const card = itemCard(/What is the maximum daily dose/);
    await user.click(within(card).getByRole("button", { name: "Edit" }));
    const editor = within(card).getByRole("textbox", { name: "Corrected answer" });
    expect(editor).toHaveValue("The maximum daily dose is 40 mg.");
    expect(editor).toHaveFocus();
    await user.clear(editor);
    await user.type(editor, "The maximum daily dose is 20 mg.");
    await user.click(within(card).getByRole("button", { name: "Save edit" }));

    await waitFor(() => expect(resolveRequests()).toHaveLength(1));
    expect(JSON.parse(resolveRequests()[0].body)).toEqual({
      action: "edit",
      edit: { answer: "The maximum daily dose is 20 mg." },
      by: "driftline-web",
    });
    await screen.findByText(/Edited/);
  });

  it("edits a relation's kind with a select, and Escape cancels an edit", async () => {
    const { user } = await setup({
      [`POST /v1/review/${RELATION.id}/resolve`]: resolved(RELATION, "edit", {
        kind: "supersedes",
      }),
    });
    const card = itemCard(/Amends SOP-12/);
    await user.click(within(card).getByRole("button", { name: "Edit" }));
    await user.keyboard("{Escape}");
    expect(within(card).queryByRole("combobox", { name: "Relation kind" })).toBeNull();
    expect(within(card).getByRole("button", { name: "Edit" })).toHaveFocus();

    await user.click(within(card).getByRole("button", { name: "Edit" }));
    await user.selectOptions(
      within(card).getByRole("combobox", { name: "Relation kind" }),
      "supersedes",
    );
    await user.click(within(card).getByRole("button", { name: "Save edit" }));
    await waitFor(() => expect(resolveRequests()).toHaveLength(1));
    expect(JSON.parse(resolveRequests()[0].body)).toEqual({
      action: "edit",
      edit: { kind: "supersedes" },
      by: "driftline-web",
    });
  });

  it("does not save an empty answer edit", async () => {
    const { user } = await setup({});
    const card = byId(BROKEN.id);
    await user.click(within(card).getByRole("button", { name: "Edit" }));
    expect(within(card).getByRole("button", { name: "Save edit" })).toBeDisabled();
  });

  it("shows already resolved on a 409 and refreshes the list", async () => {
    const { user } = await setup({
      "GET /v1/review": [
        { status: 200, json: { items: ALL } },
        { status: 200, json: { items: [LOW_CONFIDENCE, RELATION, LEGACY_ANSWER] } },
      ],
      [`POST /v1/review/${BROKEN.id}/resolve`]: {
        status: 409,
        json: { detail: { code: "already_resolved" } },
      },
    });
    await user.click(within(byId(BROKEN.id)).getByRole("button", { name: "Approve" }));

    const notice = await screen.findByRole("alert");
    expect(notice).toHaveTextContent(/already resolved/i);
    await waitFor(() => expect(api!.requests.filter((r) => r.method === "GET")).toHaveLength(2));
    expect(document.querySelector(`[data-item-id="${BROKEN.id}"]`)).toBeNull();
    expect(screen.queryByRole("region", { name: /Broken answers/ })).toBeNull();
  });

  it("rolls the item back when the resolve fails with 500", async () => {
    const { user } = await setup({
      [`POST /v1/review/${RELATION.id}/resolve`]: {
        status: 500,
        json: { detail: "boom" },
        delayMs: 150,
      },
    });
    await user.click(within(itemCard(/Amends SOP-12/)).getByRole("button", { name: "Approve" }));
    // Optimistic: gone while the request is in flight.
    expect(screen.queryByRole("article", { name: /Amends SOP-12/ })).toBeNull();

    const notice = await screen.findByRole("alert");
    expect(notice).toHaveTextContent(/Could not approve/);
    expect(notice).toHaveTextContent("500");
    expect(itemCard(/Amends SOP-12/)).toBeInTheDocument();
    // Back in its place, between the broken answer and the legacy answer.
    expect(screen.getAllByRole("article").map((a) => a.getAttribute("data-item-id"))).toEqual(
      ALL.map((i) => i.id),
    );
  });

  it("focuses the item a drift alert linked to", async () => {
    await setup({}, { focusItem: BROKEN.id });
    await waitFor(() => expect(byId(BROKEN.id)).toHaveFocus());
  });

  it("shows an empty queue", async () => {
    api = await startApiServer({ "GET /v1/review": { status: 200, json: { items: [] } } });
    render(<ReviewQueue tenants={["demo"]} client={createApiClient({ baseUrl: api.url })} />);
    await screen.findByText(/Nothing to review/);
  });

  it("shows a retry when the queue fails to load", async () => {
    api = await startApiServer({
      "GET /v1/review": [
        { status: 503, json: { detail: { code: "unavailable" } }, headers: { "Retry-After": "2" } },
        { status: 200, json: { items: [RELATION] } },
      ],
    });
    const user = userEvent.setup();
    render(<ReviewQueue tenants={["demo"]} client={createApiClient({ baseUrl: api.url })} />);
    const failure = await screen.findByRole("alert");
    expect(failure).toHaveTextContent("Could not load the review queue");
    await user.click(within(failure).getByRole("button", { name: "Retry" }));
    await screen.findByRole("article", { name: /Amends SOP-12/ });
  });
});
