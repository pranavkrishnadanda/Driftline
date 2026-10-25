"use client";

import { useEffect, useRef, useState } from "react";

import type { AskEvent, ErrorEvent, FinalEvent } from "./events";

/** Any event a Driftline SSE stream delivers: a JSON object with a `type`. */
export interface StreamEvent {
  type: string;
}
import { createSseParser, type SseMessage } from "./parse";

/**
 * - `connecting` / `reconnecting`: a request is in flight or a reconnect is scheduled.
 * - `open`: the server is streaming.
 * - `done`: a `final` event arrived (terminal).
 * - `expired`: the server no longer stores the missed events (`events_expired`, terminal);
 *   fetch the job's outcome from its status URL instead.
 * - `failed`: a non-retryable `error` event, HTTP status, bad frame, or too many retries.
 */
export type EventStreamStatus =
  | "idle"
  | "connecting"
  | "open"
  | "reconnecting"
  | "done"
  | "expired"
  | "failed";

export interface EventStreamState<E extends StreamEvent = AskEvent> {
  status: EventStreamStatus;
  /** Every `token` event's text, in order. */
  text: string;
  /** Every other event (step, claim, final, error, alert), in order. */
  events: E[];
  final: FinalEvent | null;
  /** The terminal error, from the server or made by the client (`http_404`, ...). */
  error: ErrorEvent | null;
  /** The id of the last event received; sent as `Last-Event-ID` on reconnect. */
  lastEventId: string | null;
}

export interface UseEventStreamOptions {
  /** Base reconnect delay until the server sends `retry:` (ms). */
  initialRetryMs?: number;
  /** Upper bound for the exponential backoff (ms); a server `retry:` is never cut short. */
  maxRetryMs?: number;
  /** Reconnect attempts in a row without receiving an event before giving up. */
  maxAttempts?: number;
  /** Resume an earlier stream from this event id. */
  lastEventId?: string | null;
}

const IDLE: EventStreamState<never> = {
  status: "idle",
  text: "",
  events: [],
  final: null,
  error: null,
  lastEventId: null,
};

const RETRYABLE_STATUS = new Set([408, 425, 429, 500, 502, 503, 504]);

function isError(event: StreamEvent): event is ErrorEvent {
  return event.type === "error";
}

function isFinal(event: StreamEvent): event is FinalEvent {
  return event.type === "final";
}

function isToken(event: StreamEvent): event is StreamEvent & { type: "token"; text: string } {
  return event.type === "token";
}

function clientError(code: string, message: string): ErrorEvent {
  return { type: "error", code, message, retryable: false };
}

/** `Retry-After` as milliseconds (delta-seconds or an HTTP date), or 0. */
function retryAfterMs(header: string | null): number {
  if (!header) return 0;
  const seconds = Number(header);
  if (Number.isFinite(seconds)) return Math.max(0, seconds * 1000);
  const date = Date.parse(header);
  return Number.isNaN(date) ? 0 : Math.max(0, date - Date.now());
}

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(done, ms);
    function done(): void {
      clearTimeout(timer);
      signal.removeEventListener("abort", done);
      resolve();
    }
    signal.addEventListener("abort", done, { once: true });
  });
}

type Terminal = { status: "done" | "expired" | "failed"; error: ErrorEvent | null };

interface StreamSink<E extends StreamEvent> {
  /** A token or other event, in arrival order. Duplicates have already been dropped. */
  event: (event: E, id: string | null) => void;
  status: (status: "connecting" | "open" | "reconnecting") => void;
  terminal: (terminal: Terminal) => void;
}

/**
 * The connection loop: fetch, read, parse, resume with `Last-Event-ID` and backoff until a
 * terminal event or `signal` aborts. `fetch` (not `EventSource`) so the resume header can
 * be sent.
 */
