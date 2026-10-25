# Driftline frontend

Next.js (App Router, TypeScript strict, Tailwind v4, shadcn/ui) client for the Driftline gateway.

```bash
npm ci
npm run dev        # http://localhost:3000, talks to NEXT_PUBLIC_DRIFTLINE_API (default http://localhost:8010)
npm run lint && npm run typecheck && npm test && npm run build
npm run test:e2e   # Playwright, against the Compose stack
npm run gen:api    # regenerate src/lib/api/schema.d.ts from the gateway's OpenAPI document
```

UI libraries: Motion (component animation), anime.js (choreographed SVG), Kokonut UI and
Bklit UI (installed as source through the `@kokonutui` and `@bklit` shadcn registries in
`components.json`: `npx shadcn@latest add @bklit/<name>`).
