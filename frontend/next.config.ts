import { readFileSync } from "node:fs";
import { join } from "node:path";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
  reactCompiler: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

/**
 * `NEXT_PUBLIC_DRIFTLINE_DEMO=1` builds the recorded demo: a static export for GitHub
 * Pages (under `DRIFTLINE_DEMO_BASE_PATH`) that replays `public/demo/recording.json`
 * instead of calling a gateway. Every demo difference is a module swapped in by
 * `resolveAlias` (the `src/demo/` overrides), so a normal build compiles exactly the
 * same modules as before and none of the demo code.
 */
function demoConfig(base: NextConfig): NextConfig {
  const basePath = process.env.DRIFTLINE_DEMO_BASE_PATH ?? "/Driftline/demo";
  const recording = JSON.parse(
    readFileSync(join(process.cwd(), "public", "demo", "recording.json"), "utf8"),
  ) as { recorded_at: string; tenant: string };
  return {
    ...base,
    output: "export",
    // Partial prerendering needs a server ("PPR cannot be enabled in export mode"); every
    // demo page prerenders whole instead.
    cacheComponents: false,
    partialPrefetching: false,
    basePath,
    // Pages serves `ask/index.html` for `/ask/`; there is no server to map `/ask` to a file.
    trailingSlash: true,
    images: { unoptimized: true },
    env: {
      NEXT_PUBLIC_DRIFTLINE_DEMO: "1",
      NEXT_PUBLIC_DRIFTLINE_TENANTS: recording.tenant,
      DRIFTLINE_DEMO_BASE_PATH: basePath,
      DRIFTLINE_DEMO_RECORDED_AT: recording.recorded_at,
    },
    turbopack: {
      ...base.turbopack,
      resolveAlias: {
        "@/lib/api/client": "./src/demo/api-client.ts",
        "@/lib/sse/useEventStream": "./src/demo/use-event-stream.ts",
        "@/components/kokonutui/ai-prompt": "./src/demo/ai-prompt.tsx",
        "@/components/ask/ask-controls": "./src/demo/ask-controls.tsx",
        "@/components/site-header": "./src/demo/site-header.tsx",
        "@/components/timeline/routes": "./src/demo/timeline-routes.tsx",
      },
    },
  };
}

export default process.env.NEXT_PUBLIC_DRIFTLINE_DEMO === "1" ? demoConfig(nextConfig) : nextConfig;
