import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/client";
import {
  citationNumbers,
  classifyAskFailure,
  describeCitation,
  formatCountdown,
  formatDate,
  parseTenants,
  resolveEventsUrl,
  secondsLeft,
  stepLabel,
  toAsOfParam,
} from "@/lib/ask/format";
import type { Citation, FinalEvent } from "@/lib/sse/events";

import answered from "../fixtures/sse/ask-answered.json";

const FINAL = answered.events.find((e) => e.event === "final")!.data as FinalEvent;
const CITATION: Citation = FINAL.answer.citations![0];

/** A citation stored before answers carried version metadata. */
const LEGACY: Citation = {
  chunk_id: CITATION.chunk_id,
  version_id: CITATION.version_id,
  quote: CITATION.quote,
};

describe("formatDate", () => {
  it("formats an ISO timestamp as a UTC calendar date", () => {
    expect(formatDate("2024-06-01T00:00:00Z")).toBe("1 Jun 2024");
    expect(formatDate("2024-06-01T23:30:00-05:00")).toBe("2 Jun 2024");
  });

  it("returns the input unchanged when it is not a date", () => {
    expect(formatDate("not a date")).toBe("not a date");
  });
});

describe("toAsOfParam", () => {
  it("sends the picked local calendar day as midnight UTC", () => {
    expect(toAsOfParam(new Date(2024, 5, 1, 18, 45))).toBe("2024-06-01T00:00:00Z");
    expect(toAsOfParam(new Date(2023, 0, 9))).toBe("2023-01-09T00:00:00Z");
  });

  it("omits as_of when no date is picked (the backend defaults to today)", () => {
    expect(toAsOfParam(null)).toBeNull();
  });
});

describe("describeCitation", () => {
  it("shows the cited version's title, number, section and valid-from from the citation", () => {
    expect(describeCitation(CITATION)).toEqual({
      quote: "Check ALT monthly during therapy.",
      title: "Lipitor (atorvastatin calcium) label",
      section: "Warnings and Precautions > Liver Dysfunction",
      version: "v2",
      validity: "Valid from 15 Apr 2024",
    });
  });

  it("shows the whole window of a superseded version", () => {
    const superseded = { ...CITATION, valid_to: "2025-01-01T00:00:00Z" };
    expect(describeCitation(superseded).validity).toBe("Valid 15 Apr 2024 to 1 Jan 2025");
  });

  it("falls back to the version id for a citation stored without metadata", () => {
    expect(describeCitation(LEGACY)).toEqual({
      quote: "Check ALT monthly during therapy.",
      title: null,
      section: null,
      version: "version 00000000…00a2",
      validity: null,
    });
  });
});

describe("citationNumbers", () => {
  it("numbers each distinct chunk once, in order of first appearance", () => {
    const other: Citation = { ...CITATION, chunk_id: "c-other", quote: "Other." };
    const numbers = citationNumbers([
      { citations: [CITATION, other] },
      { citations: [other, CITATION] },
    ]);
    expect(numbers.get(CITATION.chunk_id)).toBe(1);
    expect(numbers.get("c-other")).toBe(2);
    expect(numbers.size).toBe(2);
  });
});

describe("countdown", () => {
  it("rounds the remaining time up to whole seconds and never goes negative", () => {
    expect(secondsLeft(10_000, 0)).toBe(10);
    expect(secondsLeft(10_000, 9_001)).toBe(1);
    expect(secondsLeft(10_000, 10_000)).toBe(0);
    expect(secondsLeft(10_000, 12_000)).toBe(0);
  });

  it("formats seconds as m:ss", () => {
    expect(formatCountdown(0)).toBe("0:00");
    expect(formatCountdown(7)).toBe("0:07");
    expect(formatCountdown(65)).toBe("1:05");
    expect(formatCountdown(600)).toBe("10:00");
  });
});

describe("classifyAskFailure", () => {
  it("maps 429 to a rate limit that carries Retry-After", () => {
    expect(classifyAskFailure(new ApiError(429, { retryAfter: 7, code: "backpressure" }))).toEqual({
      kind: "rate_limited",
      retryAfter: 7,
    });
  });

  it("uses a default wait when a 429 has no usable Retry-After", () => {
    expect(classifyAskFailure(new ApiError(429, {}))).toEqual({
      kind: "rate_limited",
      retryAfter: 5,
    });
  });

  it("treats an unreachable or unavailable gateway as backend down", () => {
    expect(classifyAskFailure(new ApiError(0, { code: "network_error" }))).toEqual({
      kind: "backend_down",
      message: "The Driftline API can't be reached.",
    });
    expect(classifyAskFailure(new ApiError(503, {}))).toEqual({
      kind: "backend_down",
      message: "The Driftline API is unavailable (503).",
    });
  });

  it("explains a rejected or mismatched API key", () => {
    expect(classifyAskFailure(new ApiError(401, { code: "unauthorized" }))).toEqual({
      kind: "error",
      message: "The API key is missing or invalid.",
    });
    expect(classifyAskFailure(new ApiError(403, { code: "tenant_mismatch" }))).toEqual({
      kind: "error",
      message: "The API key does not belong to this tenant.",
    });
  });

  it("explains an unknown tenant and other API errors", () => {
    expect(classifyAskFailure(new ApiError(404, { code: "unknown_tenant" }))).toEqual({
      kind: "error",
      message: "Unknown tenant. Pick another tenant and ask again.",
    });
    expect(classifyAskFailure(new ApiError(422, { code: "validation_error" }))).toEqual({
      kind: "error",
      message: "The request was rejected (422 validation_error).",
    });
  });

  it("ignores an abort and reports anything else as an error", () => {
    const abort = new DOMException("aborted", "AbortError");
    expect(classifyAskFailure(abort)).toBeNull();
    expect(classifyAskFailure(new Error("boom"))).toEqual({ kind: "error", message: "boom" });
  });
});

describe("resolveEventsUrl", () => {
  it("resolves the gateway's relative events_url against the API base", () => {
    expect(resolveEventsUrl("/v1/jobs/j1/events", "http://localhost:8010")).toBe(
      "http://localhost:8010/v1/jobs/j1/events",
    );
  });

  it("keeps an absolute events_url as is", () => {
    expect(resolveEventsUrl("http://127.0.0.1:9/x", "http://localhost:8010")).toBe(
      "http://127.0.0.1:9/x",
    );
  });
});

describe("parseTenants", () => {
  it("splits a comma-separated list, trimming and dropping blanks and duplicates", () => {
    expect(parseTenants(" pharma, demo ,,pharma")).toEqual(["pharma", "demo"]);
  });

  it("defaults to the demo tenant", () => {
    expect(parseTenants(undefined)).toEqual(["demo"]);
    expect(parseTenants(" , ")).toEqual(["demo"]);
  });
});

describe("stepLabel", () => {
  it("names the agent's graph nodes for people", () => {
    expect(stepLabel("plan")).toBe("Planning");
    expect(stepLabel("subagent")).toBe("Searching sources");
    expect(stepLabel("verify")).toBe("Verifying claims");
    expect(stepLabel("re_retrieve")).toBe("Searching again");
    expect(stepLabel("review")).toBe("Human review");
    expect(stepLabel("mystery_node")).toBe("mystery_node");
  });
});
