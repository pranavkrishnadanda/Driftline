/**
 * The recorded demo's static export in a browser (`bun run test:e2e:demo`): every view
 * works from `public/demo/recording.json` alone, under the GitHub Pages base path.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import type { DemoRecording } from "../../../src/lib/demo/recording";

const recording = JSON.parse(
  readFileSync(join(__dirname, "../../../public/demo/recording.json"), "utf8"),
) as DemoRecording;

const PAGES = ["", "ask/", "timeline/", "drift/", "review/", "stats/"];

for (const path of PAGES) {
  test(`/${path} shows the recorded-demo banner and has no serious axe violations`, async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(path);
    const banner = page.getByRole("region", { name: "Recorded demo" });
    await expect(banner).toContainText("real answers captured from a live run on");
    await expect(banner.getByRole("link", { name: "quick start" })).toHaveAttribute(
      "href",
      /github\.com\/.*#quick-start$/,
    );
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(
      results.violations.filter((v) => v.impact === "serious" || v.impact === "critical"),
    ).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test("navigation stays under the base path", async ({ page }) => {
  await page.goto("");
  await page
    .getByRole("navigation", { name: "Views" })
    .getByRole("link", { name: "Stats" })
    .click();
  await expect(page).toHaveURL(/\/Driftline\/demo\/stats\/$/);
  await expect(page.getByRole("heading", { name: "Stats" })).toBeVisible();
});

test("a recorded question streams its recorded answer in full", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("ask/");
  const chips = page.getByTestId("demo-suggestion");
  await expect(chips).toHaveCount(recording.asks.length);
  const ask = recording.asks.findIndex((a) => a.job.answer?.answer);
  await chips.nth(ask).click();
  const answer = recording.asks[ask].job.answer!;
  await expect(page.getByText(recording.asks[ask].request.question).first()).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Answer ready." })).toBeAttached({
    timeout: 30_000,
  });
  await expect(page.getByTestId("demo-match-note")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "How this answer was built" })).toBeVisible();
  // The final answer's first words are on the page.
  await expect(page.getByText(answer.answer.slice(0, 40), { exact: false }).first()).toBeVisible();
});

test("a typed question gets the closest recorded answer, and says so", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("ask/");
  const question = `${recording.asks[0].request.question.split(" ").slice(0, 4).join(" ")} please`;
  await page.getByRole("textbox").fill(question);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("demo-match-note")).toContainText(
    "Showing the recorded answer to the closest demo question:",
  );
});

test("the timeline lists the recorded documents and opens one", async ({ page }) => {
  await page.goto("timeline/");
  const docs = page.getByRole("list", { name: "Recorded documents" }).getByRole("link");
  await expect(docs).toHaveCount(Object.keys(recording.timelines).length);
  await docs.first().click();
  await expect(page).toHaveURL(/\/documents\/[0-9a-f-]+\//);
  await expect(page.getByText(/version/i).first()).toBeVisible();
});

test("drift shows the recorded alerts", async ({ page }) => {
  await page.goto("drift/");
  await expect(page.getByRole("status").filter({ hasText: "Live" })).toBeVisible();
  const ids = new Set([
    ...recording.drift_events.map((e) => e.id),
    ...recording.alerts.map((a) => (a.data as { drift_event_id?: string }).drift_event_id),
  ]);
  ids.delete(undefined as never);
  await expect(page.getByRole("list", { name: "Drift alerts" }).getByRole("listitem")).toHaveCount(
    ids.size,
  );
});

test("review: approving an item works for the visit and is not persisted", async ({ page }) => {
  const open = recording.review.filter((i) => i.status === "open");
  test.skip(open.length === 0, "the recording has no open review item");
  await page.goto("review/");
  const items = page.locator("[data-item-id]");
  await expect(items).toHaveCount(open.length);
  await page.getByRole("button", { name: "Approve" }).first().click();
  await expect(page.getByRole("status").filter({ hasText: /^Approved/ })).toBeVisible();
  await expect(items).toHaveCount(open.length - 1);
  await page.reload();
  await expect(items).toHaveCount(open.length);
});
