import { defineConfig } from "@playwright/test";

import base from "./playwright.config";

/**
 * The recorded demo (static export) in a browser, served the way GitHub Pages serves it:
 *
 *   bun run test:e2e:demo
 *
 * The web server builds the export with NEXT_PUBLIC_DRIFTLINE_DEMO=1 and serves `out/`
 * under the base path. No gateway runs: every response comes from the recording.
 */
const PORT = Number(process.env.DEMO_WEB_PORT ?? 3200);
const BASE_PATH = process.env.DRIFTLINE_DEMO_BASE_PATH ?? "/Driftline/demo";

export default defineConfig({
  ...base,
  testDir: "./tests/e2e/demo",
  testMatch: ["*.spec.ts"],
  use: {
    ...base.use,
    baseURL: `http://127.0.0.1:${PORT}${BASE_PATH}/`,
    // The full Chromium build (`PLAYWRIGHT_BROWSERS_PATH=0 bunx playwright install
    // chromium`): the headless shell can hang taking screenshots on macOS.
    channel: process.env.PLAYWRIGHT_CHANNEL ?? "chromium",
  },
  webServer: {
    command: `bun run build && bun scripts/serve-demo.ts --port ${PORT}`,
    env: { NEXT_PUBLIC_DRIFTLINE_DEMO: "1", DRIFTLINE_DEMO_BASE_PATH: BASE_PATH },
    url: `http://127.0.0.1:${PORT}${BASE_PATH}/`,
    reuseExistingServer: false,
    timeout: 300_000,
  },
});
