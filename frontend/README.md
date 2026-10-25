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
