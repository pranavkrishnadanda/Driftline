/**
 * Real Ask props, built from the SSE contract fixture (`tests/fixtures/sse/*.json`) and
 * typed with the contract types. The contract ships one answered example, so the other
 * outcomes are derived from it with only the fields the contract says change.
 */
import type { AnswerSchema, NearestSource } from "@/lib/api/client";
import type { AskEvent, FinalEvent, StepEvent } from "@/lib/sse/events";

import answered from "../fixtures/sse/ask-answered.json";
import type { FixtureEvent } from "./sse-server";

export const ANSWERED_EVENTS = answered.events as FixtureEvent[];

export const ANSWERED_FINAL = ANSWERED_EVENTS.find((e) => e.event === "final")!.data as FinalEvent;

export const ANSWERED: AnswerSchema = ANSWERED_FINAL.answer as AnswerSchema;

export const ANSWERED_TEXT = ANSWERED_EVENTS.filter((e) => e.event === "token")
  .map((e) => (e.data as { text: string }).text)
  .join("");

/** Every non-token event of the answered stream up to (not including) `final`. */
export const ANSWERED_PROGRESS: AskEvent[] = ANSWERED_EVENTS.filter(
  (e) => e.event !== "token" && e.event !== "final",
).map((e) => e.data as AskEvent);

export const LAST_STEP = ANSWERED_PROGRESS.filter((e): e is StepEvent => e.type === "step").at(-1)!;

/**
 * The answered stream paused for human review (P4 T5): the contract's events up to
 * `respond`, then the review node's `step {node: "review", status: "waiting"}` instead of
 * `final`. The graph runs `respond` then `review`, and the worker emits `waiting` with the
 * interrupt's reason in `detail`.
 */
const RESPOND_STEP = ANSWERED_EVENTS.findLast((e) => e.event === "step")!;

export const REVIEW_WAITING_STEP = {
  type: "step",
  node: "review",
  status: "waiting",
  detail: { reason: "low_confidence" },
  t_ms: (RESPOND_STEP.data as StepEvent).t_ms,
} satisfies StepEvent;

export const REVIEW_WAITING_EVENTS: FixtureEvent[] = [
  ...ANSWERED_EVENTS.filter((e) => e.event !== "final"),
  { id: RESPOND_STEP.id! + 1, event: "step", data: REVIEW_WAITING_STEP },
];

/** The paused stream, then the answer once a reviewer approves it (same stream, resumed). */
export const REVIEW_APPROVED_EVENTS: FixtureEvent[] = [
  ...REVIEW_WAITING_EVENTS,
  finalFrame(ANSWERED, RESPOND_STEP.id! + 2),
];

/** Nearest sources for the insufficient-evidence outcome. */
export const NEAR_SOURCES: NearestSource[] = [
  {
    document_id: "00000000-0000-4000-8000-0000000000d1",
    external_id: "acme-label",
    section_path: "Warnings > Hepatotoxicity",
    title: "Acme tablets label",
    valid_from: "2023-02-14T00:00:00Z",
    valid_to: null,
    version_id: "00000000-0000-4000-8000-0000000000a2",
    version_no: 3,
  },
  {
    document_id: "00000000-0000-4000-8000-0000000000d2",
    external_id: "acme-label-2019",
    section_path: "Dosage",
    title: "Acme tablets label (2019)",
    valid_from: "2019-05-01T00:00:00Z",
    valid_to: "2023-02-14T00:00:00Z",
    version_id: "00000000-0000-4000-8000-0000000000a1",
    version_no: 2,
  },
];

/** The answered example as the contract's insufficient-evidence outcome. */
export function insufficientAnswer(overrides: Partial<AnswerSchema> = {}): AnswerSchema {
  return {
    ...ANSWERED,
    status: "insufficient_evidence",
    answer: "",
    claims: [],
    citations: [],
    confidence: 0,
    nearest_sources: NEAR_SOURCES,
    ...overrides,
  };
}

export function finalFrame(answer: AnswerSchema, id: number): FixtureEvent {
  return { id, event: "final", data: { type: "final", answer } satisfies FinalEvent };
}
