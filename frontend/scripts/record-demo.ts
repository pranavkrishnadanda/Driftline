#!/usr/bin/env bun
/**
 * Records a guided tour of the recorded demo (the static export) as a video, then turns
 * it into the README media with ffmpeg:
 *
 *   docs/media/driftline-demo.mp4   the whole tour, H.264
 *   docs/media/driftline-ask.gif    just the Ask flow (20-30 s), for the top of the README
 *
 *   NEXT_PUBLIC_DRIFTLINE_DEMO=1 bun run build          # the export, in out/
 *   PLAYWRIGHT_BROWSERS_PATH=0 bunx playwright install chromium
 *   PLAYWRIGHT_BROWSERS_PATH=0 bun scripts/record-demo.ts
 *
 * Options: `--url` (a demo already being served; otherwise `out/` is served on
 * `--port`), `--out` (default ../docs/media), `--ffmpeg` (default /opt/homebrew/bin/ffmpeg).
 * The tour is paced for people: a pause of about 1.5 to 3 s after each step.
 */
import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { parseArgs } from "node:util";

import { chromium, type Locator, type Page } from "@playwright/test";

import type { DemoRecording } from "../src/lib/demo/recording";

const { values } = parseArgs({
  options: {
    url: { type: "string" },
    port: { type: "string", default: "3201" },
    out: { type: "string", default: "../docs/media" },
    ffmpeg: { type: "string", default: "/opt/homebrew/bin/ffmpeg" },
    "max-mp4-mb": { type: "string", default: "15" },
    "max-gif-mb": { type: "string", default: "10" },
  },
});

const WIDTH = 1440;
const HEIGHT = 900;
const outDir = resolve(values.out ?? "../docs/media");
const ffmpeg = values.ffmpeg ?? "/opt/homebrew/bin/ffmpeg";
const recording = JSON.parse(
  readFileSync(join(import.meta.dirname, "..", "public", "demo", "recording.json"), "utf8"),
) as DemoRecording;

/** A visible cursor: headless video has none, and people need to see what is clicked. */
const CURSOR_SCRIPT = `
  addEventListener("DOMContentLoaded", () => {
    const dot = document.createElement("div");
    dot.id = "tour-cursor";
    dot.style.cssText = "position:fixed;z-index:2147483647;left:0;top:0;width:22px;height:22px;" +
      "margin:-11px 0 0 -11px;border-radius:50%;pointer-events:none;" +
      "background:rgba(99,102,241,.35);border:2px solid rgba(79,70,229,.9);" +
      "box-shadow:0 0 0 4px rgba(255,255,255,.6);transition:transform .15s ease;" +
      "transform:translate(-100px,-100px)";
    document.body.appendChild(dot);
    let x = -100, y = -100;
    addEventListener("mousemove", (e) => { x = e.clientX; y = e.clientY;
      dot.style.transform = "translate(" + x + "px," + y + "px)"; }, true);
    addEventListener("mousedown", () => {
      dot.style.transform = "translate(" + x + "px," + y + "px) scale(.7)"; }, true);
    addEventListener("mouseup", () => {
      dot.style.transform = "translate(" + x + "px," + y + "px)"; }, true);
  });
`;

const pause = (page: Page, ms: number) => page.waitForTimeout(ms);

async function pointAt(page: Page, target: Locator): Promise<void> {
  await target.scrollIntoViewIfNeeded();
  const box = await target.boundingBox();
  if (!box) throw new Error("tour target is not visible");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 25 });
}

async function clickOn(page: Page, target: Locator, after = 1800): Promise<void> {
  await pointAt(page, target);
  await pause(page, 350);
  await target.click();
  await pause(page, after);
}

async function scrollBy(page: Page, dy: number): Promise<void> {
  for (let i = 0; i < 10; i++) {
    await page.mouse.wheel(0, dy / 10);
    await pause(page, 40);
  }
}

