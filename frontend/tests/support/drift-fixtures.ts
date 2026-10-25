/**
 * Drift and review fixtures shaped by the contracts: `AlertEvent` from
 * contracts/sse/alert-events.v1.json, `DriftEvent` and `ReviewItem` from
 * contracts/openapi.json (through the generated client types).
 */
import type { DriftEvent, ReviewItem } from "@/lib/api/client";
import type { AlertEvent } from "@/lib/sse/events";

import type { FixtureEvent } from "./sse-server";

export const TENANT_ID = "0b6c7f1e-2d1f-4a50-9d0e-6a1f2b3c4d5e";

export function alert(overrides: Partial<AlertEvent> & { drift_event_id: string }): AlertEvent {
  return {
    type: "alert",
    answer_id: "a1111111-1111-4111-8111-111111111111",
    verdict: "broken",
    document_title: "Dosing guideline",
    old_version_id: "00000000-0000-4000-8000-0000000000a1",
    new_version_id: "00000000-0000-4000-8000-0000000000a2",
    before: "Take 10 mg twice daily with food.",
    after: "Take 20 mg once daily with food.",
    t: "2026-10-20T10:00:00Z",
    ...overrides,
  };
}

export function driftEvent(overrides: Partial<DriftEvent> & { id: string }): DriftEvent {
  return {
    answer_id: "a1111111-1111-4111-8111-111111111111",
    claim_idx: 0,
    verdict: "changed",
    old_version_id: "00000000-0000-4000-8000-0000000000b1",
    new_version_id: "00000000-0000-4000-8000-0000000000b2",
    document_id: "d0000000-0000-4000-8000-000000000001",
    document_title: "Storage policy",
    section_path: "Storage > Temperature",
    before: "Store below 25 C.",
    after: "Store below 30 C.",
    diff: null,
    created_at: "2026-10-19T09:00:00Z",
    ...overrides,
  };
}

/** One SSE frame of the alert stream. */
export function alertFrame(id: number, event: AlertEvent): FixtureEvent {
  return { id, event: "alert", data: event };
}

export const EXPIRED_FRAME: FixtureEvent = {
  id: null,
  event: "error",
  data: {
    type: "error",
    code: "events_expired",
    retryable: false,
    message: "alerts after 0 are no longer stored; GET /v1/drift/events",
  },
};

export function reviewItem(overrides: Partial<ReviewItem> & { id: string }): ReviewItem {
  return {
    kind: "low_confidence_answer",
    ref_id: "c0000000-0000-4000-8000-000000000001",
    tenant_id: TENANT_ID,
    status: "open",
    payload: {},
    resolution: null,
    resolved_at: null,
    resolved_by: null,
    created_at: "2026-10-20T08:00:00Z",
    ...overrides,
  };
}

export const LOW_CONFIDENCE = reviewItem({
  id: "11111111-0000-4000-8000-000000000001",
  kind: "low_confidence_answer",
  payload: {
    reason: "low_confidence",
    question: "What is the maximum daily dose?",
    answer: { answer: "The maximum daily dose is 40 mg.", confidence: 0.42, status: "answered" },
  },
});

export const BROKEN = reviewItem({
  id: "22222222-0000-4000-8000-000000000002",
  kind: "broken_answer",
  ref_id: "a1111111-1111-4111-8111-111111111111",
  payload: {
    reason: "broken",
    document_id: "d0000000-0000-4000-8000-000000000001",
    new_version_id: "00000000-0000-4000-8000-0000000000a2",
    claims: [{ idx: 0, text: "Take 10 mg twice daily." }],
  },
});

export const RELATION = reviewItem({
  id: "33333333-0000-4000-8000-000000000003",
  kind: "relation",
  payload: {
    reason: "low_confidence",
    kind: "amends",
    target_external_id: "SOP-12",
    evidence_quote: "This revision amends SOP-12.",
    confidence: 0.61,
  },
});

export const LEGACY_ANSWER = reviewItem({
  id: "44444444-0000-4000-8000-000000000004",
  kind: "answer",
  payload: { reason: "broken" },
});
