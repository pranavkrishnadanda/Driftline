# Driftline frontend

Next.js (App Router, TypeScript strict, Tailwind v4, shadcn/ui) client for the Driftline gateway.
[Bun](https://bun.sh) is the package manager and script runner.

```bash
bun install --frozen-lockfile
bun run dev        # http://localhost:3000, talks to NEXT_PUBLIC_DRIFTLINE_API (default http://localhost:8010)
bun run lint && bun run format:check && bun run typecheck && bun run test && bun run build
bun run test:e2e   # Playwright, against the Compose stack
bun run gen:api    # regenerate src/lib/api/schema.d.ts from the gateway's OpenAPI document
```

UI libraries: Motion (component animation), anime.js (choreographed SVG), Kokonut UI and
Bklit UI (installed as source through the `@kokonutui` and `@bklit` shadcn registries in
`components.json`: `bunx shadcn@latest add @bklit/<name>`).

## Recorded demo (GitHub Pages)

`bun run build:demo` (`NEXT_PUBLIC_DRIFTLINE_DEMO=1`) builds a static export under
`/Driftline/demo` that replays `public/demo/recording.json`, a capture of a real run (real
documents, real Claude answers), instead of calling a gateway. Every page says it is a
recording. The demo modules in `src/demo/` replace the API client, `useEventStream`, the
Ask prompt, the as-of picker, the header and the Timeline routes through Turbopack
`resolveAlias`, so a normal build compiles none of them.

```bash
bun run build:demo && bun scripts/serve-demo.ts --port 3200   # http://127.0.0.1:3200/Driftline/demo/
bun run test:e2e:demo                                          # Playwright against the export
PLAYWRIGHT_BROWSERS_PATH=0 bun scripts/record-demo.ts          # docs/media tour MP4 + GIFs
PLAYWRIGHT_BROWSERS_PATH=0 bun scripts/screenshots-demo.ts     # docs/screenshots
```

`scripts/capture-demo.ts` records the bundle from a running stack; `deploy/demo/` holds the
isolated capture stack, the staged ingest and the question plan.
