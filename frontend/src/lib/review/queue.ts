/**
 * The review queue's pure logic: grouping, how each kind of item reads, the edit body
 * the gateway expects, and an optimistic list that rolls back. No React or network.
 *
 * Item payloads are written by the backend (spec section 8):
 *   low_confidence_answer  {reason, question, answer: AnswerSchema, job_id, ...}
 *   broken_answer, answer  {reason: "broken", document_id, new_version_id, claims}
 *   relation               {reason, kind, target_external_id, evidence_quote, confidence}
 *                          or {error: "malformed_extraction", detail, raw}
 * They are untyped JSON, so every field is read defensively.
 */
import type { ResolveRequest, ReviewItem, ReviewKind } from "@/lib/api/client";

export const KIND_ORDER: readonly ReviewKind[] = [
  "low_confidence_answer",
  "broken_answer",
  "relation",
  "answer",
];

const KIND_LABELS: Record<ReviewKind, string> = {
  low_confidence_answer: "Low-confidence answers",
  broken_answer: "Broken answers",
  relation: "Suggested document links",
  answer: "Regenerated answers",
};

/** The relation kinds a reviewer may pick (`RELATION_KINDS` in the review queue). */
export const RELATION_KINDS = ["supersedes", "amends", "deprecates"] as const;

export interface ReviewGroup {
  kind: ReviewKind;
  label: string;
  items: ReviewItem[];
}

export function groupByKind(items: readonly ReviewItem[]): ReviewGroup[] {
  return KIND_ORDER.map((kind) => ({
    kind,
    label: KIND_LABELS[kind],
    items: items.filter((item) => item.kind === kind),
  })).filter((group) => group.items.length > 0);
}

export type ItemEdit =
  | { field: "answer"; initial: string }
  | { field: "kind"; initial: string; options: typeof RELATION_KINDS };

/** How an item reads at a glance: a coloured status and what the reviewer should do. */
export interface ItemStatus {
  tone: "changed" | "broken" | "brand";
  label: string;
  next: string;
}

export interface ItemView {
  title: string;
  status: ItemStatus;
  /** The text under review (a draft answer, the affected claims, the evidence). */
  body: string | null;
  facts: { label: string; value: string }[];
  /** How the inline editor edits this item; null when it cannot be edited. */
  edit: ItemEdit | null;
}

type Json = Record<string, unknown>;

const str = (value: unknown): string | null =>
  typeof value === "string" && value.trim() ? value : null;
const num = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;
const obj = (value: unknown): Json | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Json) : null;
const percent = (value: number): string => `${Math.round(value * 100)}%`;
const capitalise = (text: string): string => text.charAt(0).toUpperCase() + text.slice(1);

/** Why an item is here, in words (the raw reason codes are internal). */
const REASONS: Record<string, string> = {
  low_confidence: "Not confident enough to show",
  broken: "Its source text was removed",
  watched_answer: "Regenerated after its sources changed",
};

function reasonFact(payload: Json): { label: string; value: string }[] {
  const reason = str(payload.reason);
  return reason ? [{ label: "Why", value: REASONS[reason] ?? reason.replaceAll("_", " ") }] : [];
}

function confidenceFact(confidence: number | null): { label: string; value: string }[] {
  if (confidence === null) return [];
  const level = confidence >= 0.8 ? "High" : confidence >= 0.5 ? "Medium" : "Low";
  return [{ label: "Confidence", value: `${level} (${percent(confidence)})` }];
}

function describeAnswer(payload: Json): ItemView {
  const answer = obj(payload.answer);
  const text = str(answer?.answer);
  const confidence = num(answer?.confidence);
  return {
    title: str(payload.question) ?? "Low-confidence answer",
    status: {
      tone: "changed",
      label: "Needs a second look",
      next: "Driftline held this answer back. Approve it, correct it, or reject it.",
    },
    body: text,
    facts: [...reasonFact(payload), ...confidenceFact(confidence)],
    edit: { field: "answer", initial: text ?? "" },
  };
}

