#!/usr/bin/env bun
/**
 * Serves the recorded demo's static export (`out/`) the way GitHub Pages does: under its
 * base path, `dir/` as `dir/index.html`, `dir` redirected to `dir/`, and `404.html` for
 * anything else.
 *
 *   NEXT_PUBLIC_DRIFTLINE_DEMO=1 bun run build && bun scripts/serve-demo.ts --port 3200
 */
import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, resolve, sep } from "node:path";
import { parseArgs } from "node:util";

const { values } = parseArgs({
  options: {
    port: { type: "string", default: "3200" },
    dir: { type: "string", default: "out" },
    "base-path": {
      type: "string",
      default: process.env.DRIFTLINE_DEMO_BASE_PATH ?? "/Driftline/demo",
    },
  },
});

const root = resolve(values.dir ?? "out");
const basePath = (values["base-path"] ?? "").replace(/\/+$/, "");

const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".txt": "text/plain; charset=utf-8",
  ".ico": "image/x-icon",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".webp": "image/webp",
  ".woff2": "font/woff2",
};

function isFile(path: string): boolean {
  return existsSync(path) && statSync(path).isFile();
}

const server = createServer((req, res) => {
  const pathname = decodeURIComponent(new URL(req.url ?? "/", "http://demo").pathname);
  if (pathname === "/" || pathname === basePath) {
    res.writeHead(302, { Location: `${basePath}/` }).end();
    return;
  }
  const rel = pathname.startsWith(`${basePath}/`) ? pathname.slice(basePath.length) : null;
  let path = rel === null ? null : resolve(join(root, rel));
  if (path && path !== root && !path.startsWith(root + sep)) path = null;

  if (path && !rel?.endsWith("/") && !isFile(path) && isFile(join(path, "index.html"))) {
    res.writeHead(301, { Location: `${pathname}/` }).end();
    return;
  }
  if (path && !isFile(path)) path = join(path, "index.html");
  let status = 200;
  if (!path || !isFile(path)) {
    status = 404;
    path = join(root, "404.html");
  }
  if (!isFile(path)) {
    res.writeHead(404).end("Not Found");
    return;
  }
  res.writeHead(status, { "Content-Type": TYPES[extname(path)] ?? "application/octet-stream" });
  createReadStream(path).pipe(res);
});

server.listen(Number(values.port), "127.0.0.1", () => {
  console.log(`demo at http://127.0.0.1:${values.port}${basePath}/`);
});
