/**
 * Every view of the app, for checks that visit them all (a11y.spec.ts,
 * reduced-motion.spec.ts). Data-agnostic: they work against the stub gateway
 * (`bun run test:e2e:stub`) and the real stack alike.
 *
 *   DRIFTLINE_E2E_DOCUMENT_ID  the document for /documents/[id]; defaults to the stub's.
 */
import { expect, type Page } from "@playwright/test";

const STUB_DOCUMENT_ID = "0b6f7e52-6a49-4d0e-9a3c-2f5d1c7e8a10";
const DOCUMENT_ID = process.env.DRIFTLINE_E2E_DOCUMENT_ID ?? STUB_DOCUMENT_ID;

export interface View {
  name: string;
  path: string;
}

export const VIEWS: View[] = [
  { name: "landing", path: "/" },
  { name: "ask", path: "/ask" },
  { name: "timeline", path: "/timeline" },
  { name: "document", path: `/documents/${DOCUMENT_ID}` },
  { name: "drift", path: "/drift" },
  { name: "review", path: "/review" },
  { name: "stats", path: "/stats" },
];

/**
 * Open a view and wait until it has settled: its title is up and nothing says it is still
 * loading. (Not `networkidle`: the drift inbox holds its alert stream open.)
 */
export async function openView(page: Page, view: View): Promise<void> {
  await page.goto(view.path);
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
  await expect(page.getByText(/^Loading/)).toHaveCount(0, { timeout: 15_000 });
  await expect(page.locator("[aria-busy=true]")).toHaveCount(0, { timeout: 15_000 });
  await settle(page);
}

/**
 * Wait for entrance animations (alert cards, marker strokes) to finish: a 400 ms window
 * with no running CSS/Web Animation and no inline style written (Motion and anime.js
 * animate from requestAnimationFrame). Looping decorations marked `data-ambient` (the
 * landing hero) are ignored.
 */
export async function settle(page: Page): Promise<void> {
  await page.waitForFunction(
    () =>
      new Promise<boolean>((resolve) => {
        const ambient = (n: unknown) =>
          n instanceof Element && n.closest("[data-ambient]") !== null;
        const busy = () =>
          document
            .getAnimations()
            .some(
              (a) =>
                a.playState === "running" && !ambient((a.effect as KeyframeEffect | null)?.target),
            );
        let moved = false;
        const observer = new MutationObserver((records) => {
          if (records.some((r) => !ambient(r.target))) moved = true;
        });
        observer.observe(document.body, {
          subtree: true,
          attributes: true,
          attributeFilter: ["style"],
        });
        const before = busy();
        setTimeout(() => {
          observer.disconnect();
          resolve(!before && !busy() && !moved);
        }, 400);
      }),
    undefined,
    { timeout: 10_000, polling: 50 },
  );
}

/**
 * Text in `<main>` that is laid out but cannot be seen (opacity ~0 or visibility hidden),
 * as when an entrance animation never finished. Text that is deliberately out of view is
 * skipped: `display: none`, `aria-hidden`, `inert` (a flip card's far side), screen-reader
 * only text, and SVG (checked separately).
 */
export function invisibleText(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const main = document.querySelector("main");
    if (!main) return ["<no main>"];
    const out: string[] = [];
    const walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const text = walker.currentNode.textContent?.trim();
      const el = walker.currentNode.parentElement;
      if (!text || !el) continue;
      if (el.closest("[aria-hidden=true], [inert], .sr-only, svg, script, style, noscript"))
        continue;
      if (!el.checkVisibility()) continue;
      let opacity = 1;
      for (let e: Element | null = el; e; e = e.parentElement) {
        opacity *= Number(getComputedStyle(e).opacity);
      }
      if (opacity < 0.05 || getComputedStyle(el).visibility === "hidden")
        out.push(text.slice(0, 80));
    }
    return out;
  });
}

/**
 * Watch the page for `ms`: every running CSS/Web Animation, and every inline style or
 * animated SVG attribute that changes (anime.js and Motion's frame loop write these).
 */
export function motionDuring(
  page: Page,
  ms: number,
): Promise<{ running: string[]; mutations: string[] }> {
  return page.evaluate(async (ms) => {
    const describe = (n: Node | null): string => {
      if (!(n instanceof Element)) return String(n);
      const id = n.id ? `#${n.id}` : "";
      const data = n.getAttribute("data-hero") ?? n.getAttribute("data-testid");
      return `${n.tagName.toLowerCase()}${id}${data ? `[${data}]` : ""}`;
    };
    const mutations: string[] = [];
    const observer = new MutationObserver((records) => {
      for (const r of records) mutations.push(`${describe(r.target)} ${r.attributeName}`);
    });
    observer.observe(document.body, {
      subtree: true,
      attributes: true,
      attributeFilter: [
        "style",
        "transform",
        "opacity",
        "r",
        "width",
        "d",
        "points",
        "stroke-dashoffset",
      ],
    });
    const running = new Set<string>();
    const sample = () => {
      for (const a of document.getAnimations()) {
        if (a.playState !== "running") continue;
        const target = (a.effect as KeyframeEffect | null)?.target ?? null;
        const property = a instanceof CSSTransition ? ` (${a.transitionProperty})` : "";
        running.add(`${a.constructor.name}${property} on ${describe(target)}`);
      }
    };
    sample();
    for (let t = 0; t < ms; t += 100) {
      await new Promise((r) => setTimeout(r, 100));
      sample();
    }
    observer.disconnect();
    return { running: [...running], mutations };
  }, ms);
}
