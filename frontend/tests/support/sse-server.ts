/**
 * A real local SSE server for hook tests: a tiny Node `http` server that replays a
 * contract fixture the way the gateway does (`id:`/`event:`/`data:` frames, `: ping`
 * heartbeats, `Last-Event-ID` resume, end of stream after a terminal event).
 *
 * Each connection can be told to drop mid-stream, so tests exercise real reconnects.
 */
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";

export interface FixtureEvent {
  id: number | null;
  event: string;
  data: unknown;
}

export interface ConnectionPlan {
  /** Stop after sending this many events on this connection. */
  dropAfter?: number;
  /** How to stop: `"destroy"` resets the socket, `"end"` closes the response cleanly. */
  drop?: "destroy" | "end";
  /** Keep the response open after the last event instead of ending it. */
  hold?: boolean;
  /** Answer with this HTTP status (and no stream) instead. */
  status?: number;
  /** `Retry-After` header for a `status` answer. */
  retryAfter?: string;
  /** On resume, re-send this many events the client already has (it must drop them). */
  overlap?: number;
  /** Replay these events on this connection instead of the server's `events`. */
  events?: FixtureEvent[];
}

export interface SseServerOptions {
  events: FixtureEvent[];
  /** Sent as `retry:` at the start of every connection. */
  retryMs?: number;
  /** Per-connection behaviour, by connection index; later connections replay normally. */
  connections?: ConnectionPlan[];
  /** Write frames this many characters at a time, so frames straddle network chunks. */
  chunkSize?: number;
}

export interface RecordedConnection {
  /** Path plus query string, exactly as requested. */
  url: string;
  lastEventId: string | null;
  at: number;
  /** Ids of the events written on this connection. */
  sentIds: (number | null)[];
  /** Resolves when the client side closes the connection (abort or disconnect). */
  closed: Promise<void>;
  closedByClient: boolean;
}

export interface SseServer {
  url: string;
  connections: RecordedConnection[];
  close: () => Promise<void>;
}

export function frame(event: FixtureEvent): string {
  const head = event.id === null ? "" : `id: ${event.id}\n`;
  return `${head}event: ${event.event}\ndata: ${JSON.stringify(event.data)}\n\n`;
}

function writeChunked(res: ServerResponse, text: string, chunkSize: number | undefined): void {
  if (!chunkSize) {
    res.write(text);
    return;
  }
  for (let i = 0; i < text.length; i += chunkSize) res.write(text.slice(i, i + chunkSize));
}

const TERMINAL = (e: FixtureEvent): boolean => {
  if (e.event === "final") return true;
  const data = e.data as { retryable?: boolean };
  return e.event === "error" && data.retryable === false;
};

export async function startSseServer(options: SseServerOptions): Promise<SseServer> {
  const connections: RecordedConnection[] = [];

  const handler = (req: IncomingMessage, res: ServerResponse): void => {
    const index = connections.length;
    const plan = options.connections?.[index] ?? {};
    const header = req.headers["last-event-id"];
    const lastEventId = typeof header === "string" ? header : null;

    let resolveClosed!: () => void;
    const record: RecordedConnection = {
      url: req.url ?? "/",
      lastEventId,
      at: Date.now(),
      sentIds: [],
      closed: new Promise<void>((r) => (resolveClosed = r)),
      closedByClient: false,
    };
    connections.push(record);
    res.on("close", () => {
      if (!res.writableEnded) record.closedByClient = true;
      resolveClosed();
    });

    if (plan.status) {
      res.writeHead(plan.status, plan.retryAfter ? { "Retry-After": plan.retryAfter } : {});
      res.end();
      return;
    }

    res.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    });
    let out = ": ping\n\n";
    if (options.retryMs !== undefined) out += `retry: ${options.retryMs}\n\n`;

    const after = lastEventId ? Number(lastEventId) : 0;
    const from = Math.max(0, after - (lastEventId ? (plan.overlap ?? 0) : 0));
    const pending = (plan.events ?? options.events).filter((e) => e.id === null || e.id > from);

    let sent = 0;
    for (const event of pending) {
      if (plan.dropAfter !== undefined && sent >= plan.dropAfter) {
        writeChunked(res, out, options.chunkSize);
        // A half-written frame proves the client never acts on an unterminated event.
        const partial = `id: ${String(event.id)}\nevent: ${event.event}\ndata: {"trunc`;
        if (plan.drop === "end") {
          res.end(partial);
        } else {
          // Let the bytes reach the client, then reset the socket like a crashed proxy.
          res.write(partial, () => setTimeout(() => res.socket?.destroy(), 20));
        }
        return;
      }
      out += frame(event);
      record.sentIds.push(event.id);
      sent++;
      if (TERMINAL(event)) break;
    }
    writeChunked(res, out, options.chunkSize);
    if (!plan.hold) res.end();
  };

  const server = createServer(handler);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;

  return {
    url: `http://127.0.0.1:${port}/v1/ask/test-job/events`,
    connections,
    close: () =>
      new Promise<void>((resolve, reject) => {
        server.closeAllConnections();
        server.close((err) => (err ? reject(err) : resolve()));
      }),
  };
}

/** `count` token events with ids starting at `firstId`, then a `final` event. */
export function tokenBurst(count: number, firstId = 1): { events: FixtureEvent[]; text: string } {
  const events: FixtureEvent[] = [];
  let text = "";
  for (let i = 0; i < count; i++) {
    const piece = `t${i} `;
    text += piece;
    events.push({ id: firstId + i, event: "token", data: { type: "token", text: piece } });
  }
  events.push({
    id: firstId + count,
    event: "final",
    data: {
      type: "final",
      answer: { status: "answered", answer: text, as_of: "2024-06-01T00:00:00Z", confidence: 1 },
    },
  });
  return { events, text };
}
