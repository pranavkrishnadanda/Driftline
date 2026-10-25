/**
 * `prefers-reduced-motion: reduce` (plan Review Focus 3): no Motion, anime.js or CSS
 * animation runs on any view, and all content is visible without waiting for one.
 *
 * Runs against the stub gateway (`npm run test:e2e:stub`) or the real stack. See
 * tests/e2e/views.ts.
 */
import { expect, test } from "@playwright/test";

import { VIEWS, invisibleText, motionDuring, openView } from "./views";

test.use({ reducedMotion: "reduce" });

for (const view of VIEWS) {
  test(`${view.name} (${view.path}) is complete and still`, async ({ page }) => {
    await openView(page, view);
    expect(await page.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches)).toBe(true);

    const motion = await motionDuring(page, 1500);
    expect(motion.running, "animations running").toEqual([]);
    expect(motion.mutations, "styles changing over time").toEqual([]);
    expect(await invisibleText(page), "text that is laid out but invisible").toEqual([]);
  });
}

test("the landing hero shows its finished picture, with no animation control", async ({ page }) => {
  await openView(page, VIEWS[0]);

  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Answers as of any date, from the version in force then.",
  );
  await expect(page.getByRole("link", { name: "Try Ask" })).toBeVisible();
  await expect(page.getByRole("link", { name: "View drift inbox" })).toBeVisible();
  const cards = page.getByRole("list", { name: "Features" }).getByRole("group");
  await expect(cards).toHaveCount(4);
  for (const card of await cards.all()) await expect(card).toBeVisible();

  const hero = page.getByRole("img", { name: "A document drifting through three versions" });
  await expect(hero).toBeVisible();
  // The finished picture: no inline animation state; the document sits at v3, ghosts shown.
  const state = await hero.evaluate((svg) => ({
    doc: (svg.querySelector("[data-hero=doc]") as SVGElement).style.transform,
    ghosts: [...svg.querySelectorAll<SVGElement>("[data-hero=ghost]")].map((g) => [
      g.getAttribute("opacity"),
      g.style.opacity,
    ]),
    alert: getComputedStyle(svg.querySelector("[data-hero=alert]")!).opacity,
  }));
  expect(state).toEqual({
    doc: "translateX(454px)",
    ghosts: [
      ["0.4", ""],
      ["0.4", ""],
    ],
    alert: "1",
  });
  await expect(page.getByRole("button", { name: "Pause animation" })).toHaveCount(0);
  // The departure board holds the latest version instead of flipping.
  await expect(page.getByText("V3 AS OF 2025-02-10")).toBeAttached();
});

test("a flip card turns over at once, without a spin", async ({ page }) => {
  await openView(page, VIEWS[0]);
  const card = page.getByRole("list", { name: "Features" }).getByRole("group").first();
  await card.focus();
  const watching = motionDuring(page, 600);
  await card.press("Enter");
  await expect(card.getByRole("link", { name: /Try Ask/ })).toBeVisible();
  const motion = await watching;
  expect(motion.running).toEqual([]);
  // One jump to the far face is allowed; a spring would write the transform every frame.
  expect(motion.mutations.filter((m) => m.endsWith("style")).length).toBeLessThan(12);
});