function describeBroken(payload: Json): ItemView {
  const claims = Array.isArray(payload.claims) ? payload.claims : [];
  const texts = claims.map((c) => str(obj(c)?.text)).filter((t): t is string => t !== null);
  return {
    title: "A watched answer no longer matches its source",
    status: {
      tone: "broken",
      label: "Broken: the cited text was removed",
      next: "Approve to rebuild the answer from the current version, edit it yourself, or reject it to retire it.",
    },
    body: texts.length ? texts.join("\n") : null,
    facts: reasonFact(payload),
    edit: { field: "answer", initial: "" },
  };
}

function describeRelation(payload: Json): ItemView {
  if (payload.error === "malformed_extraction") {
    return {
      title: "Couldn't read a document link",
      status: {
        tone: "broken",
        label: "Needs attention",
        next: "Driftline couldn't work out how this document relates to another. Approve to dismiss, or reject.",
      },
      body: str(payload.detail),
      facts: [],
      edit: null,
    };
  }
  const kind = str(payload.kind);
  const target = str(payload.target_external_id);
  const confidence = num(payload.confidence);
  return {
    title: kind && target ? `${capitalise(kind)} ${target}` : "Proposed relation",
    status: {
      tone: "brand",
      label: "Suggested link",
      next:
        kind && target
          ? `Driftline thinks this document ${kind} ${target}. Approve to record the link, change its kind, or reject it.`
          : "Approve to record the link, change its kind, or reject it.",
    },
    body: str(payload.evidence_quote),
    facts: [...reasonFact(payload), ...confidenceFact(confidence)],
    edit: { field: "kind", initial: kind ?? RELATION_KINDS[0], options: RELATION_KINDS },
  };
}

export function describeItem(item: ReviewItem): ItemView {
  const payload = obj(item.payload) ?? {};
  switch (item.kind) {
    case "low_confidence_answer":
      return describeAnswer(payload);
    case "relation":
      return describeRelation(payload);
    case "broken_answer":
    case "answer":
      return describeBroken(payload);
  }
}

/** The `edit` of a resolve request: `{kind}` for a relation, `{answer}` otherwise. */
export function editBody(item: ReviewItem, value: string): NonNullable<ResolveRequest["edit"]> {
  return item.kind === "relation" ? { kind: value } : { answer: value.trim() };
}

// ---------------------------------------------------------------------------------
// Optimistic list

export interface QueueState {
  items: ReviewItem[];
  /** Items hidden while their resolve is in flight, with where they were. */
  pending: Record<string, { item: ReviewItem; index: number }>;
}

export type QueueAction =
  | { type: "load"; items: ReviewItem[] }
  | { type: "resolving"; id: string }
  | { type: "resolved"; id: string }
  | { type: "rollback"; id: string };

export const INITIAL_QUEUE: QueueState = { items: [], pending: {} };

function without<T>(record: Record<string, T>, key: string): Record<string, T> {
  const { [key]: _removed, ...rest } = record;
  return rest;
}

export function queueReducer(state: QueueState, action: QueueAction): QueueState {
  switch (action.type) {
    case "load":
      return { ...state, items: action.items.filter((item) => !(item.id in state.pending)) };
    case "resolving": {
      const index = state.items.findIndex((item) => item.id === action.id);
      if (index < 0) return state;
      return {
        items: state.items.filter((_, i) => i !== index),
        pending: { ...state.pending, [action.id]: { item: state.items[index], index } },
      };
    }
    case "resolved":
      return action.id in state.pending
        ? { ...state, pending: without(state.pending, action.id) }
        : state;
    case "rollback": {
      const entry = state.pending[action.id];
      if (!entry) return state;
      const items = [...state.items];
      items.splice(Math.min(entry.index, items.length), 0, entry.item);
      return { items, pending: without(state.pending, action.id) };
    }
  }
}
