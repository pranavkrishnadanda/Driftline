import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { DocumentTimelineView } from "@/components/timeline/document-timeline-view";
import { createApiClient } from "@/lib/api/client";

import { closedPortUrl, startApiServer, type ApiServer } from "../support/api-server";
import { DOC_ID, OLD_DOC_ID, OTHER_DOC_ID, TIMELINE } from "../support/version-timeline-fixtures";

const NOW = new Date("2026-02-10T00:00:00Z");
const ROUTE = `GET /v1/documents/${DOC_ID}/timeline`;

let api: ApiServer | undefined;

afterEach(async () => {
  await api?.close();
  api = undefined;
});

function renderView(baseUrl: string, reducedMotion = true) {
  const user = userEvent.setup();
  render(
    <DocumentTimelineView
      documentId={DOC_ID}
      tenant="demo"
      client={createApiClient({ baseUrl })}
      now={NOW}
      reducedMotion={reducedMotion}
    />,
  );
  return user;
}

function diffSection() {
  return screen.getByRole("region", { name: /^Changes in|is the first version/ });
}

describe("DocumentTimelineView", () => {
  it("loads the timeline for the tenant and opens on the current version", async () => {
    api = await startApiServer({ [ROUTE]: { status: 200, json: TIMELINE } });
    renderView(api.url);

    expect(screen.getByRole("status")).toHaveTextContent(/Loading timeline/);
    expect(
      await screen.findByRole("heading", { level: 1, name: "Metformin label" }),
    ).toBeInTheDocument();
    expect(api.requests[0].url).toBe(`/v1/documents/${DOC_ID}/timeline?tenant=demo`);

    const slider = screen.getByRole("slider", { name: "Version" });
    expect(slider).toHaveAttribute("aria-valuemin", "1");
    expect(slider).toHaveAttribute("aria-valuemax", "3");
    expect(slider).toHaveAttribute("aria-valuenow", "3");
    expect(slider).toHaveAttribute("aria-valuetext", "v3: from 31 Jan 2026, in force now");

    expect(screen.getByRole("heading", { level: 2, name: "Changes in v3 since v2" })).toBeInTheDocument();
    const table = within(diffSection()).getByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "v2 (before)",
      "v3 (after)",
    ]);
    const removed = within(table).getByRole("row", { name: /B > Renal/ });
    expect(within(removed).getAllByRole("cell")[0]).toHaveTextContent("B > Renal");
    expect(within(removed).getAllByRole("cell")[0]).toHaveTextContent("removed");
    expect(within(removed).getAllByRole("cell")[1]).toHaveTextContent("not present");
  });

  it("scrubbing with the keyboard selects a version and updates the diff", async () => {
    api = await startApiServer({ [ROUTE]: { status: 200, json: TIMELINE } });
    const user = renderView(api.url);
    const slider = await screen.findByRole("slider", { name: "Version" });

    slider.focus();
    await user.keyboard("{ArrowLeft}");
    expect(slider).toHaveAttribute("aria-valuenow", "2");
    expect(slider).toHaveAttribute("aria-valuetext", "v2: 11 Jan 2026 – 31 Jan 2026");
    expect(screen.getByRole("heading", { level: 2, name: "Changes in v2 since v1" })).toBeInTheDocument();
    const added = within(diffSection()).getByRole("row", { name: /B > Renal/ });
    expect(within(added).getAllByRole("cell")[0]).toHaveTextContent("not present");
    expect(within(added).getAllByRole("cell")[1]).toHaveTextContent("added");
    expect(diffSection()).toHaveTextContent("1 added · 1 changed · 0 removed · 1 unchanged");

    await user.keyboard("{Home}");
    expect(slider).toHaveAttribute("aria-valuenow", "1");
    expect(screen.getByRole("heading", { level: 2, name: "v1 is the first version" })).toBeInTheDocument();
    expect(within(diffSection()).queryByRole("table")).not.toBeInTheDocument();

    await user.keyboard("{End}");
    expect(slider).toHaveAttribute("aria-valuenow", "3");
    await user.keyboard("{ArrowRight}");
    expect(slider).toHaveAttribute("aria-valuenow", "3");
  });

  it("selects a version from the version list", async () => {
    api = await startApiServer({ [ROUTE]: { status: 200, json: TIMELINE } });
    const user = renderView(api.url);
    const list = await screen.findByRole("list", { name: "Versions" });

    const v2 = within(list).getByRole("button", { name: /^v2/ });
    expect(v2).toHaveTextContent("11 Jan 2026 – 31 Jan 2026");
    await user.click(v2);
    expect(v2).toHaveAttribute("aria-pressed", "true");
    expect(within(list).getByRole("button", { name: /^v3/ })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("slider", { name: "Version" })).toHaveAttribute("aria-valuenow", "2");
    expect(screen.getByRole("heading", { level: 2, name: "Changes in v2 since v1" })).toBeInTheDocument();
  });

  it("lists incoming and outgoing relations with links to their timelines", async () => {
    api = await startApiServer({ [ROUTE]: { status: 200, json: TIMELINE } });
    renderView(api.url);
    const graph = await screen.findByRole("region", { name: "Supersession" });

    const incoming = within(graph).getByRole("list", { name: "Declared by other documents" });
    const link = within(incoming).getByRole("link", { name: OTHER_DOC_ID.slice(0, 8) });
    expect(link).toHaveAttribute("href", `/documents/${OTHER_DOC_ID}?tenant=demo`);
    expect(incoming).toHaveTextContent("amends");
    expect(incoming).toHaveTextContent("pending");
    expect(incoming).toHaveTextContent("61%");

    const outgoing = within(graph).getByRole("list", { name: "Declared by this document" });
    expect(within(outgoing).getByRole("link", { name: "Metformin label (2019)" })).toHaveAttribute(
      "href",
      `/documents/${OLD_DOC_ID}?tenant=demo`,
    );
    expect(outgoing).toHaveTextContent("supersedes");
    expect(outgoing).toHaveTextContent("from v2");
  });

  it("says when a document has no relations", async () => {
    api = await startApiServer({
      [ROUTE]: { status: 200, json: { ...TIMELINE, relations: { incoming: [], outgoing: [] } } },
    });
    renderView(api.url);
    const graph = await screen.findByRole("region", { name: "Supersession" });
    expect(graph).toHaveTextContent("No relations recorded for this document.");
  });

  it("explains an unknown document and links back to the picker", async () => {
    api = await startApiServer({
      [ROUTE]: { status: 404, json: { detail: { code: "unknown_document" } } },
    });
    renderView(api.url);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This document was not found in tenant demo.");
    expect(within(alert).getByRole("link", { name: "Choose another document" })).toHaveAttribute(
      "href",
      "/timeline",
    );
  });

  it("offers a retry when the gateway is unreachable", async () => {
    const url = await closedPortUrl();
    const user = renderView(url);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't load the timeline");
    expect(alert).toHaveTextContent("Driftline API unreachable");
    await user.click(within(alert).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  });
});
