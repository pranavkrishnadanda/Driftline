/**
 * `/stats` render check against the real backend stack (deploy/compose with
 * DRIFTLINE_LLM_OFFLINE=true).
 *
 *   DRIFTLINE_E2E_API     the gateway URL, e.g. http://localhost:8010 (required; the spec
 *                         skips without it). Start the frontend with NEXT_PUBLIC_DRIFTLINE_API
 *                         set to the same URL.
 *   DRIFTLINE_E2E_TENANT  tenant (default "demo"). It must be the first tenant in the
 *                         frontend's NEXT_PUBLIC_DRIFTLINE_TENANTS, which `/stats` opens on.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const API = process.env.DRIFTLINE_E2E_API;
const TENANT = process.env.DRIFTLINE_E2E_TENANT ?? "demo";

test.skip(
  !API,
  "DRIFTLINE_E2E_API is not set: this spec needs the real backend stack (Compose with " +
    "DRIFTLINE_LLM_OFFLINE=true). See the header of stats.spec.ts.",
);

interface Stats {
  corpus: { documents: number };
  drift: { total: number };
  latest_eval: unknown;
}

const PANELS = [
  "Drift events per day",
  "Ask latency",
  "Cost per answer",
  "Cache hit rate",
  "Review backlog",
  "Eval scores",
];

async function expectRendered(page: Page, stats: Stats): Promise<void> {
  await expect(page.getByRole("heading", { level: 1, name: "Stats" })).toBeVisible();
  const kpis = page.getByRole("list", { name: "Key figures" });
  await expect(kpis).toBeVisible();
  await expect(kpis.getByRole("group", { name: "Documents" })).toContainText(
    new Intl.NumberFormat("en-US").format(stats.corpus.documents),
  );
  for (const name of PANELS) {
    await expect(page.getByRole("figure", { name })).toBeVisible();
  }
  const drift = page.getByRole("figure", { name: "Drift events per day" });
  if (stats.drift.total > 0) await expect(drift.locator("svg").first()).toBeVisible();
  if (stats.latest_eval === null) {
    await expect(page.getByRole("figure", { name: "Eval scores" })).toContainText("No eval runs yet.");
  }
}

test.describe("Stats (real backend)", () => {
  test("renders the gateway's numbers with Bklit charts and Kokonut KPI cards", async ({
    page,
    request,
  }) => {
    const res = await request.get(`${API}/v1/stats?tenant=${TENANT}`);
    expect(res.ok(), "GET /v1/stats failed").toBe(true);
    const stats = (await res.json()) as Stats;

    await page.goto("/stats");
    await expectRendered(page, stats);

    const axe = await new AxeBuilder({ page }).analyze();
    const serious = axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(serious, JSON.stringify(serious.map((v) => v.id))).toEqual([]);
  });

  test.describe("with reduced motion", () => {
    test.use({ reducedMotion: "reduce" });

    test("shows the same complete content", async ({ page, request }) => {
      const stats = (await (await request.get(`${API}/v1/stats?tenant=${TENANT}`)).json()) as Stats;
      await page.goto("/stats");
      await expectRendered(page, stats);
    });
  });
});
