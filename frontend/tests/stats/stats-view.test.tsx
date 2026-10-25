import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { StatsView } from "@/components/stats/stats-view";
import { createApiClient } from "@/lib/api/client";

import { startApiServer, type ApiServer, type FixtureResponse } from "../support/api-server";
import { busyStats, emptyStats } from "../support/stats-fixtures";

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

async function setup(stats: FixtureResponse | FixtureResponse[], tenants = ["demo"]) {
  api = await startApiServer({ "GET /v1/stats": stats });
  const user = userEvent.setup();
  render(<StatsView tenants={tenants} client={createApiClient({ baseUrl: api.url })} />);
  return { user };
}

const figure = (name: string) => screen.getByRole("figure", { name });

describe("StatsView", () => {
  it("shows the KPI tiles and describes every chart from the gateway's numbers", async () => {
    await setup({ status: 200, json: busyStats() });

    const kpis = await screen.findByRole("list", { name: "Key figures" });
    const tile = (name: string) => within(kpis).getByRole("group", { name });
    expect(tile("Documents")).toHaveTextContent("12");
    expect(tile("Documents")).toHaveTextContent("31 versions from 3 sources");
    // The exact figures stay one hover away.
    expect(tile("Documents")).toHaveAttribute(
      "title",
      "12 documents, 31 versions, 1,234 passages, 3 sources",
    );
    expect(tile("Typical answer time")).toHaveTextContent("1.8 s");
    expect(tile("Typical answer time")).toHaveTextContent("Slowest 5%: 5.24 s");
    expect(tile("Cost per answer")).toHaveTextContent("$0.0045");
    expect(tile("Answers reused")).toHaveTextContent("25%");
    expect(tile("Waiting for review")).toHaveTextContent("3");

    expect(figure("Changes detected per day")).toHaveAccessibleDescription(
      "4 changes detected in the last 30 days: 1 still valid, 2 changed, 1 broken. Busiest day: Oct 25 with 3.",
    );
    expect(figure("Answer time")).toHaveAccessibleDescription(
      /typical answer took 1\.8 s; the slowest 5% took 5\.24 s/,
    );
    expect(figure("Cost per answer")).toHaveAccessibleDescription(/\$0\.0045 per answer/);
    expect(figure("Answers reused")).toHaveAccessibleDescription(
      "25% of questions reused a saved answer for the same question and date (1 of 4).",
    );
    expect(figure("Waiting for review")).toHaveAccessibleDescription(/3 items waiting/);
    const quality = figure("Latest quality check");
    expect(quality).toHaveAccessibleDescription(
      "Checked on 24 Oct 2026 against the pharma question set: citation accuracy 88%, faithfulness 91%.",
    );
    expect(within(quality).getByText("88%")).toHaveAttribute("title", "Exact score: 0.88");
    expect(within(quality).getByRole("link", { name: /Read the full report/ })).toHaveAttribute(
      "href",
      expect.stringContaining("RESULTS.md"),
    );
    expect(api!.requests.map((r) => r.url)).toEqual(["/v1/stats?tenant=demo"]);
  });

  it("shows empty states, never fake numbers, for a tenant with no activity", async () => {
    await setup({ status: 200, json: emptyStats() });

    const kpis = await screen.findByRole("list", { name: "Key figures" });
    expect(within(kpis).getByRole("group", { name: "Typical answer time" })).toHaveTextContent("—");
    expect(within(kpis).getByRole("group", { name: "Answers reused" })).toHaveTextContent(
      "No questions asked yet",
    );
    expect(
      within(figure("Latest quality check")).getByText("No quality checks yet."),
    ).toBeInTheDocument();
    expect(within(figure("Answer time")).getByText(/No answers in the last/)).toBeInTheDocument();
    expect(
      within(figure("Changes detected per day")).getByText(/No changes detected/),
    ).toBeInTheDocument();
    expect(
      within(figure("Waiting for review")).getByText("Nothing is waiting for review."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/0\.88|Faithfulness/)).not.toBeInTheDocument();
  });

  it("announces loading while the request is in flight", async () => {
    await setup({ status: 200, json: busyStats(), delayMs: 150 });
    expect(screen.getByRole("status")).toHaveTextContent("Loading stats");
    await screen.findByRole("list", { name: "Key figures" });
    expect(screen.queryByText("Loading stats…")).not.toBeInTheDocument();
  });

  it("shows an error with a retry that loads the stats", async () => {
    const { user } = await setup([
      { status: 503, json: { detail: { code: "busy" } } },
      { status: 200, json: busyStats() },
    ]);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not load the stats. The Driftline API is busy");
    await user.click(within(alert).getByRole("button", { name: "Retry" }));
    await screen.findByRole("list", { name: "Key figures" });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(api!.requests).toHaveLength(2);
  });
});
