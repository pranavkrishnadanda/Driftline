/**
 * Incremental server-sent events parser, following the WHATWG "event stream
 * interpretation" rules (https://html.spec.whatwg.org/multipage/server-sent-events.html).
 *
 * Feed it decoded text in chunks of any size; a line, a CRLF pair or an event may be split
 * across chunks. Decoding bytes is the caller's job (use one streaming `TextDecoder`).
 */

export interface SseMessage {
  /** The `event:` field, or `"message"` when the block had none. */
  type: string;
  /** The `data:` lines joined with `\n`. */
  data: string;
  /** The `id:` field set in this block, or `null` when the block set none. */
  id: string | null;
  /** The stream's last event id after this block (it persists across blocks). */
  lastEventId: string;
}

export interface SseParserHandlers {
  onMessage: (message: SseMessage) => void;
  /** A valid `retry:` field, in milliseconds. */
  onRetry?: (ms: number) => void;
  /** A comment line (`: ping`), without the leading colon. */
  onComment?: (text: string) => void;
}

export interface SseParser {
  feed: (chunk: string) => void;
  /** Drop any half-received line or block (call before reading a new connection). */
  reset: () => void;
}

const DIGITS = /^\d+$/;

export function createSseParser(handlers: SseParserHandlers): SseParser {
  let buffer = "";
  let atStreamStart = true;
  // A chunk that ended in CR: if the next one starts with LF, that LF belongs to the CR.
  let skipLeadingLf = false;

  let data = "";
  let hasData = false;
  let eventType = "";
  let blockId: string | null = null;
  let lastEventId = "";

  function dispatch(): void {
    if (blockId !== null) lastEventId = blockId;
    const id = blockId;
    blockId = null;
    if (!hasData) {
      eventType = "";
      return;
    }
    const message: SseMessage = { type: eventType || "message", data, id, lastEventId };
    data = "";
    hasData = false;
    eventType = "";
    handlers.onMessage(message);
  }

  function processLine(line: string): void {
    if (line === "") {
      dispatch();
      return;
    }
    if (line.startsWith(":")) {
      handlers.onComment?.(line.slice(1));
      return;
    }
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    switch (field) {
      case "data":
        data = hasData ? `${data}\n${value}` : value;
        hasData = true;
        break;
      case "event":
        eventType = value;
        break;
      case "id":
        if (!value.includes("\u0000")) blockId = value;
        break;
      case "retry":
        if (DIGITS.test(value)) handlers.onRetry?.(Number(value));
        break;
      default:
        // Unknown fields are ignored.
        break;
    }
  }

  function feed(chunk: string): void {
    if (chunk === "") return;
    let text = chunk;
    if (skipLeadingLf) {
      skipLeadingLf = false;
      if (text.startsWith("\n")) text = text.slice(1);
    }
    if (atStreamStart && text !== "") {
      atStreamStart = false;
      if (text.startsWith("﻿")) text = text.slice(1);
    }
    buffer += text;

    let start = 0;
    for (let i = 0; i < buffer.length; i++) {
      const ch = buffer.charCodeAt(i);
      if (ch !== 10 /* LF */ && ch !== 13 /* CR */) continue;
      processLine(buffer.slice(start, i));
      if (ch === 13) {
        if (i + 1 === buffer.length) skipLeadingLf = true;
        else if (buffer.charCodeAt(i + 1) === 10) i++;
      }
      start = i + 1;
    }
    buffer = buffer.slice(start);
  }

  function reset(): void {
    buffer = "";
    atStreamStart = true;
    skipLeadingLf = false;
    data = "";
    hasData = false;
    eventType = "";
    blockId = null;
  }

  return { feed, reset };
}