/** The question asked at two as-of dates (the drift "trap"), else the first answered one. */
function trapQuestion(): { first: number; second: number | null } {
  const byQuestion = new Map<string, number[]>();
  recording.asks.forEach((ask, i) => {
    const list = byQuestion.get(ask.request.question) ?? [];
    list.push(i);
    byQuestion.set(ask.request.question, list);
  });
  for (const indexes of byQuestion.values()) {
    if (indexes.length < 2) continue;
    const sorted = [...indexes].sort((a, b) =>
      (recording.asks[a].request.as_of ?? "9999").localeCompare(
        recording.asks[b].request.as_of ?? "9999",
      ),
    );
    return { first: sorted[0], second: sorted[1] };
  }
  const answered = recording.asks.findIndex((a) => a.job.answer?.status === "answered");
  return { first: Math.max(0, answered), second: null };
}

async function waitForAnswer(page: Page): Promise<void> {
  await page
    .getByRole("status")
    .filter({ hasText: /Answer ready\.|Waiting for human review\./ })
    .waitFor({ state: "attached", timeout: 60_000 });
}

async function tour(page: Page, base: string, marks: Record<string, number>, t0: number) {
  const mark = (name: string) => {
    marks[name] = (Date.now() - t0) / 1000;
  };
  const trap = trapQuestion();
  const chips = page.getByTestId("demo-suggestion");

  // 1. Landing: let the hero animate.
  await page.goto(base);
  await pause(page, 4500);
  await page.mouse.move(WIDTH / 2, HEIGHT / 2, { steps: 20 });
  await scrollBy(page, 500);
  await pause(page, 2000);
  await scrollBy(page, -500);

  // 2. Ask a trap question, watch it stream, open how it was built, hover a source.
  mark("ask_start");
  await clickOn(page, page.getByRole("banner").getByRole("link", { name: "Try Ask" }), 2000);
  await clickOn(page, chips.nth(trap.first), 0);
  await waitForAnswer(page);
  await pause(page, 2000);
  const steps = page.getByRole("button", { name: "Show steps" });
  if (await steps.count()) await clickOn(page, steps.first(), 2500);
  const citation = page.getByRole("button", { name: /^Citation 1:/ }).first();
  if (await citation.count()) {
    await pointAt(page, citation);
    await pause(page, 3000);
  }
  mark("ask_end");

  // 3. The same question at another as-of date: the answer changes.
  if (trap.second !== null) {
    await scrollBy(page, 900);
    await clickOn(page, chips.nth(trap.second), 0);
    await waitForAnswer(page);
    await pause(page, 3000);
  }

  // 4. Timeline: open a document, scrub its versions, show the related documents.
  await clickOn(
    page,
    page.getByRole("navigation", { name: "Views" }).getByRole("link", { name: "Timeline" }),
    2000,
  );
  const drifted = recording.drift_events.find((e) => e.document_id)?.document_id;
  const docLinks = page.getByRole("list", { name: "Recorded documents" }).getByRole("link");
  const preferred = drifted ? docLinks.and(page.locator(`[href*="${drifted}"]`)) : null;
  await clickOn(
    page,
    preferred && (await preferred.count()) ? preferred.first() : docLinks.first(),
    2500,
  );
  const versions = page.getByRole("list", { name: "Versions" }).getByRole("button");
  const count = await versions.count();
  for (let i = 0; i < count; i++) await clickOn(page, versions.nth(i), 1600);
  const graph = page.getByRole("group", { name: "Related documents graph" });
  if (await graph.count()) {
    await graph.scrollIntoViewIfNeeded();
    await pointAt(page, graph);
    await pause(page, 3000);
  }

  // 5. Drift: a real alert and its diff.
  await clickOn(
    page,
    page.getByRole("navigation", { name: "Views" }).getByRole("link", { name: "Drift" }),
    2500,
  );
  const details = page.getByRole("button", { name: "Details" });
  if (await details.count()) await clickOn(page, details.first(), 3000);

  // 6. Review: approve an item.
  await clickOn(
    page,
    page.getByRole("navigation", { name: "Views" }).getByRole("link", { name: "Review" }),
    2500,
  );
  const approve = page.getByRole("button", { name: "Approve" });
  if (await approve.count()) await clickOn(page, approve.first(), 2500);

  // 7. Stats: the charts draw.
  await clickOn(
    page,
    page.getByRole("navigation", { name: "Views" }).getByRole("link", { name: "Stats" }),
    4000,
  );
  await scrollBy(page, 700);
  await pause(page, 2500);
  await scrollBy(page, -700);

  // 8. Dark mode, briefly.
  await clickOn(page, page.getByRole("button", { name: "Switch to dark theme" }), 3000);
  await clickOn(page, page.getByRole("button", { name: "Switch to light theme" }), 1500);
}

