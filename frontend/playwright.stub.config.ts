import { defineConfig } from "@playwright/test";

import base from "./playwright.config";

/**
 * The browser checks that need no backend (axe on every view, reduced motion), run against
 * a production build (`next start`) and the stub gateway in tests/support/stub-gateway.ts:
 *
 *   bun run test:e2e:stub
 *
 * NEXT_PUBLIC_DRIFTLINE_API is inlined at build time, so the web server command builds
 * with the stub's URL before starting.
 */
const PORT = Number(process.env.STUB_WEB_PORT ?? 3100);
const GATEWAY_PORT = Number(process.env.STUB_GATEWAY_PORT ?? 8019);
const baseURL = `http://localhost:${PORT}`;

export default defineConfig({
  ...base,
  testMatch: ["a11y.spec.ts", "reduced-motion.spec.ts"],
  globalSetup: "./tests/e2e/stub/global-setup.ts",
  use: { ...base.use, baseURL },
  webServer: {
    command: `bun run build && bun run start -p ${PORT}`,
    env: { NEXT_PUBLIC_DRIFTLINE_API: `http://127.0.0.1:${GATEWAY_PORT}` },
    url: baseURL,
    reuseExistingServer: false,
    timeout: 300_000,
  },
});
