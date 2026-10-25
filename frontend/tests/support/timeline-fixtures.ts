/**
 * Ask event sequences for the agent timeline, typed with the SSE contract types.
 *
 * The contract ships one answered example (`ask-answered.json`, a single sub-question).
 * The other runs are built the way the backend graph (`backend/src/driftline/agents/
 * graph.py`) emits them: the same node names, statuses and `detail` keys.
 */
import type { AnswerSchema } from "@/lib/api/client";
import type { AskEvent, ClaimEvent, Citation, StepEvent } from "@/lib/sse/events";

import { ANSWERED, ANSWERED_EVENTS, NEAR_SOURCES, REVIEW_WAITING_EVENTS } from "./ask-fixtures";

const AS_OF = "2024-06-01T00:00:00+00:00";

function step(
  node: string,
  status: StepEvent["status"],
  t_ms: number,
  detail: Record<string, unknown> = {},
): StepEvent {
  return { type: "step", node, status, t_ms, detail };
}

const CITATION: Citation = ANSWERED.claims![0]!.citations[0]!;

function claim(idx: number, verified: boolean, reason: string | null = null): ClaimEvent {
  return { type: "claim", idx, verified, reason, citation: verified ? CITATION : null };
}

/** Every event of the contract's answered stream except tokens (the hook keeps those apart). */
export const ANSWERED_RUN: AskEvent[] = ANSWERED_EVENTS.filter((e) => e.event !== "token").map(
  (e) => e.data as AskEvent,
);

const QUESTIONS = [
  "How often should ALT be checked?",
  "What is the maximum daily dose?",
  "Which patients need a lower dose?",
];

const START: AskEvent[] = [
  step("classify", "started", 0),
  step("classify", "completed", 2, { as_of: AS_OF, source: "request", refused: null }),
  step("cache", "miss", 9),
];

/** A parallel plan: three subagents run at once and finish out of order. */
export const FAN_OUT_RUN: AskEvent[] = [
  ...START,
  step("plan", "started", 10),
  step("plan", "completed", 800, {
    mode: "parallel",
    sub_questions: QUESTIONS.map((question) => ({ question, as_of: AS_OF })),
    error: null,
  }),
  step("subagent", "started", 801, { branch: 0, sub_question: QUESTIONS[0], as_of: AS_OF }),
  step("subagent", "started", 802, { branch: 1, sub_question: QUESTIONS[1], as_of: AS_OF }),
  step("subagent", "started", 803, { branch: 2, sub_question: QUESTIONS[2], as_of: AS_OF }),
  step("subagent", "completed", 1100, {
    branch: 1,
    retrieved: 30,
    kept: 6,
    reranked: true,
    rerank_error: null,
  }),
  step("subagent", "completed", 1200, {
    branch: 0,
    retrieved: 28,
    kept: 8,
    reranked: true,
    rerank_error: null,
  }),
];

/** The fan-out run once every branch is back and merged. */
export const FAN_OUT_MERGED: AskEvent[] = [
  ...FAN_OUT_RUN,
  step("subagent", "completed", 1300, {
    branch: 2,
    retrieved: 12,
    kept: 3,
    reranked: false,
    rerank_error: "timeout",
  }),
  step("merge", "completed", 1301, { evidence: 17 }),
];

const SINGLE_PLAN: AskEvent[] = [
  ...START,
  step("plan", "started", 10),
  step("plan", "completed", 800, {
    mode: "single",
    sub_questions: [{ question: QUESTIONS[0], as_of: AS_OF }],
    error: null,
  }),
  step("subagent", "started", 801, { branch: 0, sub_question: QUESTIONS[0], as_of: AS_OF }),
  step("subagent", "completed", 1200, {
    branch: 0,
    retrieved: 30,
    kept: 8,
    reranked: true,
    rerank_error: null,
  }),
  step("merge", "completed", 1201, { evidence: 8 }),
];

/** Verify rejects a claim, the graph re-retrieves and drafts again (attempt 1), twice. */
export const RE_RETRIEVE_RUN: AskEvent[] = [
  ...SINGLE_PLAN,
  step("draft", "started", 1202, { attempt: 0 }),
  step("draft", "completed", 3000, { attempt: 0, claims: 2 }),
  step("verify", "started", 3001, { attempt: 0 }),
  claim(0, true),
  claim(1, false, "quote_not_found"),
  step("verify", "completed", 3500, { supported: 1, unsupported: 1 }),
  step("re_retrieve", "started", 3501, { attempt: 1, claims: 1 }),
  step("re_retrieve", "completed", 3900, { attempt: 1, found: 4 }),
  step("draft", "retry", 3901, { attempt: 1 }),
  step("draft", "completed", 5000, { attempt: 1, claims: 2 }),
  step("verify", "started", 5001, { attempt: 1 }),
  claim(0, true),
];

/** The re-retrieve loop's second pass verifies the claim it lost the first time. */
export const RE_RETRIEVE_DONE: AskEvent[] = [
  ...RE_RETRIEVE_RUN,
  claim(1, true),
  step("verify", "completed", 5600, { supported: 2, unsupported: 0 }),
  step("respond", "completed", 5601, { outcome: "answered", error: null }),
  { type: "final", answer: { ...ANSWERED, confidence: 1 } },
];

/** The draft node fails, then the worker gives up with a non-retryable error. */
export const ERROR_RUN: AskEvent[] = [
  ...SINGLE_PLAN,
  step("draft", "started", 1202, { attempt: 0 }),
  step("draft", "failed", 2000, { attempt: 0, error: "malformed_draft" }),
  { type: "error", code: "internal", message: "RuntimeError", retryable: false },
];

/** The answered stream paused at the review node (`step review waiting`). */
export const REVIEW_WAITING_RUN: AskEvent[] = REVIEW_WAITING_EVENTS.filter(
  (e) => e.event !== "token",
).map((e) => e.data as AskEvent);

const CACHED: AnswerSchema = { ...ANSWERED, cached: true, answer_id: null, cost_usd: 0 };

/** A semantic-cache hit: classify, cache hit, then straight to respond. */
export const CACHE_HIT_RUN: AskEvent[] = [
  step("classify", "started", 0),
  step("classify", "completed", 2, { as_of: AS_OF, source: "request", refused: null }),
  step("cache", "hit", 8, { similarity: 0.9731 }),
  step("respond", "completed", 9, { outcome: "answered", error: null }),
  { type: "final", answer: CACHED },
];

/** Nothing in force answers the question: insufficient evidence with nearest sources. */
export const INSUFFICIENT_RUN: AskEvent[] = [
  ...SINGLE_PLAN,
  step("draft", "started", 1202, { attempt: 0 }),
  step("draft", "completed", 3000, { attempt: 0, claims: 1 }),
  step("verify", "started", 3001, { attempt: 0 }),
  claim(0, false, "quote_not_found"),
  step("verify", "completed", 3500, { supported: 0, unsupported: 1 }),
  step("respond", "completed", 3501, { outcome: "insufficient_evidence", error: null }),
  {
    type: "final",
    answer: {
      ...ANSWERED,
      status: "insufficient_evidence",
      answer: "There is not enough in-force evidence to answer this as of 2024-06-01.",
      claims: [],
      citations: [],
      confidence: 0,
      nearest_sources: NEAR_SOURCES,
    },
  },
];
