/**
 * axe on every view: no serious or critical accessibility violations.
 *
 * Runs against the stub gateway (`npm run test:e2e:stub`) or the real stack (`npm run
 * test:e2e` with NEXT_PUBLIC_DRIFTLINE_API pointing at it). See tests/e2e/views.ts.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { VIEWS, openView } from "./views";

async function seriousViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"])
    .analyze();
  return results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => ({
      id: v.id,
      impact: v.impact,
      help: v.help,
      nodes: v.nodes.map((n) => `${n.target.join(" ")}: ${n.failureSummary?.split("\n").slice(1).join(" ")}`),
    }));
}

for (const view of VIEWS) {
  test(`${view.name} (${view.path}) has no serious or critical axe violations`, async ({ page }) => {
    await openView(page, view);
    const violations = await seriousViolations(page);
    expect(violations, JSON.stringify(violations, null, 2)).toEqual([]);
  });
}

test("the landing page's flip cards stay accessible with their backs turned", async ({ page }) => {
  await openView(page, VIEWS[0]);
  const cards = page.getByRole("list", { name: "Features" }).getByRole("group");
  await expect(cards).toHaveCount(4);
  for (const card of await cards.all()) {
    await card.focus();
    await card.press("Enter");
  }
  await expect(cards.first().getByRole("link", { name: /Try Ask/ })).toBeVisible();
  const violations = await seriousViolations(page);
  expect(violations, JSON.stringify(violations, null, 2)).toEqual([]);
});

test("every interactive element on the landing page is reachable by keyboard", async ({ page }) => {
  await openView(page, VIEWS[0]);
  const reached = new Set<string>();
  for (let i = 0; i < 20; i++) {
    await page.keyboard.press("Tab");
    const name = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      return el?.getAttribute("aria-label") ?? el?.textContent?.trim().slice(0, 40) ?? "";
    });
    reached.add(name);
  }
  for (const name of ["Try Ask", "View drift inbox", "As-of answers with verified citations", "MCP for agents"]) {
    expect([...reached].some((r) => r.startsWith(name)), `${name} not reached; got ${[...reached].join(" | ")}`).toBe(true);
  }
});
