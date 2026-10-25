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
    expect(tile("Documents")).toHaveTextContent("31 versions · 1,234 chunks · 3 sources");
    expect(tile("Ask latency")).toHaveTextContent("5.24 s");
    expect(tile("Cost per answer")).toHaveTextContent("$0.0045");
    expect(tile("Cache hit rate")).toHaveTextContent("25%");
    expect(tile("Review backlog")).toHaveTextContent("3");

    expect(figure("Drift events per day")).toHaveAccessibleDescription(
      "4 drift events in the last 30 days: 1 still valid, 2 changed, 1 broken. Busiest day: Oct 25 with 3.",
    );
    expect(figure("Ask latency")).toHaveAccessibleDescription(/p50 1\.8 s, p95 5\.24 s/);
    expect(figure("Cost per answer")).toHaveAccessibleDescription(/\$0\.0045 per answer/);
    expect(figure("Cache hit rate")).toHaveAccessibleDescription("Cache hit rate 25%: 1 hit and 3 misses.");
    expect(figure("Review backlog")).toHaveAccessibleDescription(/3 open review items/);
    expect(figure("Eval scores")).toHaveAccessibleDescription(
      "Latest eval run bbbbbbb on corpus pharma: Citation precision 0.88, Faithfulness 0.91.",
    );
    expect(api!.requests.map((r) => r.url)).toEqual(["/v1/stats?tenant=demo"]);
  });

  it("shows empty states, never fake numbers, for a tenant with no activity", async () => {
    await setup({ status: 200, json: emptyStats() });

    const kpis = await screen.findByRole("list", { name: "Key figures" });
    expect(within(kpis).getByRole("group", { name: "Ask latency" })).toHaveTextContent("—");
    expect(within(kpis).getByRole("group", { name: "Cache hit rate" })).toHaveTextContent(
      "No cache lookups yet",
    );
    expect(within(figure("Eval scores")).getByText("No eval runs yet.")).toBeInTheDocument();
    expect(within(figure("Ask latency")).getByText(/No finished asks/)).toBeInTheDocument();
    expect(within(figure("Drift events per day")).getByText(/No drift events/)).toBeInTheDocument();
    expect(within(figure("Review backlog")).getByText("The review queue is empty.")).toBeInTheDocument();
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