async function runEventStream<E extends StreamEvent>(
  url: string,
  options: Required<Omit<UseEventStreamOptions, "lastEventId">> & { lastEventId: string | null },
  sink: StreamSink<E>,
  signal: AbortSignal,
): Promise<void> {
  let lastEventId = options.lastEventId;
  let lastSeq = lastEventId !== null && /^\d+$/.test(lastEventId) ? Number(lastEventId) : 0;
  let retryMs = options.initialRetryMs;
  let attempt = 0;
  let terminal: Terminal | null = null;
  let receivedThisConnection = false;

  const parser = createSseParser({
    onRetry: (ms) => {
      retryMs = ms;
    },
    onMessage: (message: SseMessage) => {
      if (terminal) return;
      if (message.id !== null) {
        const seq = /^\d+$/.test(message.id) ? Number(message.id) : null;
        // Ids increase strictly per job: anything at or below the last one is a replay.
        if (seq !== null && seq <= lastSeq) return;
        if (seq !== null) lastSeq = seq;
        lastEventId = message.id;
      }
      let event: E;
      try {
        event = JSON.parse(message.data) as E;
      } catch {
        terminal = {
          status: "failed",
          error: clientError("bad_event", `unparseable ${message.type} event data`),
        };
        return;
      }
      receivedThisConnection = true;
      sink.event(event, lastEventId);
      if (event.type === "final") {
        terminal = { status: "done", error: null };
      } else if (isError(event) && !event.retryable) {
        terminal = {
          status: event.code === "events_expired" ? "expired" : "failed",
          error: event,
        };
      }
    },
  });

  while (!signal.aborted) {
    sink.status(attempt === 0 && lastSeq === 0 ? "connecting" : "reconnecting");
    let minDelay = 0;
    receivedThisConnection = false;
    parser.reset();
    try {
      const headers: Record<string, string> = { Accept: "text/event-stream" };
      if (lastEventId) headers["Last-Event-ID"] = lastEventId;
      const response = await fetch(url, { headers, signal, cache: "no-store" });

      if (!response.ok || !response.body) {
        await response.body?.cancel();
        if (!RETRYABLE_STATUS.has(response.status)) {
          sink.terminal({
            status: "failed",
            error: clientError(`http_${response.status}`, `the event stream returned ${response.status}`),
          });
          return;
        }
        minDelay = retryAfterMs(response.headers.get("Retry-After"));
      } else {
        sink.status("open");
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        try {
          while (!terminal) {
            const { done, value } = await reader.read();
            if (done) break;
            parser.feed(decoder.decode(value, { stream: true }));
          }
        } finally {
          if (terminal) await reader.cancel().catch(() => undefined);
        }
        if (terminal) {
          sink.terminal(terminal);
          return;
        }
      }
    } catch {
      // Aborted (unmount or new url): stop quietly. Otherwise the network failed or the
      // connection dropped mid-read: reconnect below.
      if (signal.aborted) return;
      if (terminal) {
        sink.terminal(terminal);
        return;
      }
    }

    attempt = receivedThisConnection ? 1 : attempt + 1;
    if (attempt > options.maxAttempts) {
      sink.terminal({
        status: "failed",
        error: clientError("reconnect_exhausted", `gave up after ${options.maxAttempts} attempts`),
      });
      return;
    }
    sink.status("reconnecting");
    const backoff = Math.max(retryMs, Math.min(options.maxRetryMs, retryMs * 2 ** (attempt - 1)));
    await wait(Math.max(backoff, minDelay), signal);
  }
}

const schedule: (cb: () => void) => () => void =
  typeof requestAnimationFrame === "function"
    ? (cb) => {
        const handle = requestAnimationFrame(cb);
        return () => cancelAnimationFrame(handle);
      }
    : (cb) => {
        const handle = setTimeout(cb, 16);
        return () => clearTimeout(handle);
      };

/**
 * Subscribe to a Driftline SSE event stream: an ask's (the default event type) or any
 * other, such as the open-ended drift-alert stream (`useEventStream<AlertStreamEvent>`).
 * Pass `null` to stay idle. A `final` event ends a stream, as does a non-retryable
 * `error`; a stream without them runs until unmount or a new `url`.
 *
 * Events are buffered and committed to React state at most once per animation frame, so a
 * burst of thousands of `token` events costs a handful of renders and none is dropped.
 * Changing `url` or unmounting aborts the request.
 */
export function useEventStream<E extends StreamEvent = AskEvent>(
  url: string | null,
  options: UseEventStreamOptions = {},
): EventStreamState<E> {
  const [state, setState] = useState<EventStreamState<E>>(IDLE);
  const { initialRetryMs = 1000, maxRetryMs = 30_000, maxAttempts = 8, lastEventId = null } = options;
  // Options are read when a stream starts; only a new `url` restarts it.
  const optionsRef = useRef({ initialRetryMs, maxRetryMs, maxAttempts, lastEventId });
  useEffect(() => {
    optionsRef.current = { initialRetryMs, maxRetryMs, maxAttempts, lastEventId };
  });

  useEffect(() => {
    if (url === null) return;
    const controller = new AbortController();
    // The first commit of a new stream replaces whatever the previous url left behind.
    const resetState = (): EventStreamState<E> => ({ ...IDLE, status: "connecting" });
    let pendingText: string[] = [];
    let pendingEvents: E[] = [];
    let pendingId: string | null = null;
    let pendingStatus: EventStreamStatus | null = "connecting";
    let pendingTerminal: Terminal | null = null;
    let fresh = true;
    let cancelFrame: (() => void) | null = null;

    const flush = (): void => {
      cancelFrame = null;
      const text = pendingText.join("");
      const events = pendingEvents;
      const id = pendingId;
      const status = pendingStatus;
      const terminal = pendingTerminal;
      const reset = fresh;
      pendingText = [];
      pendingEvents = [];
      pendingStatus = null;
      pendingTerminal = null;
      fresh = false;
      setState((previous) => {
        const base = reset ? resetState() : previous;
        let final = base.final;
        for (const event of events) if (isFinal(event)) final = event;
        return {
          status: terminal?.status ?? status ?? base.status,
          text: text ? base.text + text : base.text,
          events: events.length ? [...base.events, ...events] : base.events,
          final,
          error: terminal ? terminal.error : base.error,
          lastEventId: id ?? base.lastEventId,
        };
      });
    };
    const requestFlush = (): void => {
      if (!cancelFrame) cancelFrame = schedule(flush);
    };

    const sink: StreamSink<E> = {
      event: (event, id) => {
        if (isToken(event)) pendingText.push(event.text);
        else pendingEvents.push(event);
        pendingId = id;
        requestFlush();
      },
      status: (status) => {
        pendingStatus = status;
        requestFlush();
      },
      terminal: (terminal) => {
        pendingTerminal = terminal;
        cancelFrame?.();
        flush();
      },
    };

    requestFlush();
    void runEventStream(url, optionsRef.current, sink, controller.signal);

    return () => {
      controller.abort();
      cancelFrame?.();
    };
  }, [url]);

  return url === null ? IDLE : state;
}
