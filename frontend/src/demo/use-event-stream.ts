"use client";

/**
 * Demo build only (next.config.ts aliases `@/lib/sse/useEventStream` here): the same hook
 * and state, fed by replaying the recording for the URL instead of a connection.
 */
import { useEffect, useState } from "react";

import { runDemoStream, type StreamSink, type Terminal } from "../lib/demo/stream";
import type { AskEvent } from "../lib/sse/events";
import type {
  EventStreamState,
  EventStreamStatus,
  StreamEvent,
  UseEventStreamOptions,
} from "../lib/sse/useEventStream";

export type {
  EventStreamState,
  EventStreamStatus,
  StreamEvent,
  UseEventStreamOptions,
} from "../lib/sse/useEventStream";

const IDLE: EventStreamState<never> = {
  status: "idle",
  text: "",
  events: [],
  final: null,
  error: null,
  lastEventId: null,
};

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

/** `useEventStream`, replaying the recorded stream for `url` (options do not apply). */
export function useEventStream<E extends StreamEvent = AskEvent>(
  url: string | null,
  _options: UseEventStreamOptions = {},
): EventStreamState<E> {
  const [state, setState] = useState<EventStreamState<E>>(IDLE);

  useEffect(() => {
    if (url === null) return;
    const controller = new AbortController();
    let pendingText: string[] = [];
    let pendingEvents: E[] = [];
    let pendingId: string | null = null;
    let pendingStatus: EventStreamStatus | null = "connecting";
    let pendingTerminal: Terminal | null = null;
    let fresh = true;
    let cancelFrame: (() => void) | null = null;

    // Commit what arrived since the last frame, as the network hook does.
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
        const base: EventStreamState<E> = reset ? { ...IDLE, status: "connecting" } : previous;
        let final = base.final;
        for (const event of events) if (event.type === "final") final = event as never;
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
        if (event.type === "token") pendingText.push((event as unknown as { text: string }).text);
        else pendingEvents.push(event);
        if (id !== null) pendingId = id;
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
    void runDemoStream(url, sink, controller.signal);
    return () => {
      controller.abort();
      cancelFrame?.();
    };
  }, [url]);

  return url === null ? IDLE : state;
}