function run(args: string[]): void {
  const result = spawnSync(ffmpeg, ["-hide_banner", "-loglevel", "error", "-y", ...args], {
    stdio: "inherit",
  });
  if (result.status !== 0) throw new Error(`ffmpeg failed: ${args.join(" ")}`);
}

const mb = (path: string) => statSync(path).size / 1024 / 1024;

function gif(input: string, output: string, opts: { ss?: number; t?: number }): void {
  const maxMb = Number(values["max-gif-mb"]);
  // Fewer frames and colours until it fits.
  for (const [fps, colors, width] of [
    [12, 160, 960],
    [10, 128, 960],
    [10, 96, 900],
    [8, 64, 860],
  ] as const) {
    run([
      ...(opts.ss !== undefined ? ["-ss", String(opts.ss)] : []),
      ...(opts.t !== undefined ? ["-t", String(opts.t)] : []),
      "-i",
      input,
      "-vf",
      `fps=${fps},scale=${width}:-1:flags=lanczos,split[a][b];` +
        `[a]palettegen=max_colors=${colors}:stats_mode=diff[p];` +
        `[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle`,
      "-loop",
      "0",
      output,
    ]);
    if (mb(output) <= maxMb) return;
  }
  throw new Error(`${output} is ${mb(output).toFixed(1)} MB, over ${maxMb} MB`);
}

function mp4(input: string, output: string): void {
  const maxMb = Number(values["max-mp4-mb"]);
  for (const crf of [24, 28, 32]) {
    run([
      "-i",
      input,
      "-c:v",
      "libx264",
      "-preset",
      "slow",
      "-crf",
      String(crf),
      "-pix_fmt",
      "yuv420p",
      "-movflags",
      "+faststart",
      "-an",
      output,
    ]);
    if (mb(output) <= maxMb) return;
  }
  throw new Error(`${output} is ${mb(output).toFixed(1)} MB, over ${maxMb} MB`);
}

async function main(): Promise<void> {
  let server: ReturnType<typeof spawn> | null = null;
  let base = values.url;
  if (!base) {
    server = spawn("bun", ["scripts/serve-demo.ts", "--port", values.port ?? "3201"], {
      stdio: "ignore",
    });
    base = `http://127.0.0.1:${values.port}/Driftline/demo/`;
    for (let i = 0; i < 50; i++) {
      const ok = await fetch(base).then(
        (r) => r.ok,
        () => false,
      );
      if (ok) break;
      await new Promise((r) => setTimeout(r, 200));
    }
  }

  const videoDir = mkdtempSync(join(tmpdir(), "driftline-tour-"));
  const browser = await chromium.launch({ channel: "chromium" });
  const marks: Record<string, number> = {};
  let video: string;
  try {
    const context = await browser.newContext({
      viewport: { width: WIDTH, height: HEIGHT },
      deviceScaleFactor: 1,
      colorScheme: "light",
      recordVideo: { dir: videoDir, size: { width: WIDTH, height: HEIGHT } },
    });
    await context.addInitScript(CURSOR_SCRIPT);
    const page = await context.newPage();
    const t0 = Date.now();
    await tour(page, base, marks, t0);
    await pause(page, 1000);
    const handle = page.video();
    await context.close();
    if (!handle) throw new Error("no video was recorded");
    video = await handle.path();
  } finally {
    await browser.close();
    server?.kill();
  }

  mkdirSync(outDir, { recursive: true });
  const raw = join(videoDir, "tour.webm");
  renameSync(video, raw);
  mp4(raw, join(outDir, "driftline-demo.mp4"));
  const askStart = Math.max(0, (marks.ask_start ?? 0) - 0.5);
  const askLength = Math.min(30, Math.max(20, (marks.ask_end ?? askStart + 25) - askStart + 1));
  gif(raw, join(outDir, "driftline-ask.gif"), { ss: askStart, t: askLength });
  rmSync(videoDir, { recursive: true, force: true });

  for (const name of ["driftline-demo.mp4", "driftline-ask.gif"]) {
    console.log(`${name}: ${mb(join(outDir, name)).toFixed(2)} MB`);
  }
  console.log(`tour marks (s): ${JSON.stringify(marks)}`);
}

await main();
