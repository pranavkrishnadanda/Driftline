/**
 * Ask view against the real backend stack (deploy/compose with DRIFTLINE_LLM_OFFLINE=true).
 *
 * Needs a gateway with the agent worker running and a tenant with an ingested document:
 *   DRIFTLINE_E2E_API       the gateway URL, e.g. http://localhost:8010 (required; the spec
 *                           skips without it). Start the frontend with
 *                           NEXT_PUBLIC_DRIFTLINE_API set to the same URL.
 *   DRIFTLINE_E2E_TENANT    tenant to ask (default "demo"); must be listed in
 *                           NEXT_PUBLIC_DRIFTLINE_TENANTS.
 *   DRIFTLINE_E2E_QUESTION  a question the uploaded fixture document answers.
 *   DRIFTLINE_E2E_AS_OF     optional as-of date, YYYY-MM-DD.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const API = process.env.DRIFTLINE_E2E_API;
const TENANT = process.env.DRIFTLINE_E2E_TENANT ?? "demo";
const QUESTION =
  process.env.DRIFTLINE_E2E_QUESTION ?? "What does the uploaded document say about dosing?";

test.skip(
  !API,
  "DRIFTLINE_E2E_API is not set: this spec needs the real backend stack (Compose with " +
    "DRIFTLINE_LLM_OFFLINE=true and the P3 agent worker). See the header of ask.spec.ts.",
);

test.describe("Ask view (real backend)", () => {
  test.beforeAll(async ({ request }) => {
    const health = await request.get(`${API}/healthz`);
    expect(health.ok(), `gateway at ${API} is not healthy`).toBe(true);
  });

  test("navigation reaches every view without a 404", async ({ page }) => {
    await page.goto("/ask");
    const nav = page.getByRole("navigation", { name: "Views" });
    for (const name of ["Timeline", "Drift", "Review", "Stats", "Ask"]) {
      await nav.getByRole("link", { name }).click();
      await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
      await expect(nav.getByRole("link", { name })).toHaveAttribute("aria-current", "page");
    }
  });

  test("asks a question and shows the final answer with citations", async ({ page }) => {
    await page.goto("/ask");

    const tenant = page.getByRole("combobox", { name: "Tenant" });
    if ((await tenant.textContent())?.trim() !== TENANT) {
      await tenant.click();
      await page.getByRole("option", { name: TENANT }).click();
    }

    const question = page.getByRole("textbox", { name: "Question" });
    await question.fill(QUESTION);
    await question.press("Enter");

    const answer = page.getByRole("region", { name: "Answer" });
    await expect(answer).toBeVisible({ timeout: 60_000 });

    await expect(
      answer.getByRole("heading", { name: /Not enough evidence|declined/ }),
      "the fixture question was refused; check DRIFTLINE_E2E_QUESTION and the uploaded document",
    ).toHaveCount(0);
    await expect(answer.getByRole("list", { name: "Claims" })).toBeVisible();
    const citation = answer.getByRole("button", { name: /^Citation 1/ });
    await citation.focus();
    const tip = page.getByRole("tooltip");
    await expect(tip).toBeVisible();
    await expect(tip).toContainText("Valid from");

    const results = await new AxeBuilder({ page }).analyze();
    const serious = results.violations.filter(
      (v) => v.impact === "serious" || v.impact === "critical",
    );
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
  });

  test("the Ask view has no serious or critical axe violations before asking", async ({ page }) => {
    await page.goto("/ask");
    await expect(page.getByRole("textbox", { name: "Question" })).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    const serious = results.violations.filter(
      (v) => v.impact === "serious" || v.impact === "critical",
    );
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
  });
});
