/**
 * Pure helpers for the Ask view: dates, citations, the Retry-After countdown and error
 * classification. Nothing here touches React, the network or the clock.
 */
import { ApiError } from "@/lib/api/client";
import type { Citation, Claim } from "@/lib/sse/events";

const DATE_FORMAT = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

/** An ISO timestamp as a UTC calendar date ("1 Jun 2024"); other text is returned as is. */
export function formatDate(iso: string): string {
  const at = Date.parse(iso);
  return Number.isNaN(at) ? iso : DATE_FORMAT.format(at);
}

const pad = (n: number, width = 2): string => String(n).padStart(width, "0");

/**
 * The picked calendar day (in the viewer's time zone) as midnight UTC, the form the
 * gateway's `as_of` takes. `null` leaves `as_of` out, so the backend uses today.
 */
export function toAsOfParam(date: Date | null): string | null {
  if (!date) return null;
  return `${pad(date.getFullYear(), 4)}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T00:00:00Z`;
}

export interface CitationDetails {
  quote: string;
  /** Null for a citation stored before answers carried version metadata. */
  title: string | null;
  section: string | null;
  version: string;
  /** "Valid from …" or "Valid … to …"; null when the citation has no metadata. */
  validity: string | null;
}

function shortId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id;
}

/**
 * A version's validity window in plain words: "In force from 1 Jun 2024", or
 * "In force 1 May 2019 to 1 Jun 2024" for a version that has since been replaced.
 */
export function formatValidity(validFrom: string, validTo?: string | null): string {
  return validTo
    ? `In force ${formatDate(validFrom)} to ${formatDate(validTo)}`
    : `In force from ${formatDate(validFrom)}`;
}

/** A section path as a readable breadcrumb: "B > Renal" -> "B › Renal". */
export function formatSection(path: string | null | undefined): string | null {
  const parts = (path ?? "")
    .split(/\s*[>›]\s*/)
    .map((p) => p.trim())
    .filter(Boolean);
  return parts.length ? parts.join(" › ") : null;
}

export type ConfidenceLevel = "High" | "Medium" | "Low";

/** The answer's confidence as a word, with what it means. */
export function confidenceLevel(confidence: number): {
  level: ConfidenceLevel;
  explanation: string;
} {
  const percent = Math.round(confidence * 100);
  const level: ConfidenceLevel = confidence >= 0.8 ? "High" : confidence >= 0.5 ? "Medium" : "Low";
  const meaning =
    level === "High"
      ? "The cited passages clearly support this answer."
      : level === "Medium"
        ? "The cited passages support this answer, with some gaps."
        : "The evidence is thin: check the sources before relying on it.";
  return { level, explanation: `${meaning} (Confidence score ${percent}%.)` };
}

/**
 * What a citation's hover card shows: the quote plus the cited version's document title,
 * version number, section and validity window, all carried by the citation itself.
 * Citations stored before that metadata existed fall back to the version id.
 */
export function describeCitation(citation: Citation): CitationDetails {
  return {
    quote: citation.quote,
    title: citation.title ?? null,
    section: formatSection(citation.section_path),
    version:
      citation.version_no != null
        ? `v${citation.version_no}`
        : `version ${shortId(citation.version_id)}`,
    validity: citation.valid_from ? formatValidity(citation.valid_from, citation.valid_to) : null,
  };
}

/** Footnote numbers: each distinct chunk once, in order of first appearance. */
export function citationNumbers(claims: Pick<Claim, "citations">[]): Map<string, number> {
  const numbers = new Map<string, number>();
  for (const claim of claims) {
    for (const citation of claim.citations) {
      if (!numbers.has(citation.chunk_id)) numbers.set(citation.chunk_id, numbers.size + 1);
    }
  }
  return numbers;
}

/** Whole seconds until `until` (ms epoch), rounded up, never negative. */
export function secondsLeft(until: number, now: number): number {
  return Math.max(0, Math.ceil((until - now) / 1000));
}

/** Seconds as `m:ss`. */
export function formatCountdown(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${pad(s % 60)}`;
}

/** The wait used when a 429 carries no usable `Retry-After`. */
export const DEFAULT_RETRY_AFTER_S = 5;

export type AskFailure =
  | { kind: "rate_limited"; retryAfter: number }
  | { kind: "backend_down"; message: string }
  | { kind: "error"; message: string };

const DOWN_STATUSES = new Set([502, 503, 504]);

/** How the Ask view should present a failed call; `null` for an abort (not a failure). */
export function classifyAskFailure(error: unknown): AskFailure | null {
  // DOMException is not an Error subclass in every runtime, so check the name.
  if (error && typeof error === "object" && (error as { name?: unknown }).name === "AbortError") {
    return null;
  }
  if (error instanceof ApiError) {
    if (error.status === 429) {
      return { kind: "rate_limited", retryAfter: error.retryAfter ?? DEFAULT_RETRY_AFTER_S };
    }
    if (error.status === 0) {
      return { kind: "backend_down", message: "The Driftline API can't be reached." };
    }
    if (DOWN_STATUSES.has(error.status)) {
      return {
        kind: "backend_down",
        message: `The Driftline API is unavailable (${error.status}).`,
      };
    }
    if (error.code === "unknown_tenant") {
      return { kind: "error", message: "Unknown tenant. Pick another tenant and ask again." };
    }
    if (error.status === 401) {
      return { kind: "error", message: "The API key is missing or invalid." };
    }
    if (error.status === 403) {
      return { kind: "error", message: "The API key does not belong to this tenant." };
    }
    return {
      kind: "error",
      message: `The request was rejected (${error.status}${error.code ? ` ${error.code}` : ""}).`,
    };
  }
  return { kind: "error", message: error instanceof Error ? error.message : String(error) };
}

/** The gateway returns `events_url` relative to itself. */
export function resolveEventsUrl(eventsUrl: string, baseUrl: string): string {
  return new URL(eventsUrl, `${baseUrl.replace(/\/+$/, "")}/`).toString();
}

/** Tenant names from a comma-separated list (NEXT_PUBLIC_DRIFTLINE_TENANTS). */
export function parseTenants(raw: string | undefined): string[] {
  const names = (raw ?? "")
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);
  const unique = [...new Set(names)];
  return unique.length ? unique : ["demo"];
}

const STEP_LABELS: Record<string, string> = {
  classify: "Understanding the question",
  cache: "Checking for a saved answer",
  plan: "Planning the search",
  subagent: "Searching the documents",
  merge: "Gathering the evidence",
  draft: "Writing the answer",
  verify: "Checking claims against sources",
  re_retrieve: "Looking for more evidence",
  respond: "Finishing up",
  review: "Waiting for a reviewer",
};

/** A step of the answer graph in plain words. */
export function stepLabel(node: string): string {
  return STEP_LABELS[node] ?? node.replaceAll("_", " ");
}

/**
 * The one-line progress shown while an answer streams, e.g. "Searching the documents in
 * force on 1 Jun 2024…". `asOf` is the date being asked about (null: today).
 */
export function progressLine(node: string | null, asOf: string | null): string {
  const when = asOf ? `on ${formatDate(asOf)}` : "today";
  switch (node) {
    case null:
      return "Getting started…";
    case "classify":
      return "Reading your question…";
    case "plan":
    case "subagent":
    case "merge":
      return `Searching the documents in force ${when}…`;
    case "re_retrieve":
      return `Looking for more evidence in force ${when}…`;
    case "verify":
      return "Checking each claim against its source…";
    default:
      return `${stepLabel(node)}…`;
  }
}
