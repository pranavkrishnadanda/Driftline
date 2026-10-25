/**
 * Things that must actually be drawn, checked in a real browser against the stub gateway
 * (`bun run test:e2e:stub`):
 *
 * - every `/stats` chart has visible marks (bars, lines, gauge notches) of non-zero size,
 *   right after load and after a full-page capture. A capture re-lays out the page and
 *   used to report a 0×0 chart size for a moment, which unmounted every Bklit chart and
 *   replayed its grow-from-zero entrance, so the page showed empty chart boxes;
 * - the landing page's split-flap board settles on a real date, never half-turned text
 *   such as "V3 AS OF 2025-0/-00".
 */
import { expect, test, type Page } from "@playwright/test";

import { VIEWS, openView } from "./views";

test.use({ viewport: { width: 1440, height: 900 } });

const STATS = VIEWS.find((v) => v.name === "stats")!;
const LANDING = VIEWS.find((v) => v.name === "landing")!;

/** Every chart panel on /stats with data in the stub, by its figure name. */
const CHARTS = [
  "Changes detected per day",
  "Answer time",
  "Cost per answer",
  "Answers reused",
  "Waiting for review",
  "Latest quality check",
];

/** For each chart: how many marks it draws with a non-zero, painted size. */
function drawnMarks(page: Page): Promise<Record<string, number>> {
  return page.evaluate((names) => {
    const out: Record<string, number> = {};
    for (const figure of document.querySelectorAll("figure")) {
      const name = figure.querySelector("h2")?.textContent ?? "";
      if (!names.includes(name)) continue;
      const marks = [...figure.querySelectorAll<SVGGraphicsElement>("svg rect, svg path")].filter(
        (mark) => {
          if (mark.closest("defs, clipPath, mask, pattern, linearGradient")) return false;
          const paint = getComputedStyle(mark);
          const fill = mark.getAttribute("fill") ?? paint.fill;
          const stroke = mark.getAttribute("stroke") ?? paint.stroke;
          const painted =
            (fill && fill !== "none" && fill !== "transparent") ||
            (stroke && stroke !== "none" && stroke !== "transparent");
          // Series marks use the chart colour tokens, gradients or the gauge's fills.
          const series = /var\(--|url\(#/.test(`${fill} ${stroke}`);
          const box = mark.getBBox();
          const rect = mark.getBoundingClientRect();
          return (
            painted &&
            series &&
            box.width > 0 &&
            box.height > 0 &&
            rect.width > 0 &&
            rect.height > 0 &&
            paint.visibility !== "hidden" &&
            Number(paint.opacity) > 0
          );
        },
      );
      // The clip-path reveal of line charts must be open too, or the lines are hidden.
      const clips = [...figure.querySelectorAll("clipPath rect")].map((r) =>
        Number.parseFloat(r.getAttribute("width") ?? "0"),
      );
      out[name] = clips.some((w) => w < 1) ? 0 : marks.length;
    }
    return out;
  }, CHARTS);
}

async function expectAllDrawn(page: Page, when: string): Promise<void> {
  const marks = await drawnMarks(page);
  for (const name of CHARTS) {
    expect(marks[name] ?? 0, `${name} has no drawn marks ${when}`).toBeGreaterThan(0);
  }
}

test("every /stats chart draws its marks, and keeps them through a full-page capture", async ({
  page,
}) => {
  await openView(page, STATS);
  await expect.poll(() => drawnMarks(page).then((m) => Object.keys(m).length)).toBe(CHARTS.length);
  await expectAllDrawn(page, "after load");

  // Once the entrance has finished (the bars are static), a full-page capture made the
  // chart parents report 0x0 for a moment; without the fix this is where they went blank.
  await page.waitForTimeout(2500);
  await page.screenshot({ fullPage: true });
  await expectAllDrawn(page, "right after a full-page capture");

  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() => drawnMarks(page).then((m) => Math.min(...Object.values(m))))
    .toBeGreaterThan(0);
});

test("the verdict colours are the green, amber and red tokens, not greys", async ({ page }) => {
  await openView(page, STATS);
  const fills = await page
    .getByRole("figure", { name: "Changes detected per day" })
    .evaluate((figure) => [
      ...new Set(
        [...figure.querySelectorAll("svg rect[fill^='var(--']")].map((r) => r.getAttribute("fill")),
      ),
    ]);
  expect(fills.sort()).toEqual(["var(--broken)", "var(--changed)", "var(--valid)"]);
});

test("the landing as-of board always settles on a valid date", async ({ page }) => {
  await page.goto(LANDING.path);
  const board = page.locator("[data-ambient]").first();
  const read = () =>
    board.evaluate((el) => ({
      text: [...el.querySelectorAll<HTMLElement>("[data-char]")]
        .map((t) => t.dataset.char)
        .join("")
        .trimEnd(),
      flipping: el.querySelector("[data-flipping]") !== null,
    }));
  // Sample the board through several word changes (it cycles every 2.8 s): whenever no
  // tile is mid-flip, it must read as a version and a real date.
  const settled = new Set<string>();
  const deadline = Date.now() + 9_000;
  while (Date.now() < deadline) {
    const { text, flipping } = await read();
    if (!flipping) {
      expect(text).toMatch(/^V\d AS OF \d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/);
      settled.add(text);
    }
    await page.waitForTimeout(120);
  }
  expect(settled.size, `settled boards: ${[...settled].join(", ")}`).toBeGreaterThan(1);
});
