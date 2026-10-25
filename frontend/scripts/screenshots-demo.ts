#!/usr/bin/env bun
/**
 * Regenerates the README screenshots (`docs/screenshots/*.webp`) from the recorded demo,
 * so they show the real recorded run rather than test fixtures.
 *
 *   bun run build:demo
 *   PLAYWRIGHT_BROWSERS_PATH=0 bun scripts/screenshots-demo.ts
 *
 * WebP is encoded by Chromium itself (canvas `toBlob`), lowering the quality until each
 * file is under `--max-kb` (300).
 */
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { parseArgs } from "node:util";

import { chromium, type Browser, type Page } from "@playwright/test";

import type { DemoRecording } from "../src/lib/demo/recording";

const { values } = parseArgs({
  options: {
    url: { type: "string" },
    port: { type: "string", default: "3202" },
    out: { type: "string", default: "../docs/screenshots" },
    "max-kb": { type: "string", default: "300" },
  },
});

const outDir = resolve(values.out ?? "../docs/screenshots");
const maxBytes = Number(values["max-kb"]) * 1024;
const recording = JSON.parse(
  readFileSync(join(import.meta.dirname, "..", "public", "demo", "recording.json"), "utf8"),
) as DemoRecording;

interface Shot {
  file: string;
  path: string;
  viewport: { width: number; height: number };
  dark?: boolean;
  fullPage?: boolean;
  prepare?: (page: Page) => Promise<void>;
}

/** The question asked at two dates, earliest date first (the drift "trap"). */
function trapIndex(): number {
  const seen = new Map<string, number>();
  for (const [i, ask] of recording.asks.entries()) {
    const first = seen.get(ask.request.question);
    if (first !== undefined) {
      const a = recording.asks[first].request.as_of ?? "9999";
      const b = ask.request.as_of ?? "9999";
      return a <= b ? first : i;
    }
    seen.set(ask.request.question, i);
  }
  return Math.max(
    0,
    recording.asks.findIndex((a) => a.job.answer?.status === "answered"),
  );
}

async function askTrap(page: Page): Promise<void> {
  await page.getByTestId("demo-suggestion").nth(trapIndex()).click();
  await page
    .getByRole("status")
    .filter({ hasText: /Answer ready\./ })
    .waitFor({ state: "attached", timeout: 60_000 });
  await page.waitForTimeout(1200);
}

const drifted = recording.drift_events.find((e) => e.document_id)?.document_id;
const firstDoc = drifted ?? Object.keys(recording.timelines)[0];
const DESKTOP = { width: 1440, height: 900 };

const SHOTS: Shot[] = [
  {
    file: "landing.webp",
    path: "",
    viewport: DESKTOP,
    fullPage: true,
    prepare: (p) => p.waitForTimeout(4500),
  },
  { file: "ask-answered.webp", path: "ask/", viewport: DESKTOP, prepare: askTrap },
  { file: "ask-answered-dark.webp", path: "ask/", viewport: DESKTOP, dark: true, prepare: askTrap },
  {
    file: "ask-answered-mobile.webp",
    path: "ask/",
    viewport: { width: 390, height: 948 },
    prepare: askTrap,
  },
  {
    file: "document-timeline.webp",
    path: `documents/${firstDoc}/`,
    viewport: DESKTOP,
    fullPage: true,
    prepare: (p) => p.waitForTimeout(3000),
  },
  {
    file: "drift-inbox.webp",
    path: "drift/",
    viewport: DESKTOP,
    prepare: (p) => p.waitForTimeout(2500),
  },
  {
    file: "review-queue.webp",
    path: "review/",
    viewport: DESKTOP,
    fullPage: true,
    prepare: (p) => p.waitForTimeout(2000),
  },
  {
    file: "stats.webp",
    path: "stats/",
    viewport: DESKTOP,
    fullPage: true,
    prepare: (p) => p.waitForTimeout(4500),
  },
];

/** PNG bytes as WebP, encoded by the browser, at the highest quality under the cap. */
async function toWebp(browser: Browser, png: Buffer): Promise<Buffer> {
  const page = await browser.newPage();
  try {
    for (const quality of [0.86, 0.8, 0.72, 0.64, 0.56, 0.48, 0.4]) {
      const b64 = await page.evaluate(
        async ({ data, q }) => {
          const img = new Image();
          img.src = `data:image/png;base64,${data}`;
          await img.decode();
          const canvas = document.createElement("canvas");
          canvas.width = img.naturalWidth;
          canvas.height = img.naturalHeight;
          canvas.getContext("2d")!.drawImage(img, 0, 0);
          const blob = await new Promise<Blob>((ok, fail) =>
            canvas.toBlob((b) => (b ? ok(b) : fail(new Error("no blob"))), "image/webp", q),
          );
          const bytes = new Uint8Array(await blob.arrayBuffer());
          let s = "";
          for (let i = 0; i < bytes.length; i += 0x8000) {
            s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
          }
          return btoa(s);
        },
        { data: png.toString("base64"), q: quality },
      );
      const webp = Buffer.from(b64, "base64");
      if (webp.length <= maxBytes) return webp;
    }
    throw new Error(`could not get a screenshot under ${maxBytes} bytes`);
  } finally {
    await page.close();
  }
}

async function main(): Promise<void> {
  let server: ReturnType<typeof spawn> | null = null;
  let base = values.url;
  if (!base) {
    server = spawn("bun", ["scripts/serve-demo.ts", "--port", values.port ?? "3202"], {
      stdio: "ignore",
    });
    base = `http://127.0.0.1:${values.port}/Driftline/demo/`;
    for (let i = 0; i < 50; i++) {
      if (
        await fetch(base).then(
          (r) => r.ok,
          () => false,
        )
      )
        break;
      await new Promise((r) => setTimeout(r, 200));
    }
  }
  const browser = await chromium.launch({ channel: "chromium" });
  mkdirSync(outDir, { recursive: true });
  try {
    for (const shot of SHOTS) {
      const context = await browser.newContext({
        viewport: shot.viewport,
        deviceScaleFactor: 1,
        colorScheme: shot.dark ? "dark" : "light",
      });
      const page = await context.newPage();
      await page.goto(new URL(shot.path, base).toString());
      await shot.prepare?.(page);
      await page.mouse.move(0, 0);
      const png = await page.screenshot({ fullPage: shot.fullPage ?? false });
      await context.close();
      const file = join(outDir, shot.file);
      writeFileSync(file, await toWebp(browser, png));
      console.log(`${shot.file}: ${(statSync(file).size / 1024).toFixed(0)} KB`);
    }
  } finally {
    await browser.close();
    server?.kill();
  }
}

await main();
