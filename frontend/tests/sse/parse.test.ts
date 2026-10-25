import { describe, expect, it } from "vitest";

import { createSseParser, type SseMessage } from "@/lib/sse/parse";

interface Collected {
  messages: SseMessage[];
  retries: number[];
  comments: string[];
}

function collect(chunks: string[]): Collected {
  const out: Collected = { messages: [], retries: [], comments: [] };
  const parser = createSseParser({
    onMessage: (m) => out.messages.push(m),
    onRetry: (ms) => out.retries.push(ms),
    onComment: (c) => out.comments.push(c),
  });
  for (const chunk of chunks) parser.feed(chunk);
  return out;
}

/** Every way of cutting `text` into two chunks, plus one character at a time. */
function splits(text: string): string[][] {
  const out: string[][] = [[text], [...text]];
  for (let i = 1; i < text.length; i++) out.push([text.slice(0, i), text.slice(i)]);
  return out;
}

describe("createSseParser", () => {
  it("parses a framed event with id, event and data", () => {
    const { messages } = collect(['id: 7\nevent: token\ndata: {"text":"hi"}\n\n']);
    expect(messages).toEqual([{ id: "7", lastEventId: "7", type: "token", data: '{"text":"hi"}' }]);
  });

  it("yields identical events however the bytes are chunked", () => {
    const stream =
      'id: 1\nevent: step\ndata: {"a":1}\n\n: ping\n\nid: 2\r\nevent: token\r\ndata: x\r\n\r\n';
    const expected = collect([stream]);
    expect(expected.messages).toHaveLength(2);
    for (const chunks of splits(stream)) {
      expect(collect(chunks)).toEqual(expected);
    }
  });

  it("treats CRLF, CR and LF as line endings, including a CRLF split across chunks", () => {
    for (const eol of ["\n", "\r", "\r\n"]) {
      const { messages } = collect([`data: a${eol}data: b${eol}${eol}`]);
      expect(messages.map((m) => m.data)).toEqual(["a\nb"]);
    }
    const split = collect(["data: a\r", "\ndata: b\r", "\n\r", "\n"]);
    expect(split.messages.map((m) => m.data)).toEqual(["a\nb"]);
  });

  it("joins multi-line data with newlines and strips only one leading space", () => {
    const { messages } = collect(["data:no space\ndata:  two spaces\ndata\n\n"]);
    expect(messages[0].data).toBe("no space\n two spaces\n");
  });

  it("defaults the event type to message and keeps the last event id across events", () => {
    const { messages } = collect(["id: 3\ndata: a\n\ndata: b\n\n"]);
    expect(messages).toEqual([
      { id: "3", lastEventId: "3", type: "message", data: "a" },
      { id: null, lastEventId: "3", type: "message", data: "b" },
    ]);
  });

  it("reports comments and heartbeats without dispatching an event", () => {
    const out = collect([": ping\n\n:\n\n: keep-alive\n"]);
    expect(out.messages).toEqual([]);
    expect(out.comments).toEqual([" ping", "", " keep-alive"]);
  });

  it("does not dispatch a block with no data lines, and resets its event type", () => {
    const { messages } = collect(["event: step\nid: 9\n\ndata: x\n\n"]);
    expect(messages).toEqual([{ id: null, lastEventId: "9", type: "message", data: "x" }]);
  });

  it("accepts retry only when it is all ASCII digits", () => {
    expect(collect(["retry: 1500\n\n"]).retries).toEqual([1500]);
    expect(collect(["retry: 15s\nretry: -1\nretry:\n\n"]).retries).toEqual([]);
  });

  it("ignores an id containing NUL and unknown fields", () => {
    const { messages } = collect(["id: 4\n\nid: 5\u0000\nfoo: bar\ndata: z\n\n"]);
    expect(messages).toEqual([{ id: null, lastEventId: "4", type: "message", data: "z" }]);
  });

  it("an empty id resets the last event id", () => {
    const { messages } = collect(["id: 4\ndata: a\n\nid\ndata: b\n\n"]);
    expect(messages.map((m) => m.lastEventId)).toEqual(["4", ""]);
  });

  it("strips a leading byte order mark and never dispatches an unterminated block", () => {
    const { messages } = collect(["\uFEFFdata: a\n\n", "data: partial\n"]);
    expect(messages.map((m) => m.data)).toEqual(["a"]);
  });

  it("reset() drops a half-received block, as a reconnect must", () => {
    const messages: SseMessage[] = [];
    const parser = createSseParser({ onMessage: (m) => messages.push(m) });
    parser.feed("id: 1\nevent: token\ndata: half");
    parser.reset();
    parser.feed("data: whole\n\n");
    expect(messages).toEqual([{ id: null, lastEventId: "", type: "message", data: "whole" }]);
  });
});
