/**
 * A real local HTTP server for API client tests: it answers each `METHOD /path`
 * with a fixed status, JSON (or raw) body and headers, and records every request.
 * No fetch is faked; the client under test talks to it over a real socket.
 */
import { createServer, type IncomingHttpHeaders } from "node:http";
import type { AddressInfo } from "node:net";

export interface FixtureResponse {
  status: number;
  /** Serialised as JSON unless `raw` is set. */
  json?: unknown;
  /** Sent verbatim (use it for non-JSON bodies). */
  raw?: string;
  headers?: Record<string, string>;
  /** Wait this long before answering (to observe in-flight states). */
  delayMs?: number;
}

export interface RecordedRequest {
  method: string;
  /** Path plus query string, exactly as received. */
  url: string;
  headers: IncomingHttpHeaders;
  body: string;
}

export interface ApiServer {
  url: string;
  requests: RecordedRequest[];
  close(): Promise<void>;
}

/**
 * Routes are keyed `"GET /v1/stats"`; the query string is ignored for matching. A list
 * answers successive requests in turn and then keeps repeating its last response.
 */
export async function startApiServer(
  routes: Record<string, FixtureResponse | FixtureResponse[]>,
): Promise<ApiServer> {
  const requests: RecordedRequest[] = [];
  const served = new Map<string, number>();
  const server = createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on("data", (chunk: Buffer) => chunks.push(chunk));
    req.on("end", () => {
      const url = req.url ?? "/";
      requests.push({
        method: req.method ?? "GET",
        url,
        headers: req.headers,
        body: Buffer.concat(chunks).toString("utf8"),
      });
      const key = `${req.method} ${url.split("?")[0]}`;
      const route = routes[key];
      const count = served.get(key) ?? 0;
      served.set(key, count + 1);
      const fixture = Array.isArray(route) ? route[Math.min(count, route.length - 1)] : route;
      if (!fixture) {
        res.writeHead(404, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ detail: "Not Found" }));
        return;
      }
      const raw = fixture.raw ?? JSON.stringify(fixture.json ?? null);
      const answer = (): void => {
        if (res.destroyed) return;
        res.writeHead(fixture.status, {
          "Content-Type": fixture.raw === undefined ? "application/json" : "text/plain",
          ...fixture.headers,
        });
        res.end(raw);
      };
      if (fixture.delayMs) setTimeout(answer, fixture.delayMs);
      else answer();
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${port}`,
    requests,
    close: () =>
      new Promise<void>((resolve, reject) => {
        server.closeAllConnections();
        server.close((err) => (err ? reject(err) : resolve()));
      }),
  };
}

/** A URL on a port that was just released, so connecting to it is refused. */
export async function closedPortUrl(): Promise<string> {
  const server = createServer();
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  await new Promise<void>((resolve) => server.close(() => resolve()));
  return `http://127.0.0.1:${port}`;
}
