/**
 * The agent timeline's state, folded from the ask stream's events by a pure reducer.
 *
 * Node names and statuses are the backend answer graph's
 * (`backend/src/driftline/agents/graph.py`): classify -> cache -> plan -> subagent
 * (fan-out, one branch per sub-question) -> merge -> draft -> verify -> [re_retrieve ->
 * draft -> verify]* -> respond -> [review]. Nothing here touches React or the network.
 */
import { stepLabel } from "@/lib/ask/format";
import type {
  AnswerSchema,
  AskEvent,
  Citation,
  ClaimEvent,
  ErrorEvent,
  StepEvent,
} from "@/lib/sse/events";

export const GRAPH_NODES = [
  "classify",
  "cache",
  "plan",
  "subagent",
  "merge",
  "draft",
  "verify",
  "re_retrieve",
  "respond",
  "review",
] as const;

export type NodeName = (typeof GRAPH_NODES)[number];

/** How a node is drawn: not reached yet, running, finished, not run, failed or paused. */
export type NodeStatus = "pending" | "active" | "done" | "skipped" | "failed" | "waiting";

export interface NodeState {
  name: NodeName;
  status: NodeStatus;
  /** How many times the node has started (subagent: one per branch). */
  runs: number;
  /** The last `step` was a `retry` (a re-draft or a repaired draft). */
  retrying: boolean;
  /** The last `step` event's `detail`. */
  detail: Record<string, unknown>;
  /** The last `step` event's time since the ask started, in milliseconds. */
  tMs: number | null;
}

export interface BranchState {
  branch: number;
  question: string;
  status: NodeStatus;
  retrieved: number | null;
  kept: number | null;
  reranked: boolean | null;
}

export interface ClaimCheck {
  idx: number;
  /** `null` while the claim waits to be checked in the current verify pass. */
  verified: boolean | null;
  reason: string | null;
  citation: Citation | null;
}

export type TimelinePhase = "idle" | "running" | "waiting" | "done" | "failed";

export interface TimelineState {
  phase: TimelinePhase;
  nodes: Record<NodeName, NodeState>;
  /** Nodes in the order they first lit up (started or finished; never a skip). */
  lit: NodeName[];
  /** One per sub-question of the plan, in branch order. */
  branches: BranchState[];
  /** The claims of the current verify pass. */
  claims: ClaimCheck[];
  /** Completed or running re-retrieve passes (0: the first pass is still the only one). */
  iteration: number;
  cache: "hit" | "miss" | "skipped" | null;
  /** The last stream error; cleared when a retried job makes progress again. */
  error: ErrorEvent | null;
  answer: AnswerSchema | null;
}

function node(name: NodeName): NodeState {
  return { name, status: "pending", runs: 0, retrying: false, detail: {}, tMs: null };
}

export const initialTimeline: TimelineState = {
  phase: "idle",
  nodes: Object.fromEntries(GRAPH_NODES.map((name) => [name, node(name)])) as Record<
    NodeName,
    NodeState
  >,
  lit: [],
  branches: [],
  claims: [],
  iteration: 0,
  cache: null,
  error: null,
  answer: null,
};

const isNodeName = (name: string): name is NodeName =>
  (GRAPH_NODES as readonly string[]).includes(name);

const num = (value: unknown): number | null => (typeof value === "number" ? value : null);
const str = (value: unknown): string | null => (typeof value === "string" ? value : null);

function statusOf(step: StepEvent["status"]): NodeStatus {
  switch (step) {
    case "started":
    case "retry":
      return "active";
    case "completed":
    case "hit":
    case "miss":
      return "done";
    case "skipped":
      return "skipped";
    case "failed":
      return "failed";
    case "waiting":
      return "waiting";
  }
}

/** The subagent node as a whole: active until every branch is back. */
function aggregate(branches: BranchState[]): NodeStatus {
  if (branches.some((b) => b.status === "failed")) return "failed";
  if (branches.some((b) => b.status === "active" || b.status === "pending")) return "active";
  return "done";
}

function upsertBranch(
  branches: BranchState[],
  index: number,
  patch: Partial<BranchState>,
): BranchState[] {
  const next = [...branches];
  const at = next.findIndex((b) => b.branch === index);
  const base: BranchState =
    at >= 0
      ? next[at]!
      : {
          branch: index,
          question: "",
          status: "pending",
          retrieved: null,
          kept: null,
          reranked: null,
        };
  const merged = { ...base, ...patch };
  if (at >= 0) next[at] = merged;
  else next.push(merged);
  return next.sort((a, b) => a.branch - b.branch);
}

function onStep(state: TimelineState, event: StepEvent): TimelineState {
  if (!isNodeName(event.node)) return state;
  const name = event.node;
  const detail = event.detail ?? {};
  const prev = state.nodes[name];
  let status = statusOf(event.status);
  const repair = event.status === "retry" && detail.reason === "repair";
  const runs =
    prev.runs + (event.status === "started" || (event.status === "retry" && !repair) ? 1 : 0);

  let { branches, claims, iteration, cache, phase } = state;

  if (name === "plan" && event.status === "completed" && Array.isArray(detail.sub_questions)) {
    branches = detail.sub_questions.map((sub, branch) => ({
      branch,
      question: str((sub as { question?: unknown }).question) ?? "",
      status: "pending" as const,
      retrieved: null,
      kept: null,
      reranked: null,
    }));
  }

  if (name === "subagent") {
    const index = num(detail.branch) ?? 0;
    const patch: Partial<BranchState> = { status };
    const question = str(detail.sub_question);
    if (question) patch.question = question;
    if (event.status === "completed") {
      patch.retrieved = num(detail.retrieved);
      patch.kept = num(detail.kept);
      patch.reranked = typeof detail.reranked === "boolean" ? detail.reranked : null;
    }
    branches = upsertBranch(branches, index, patch);
    status = aggregate(branches);
  }

  if (name === "verify" && event.status === "started") {
    // A new verify pass: every claim of the latest draft waits to be checked again.
    const count = num(state.nodes.draft.detail.claims) ?? state.claims.length;
    claims = Array.from({ length: count }, (_, idx) => ({
      idx,
      verified: null,
      reason: null,
      citation: null,
    }));
  }

  if (name === "re_retrieve") {
    iteration = Math.max(
      iteration,
      num(detail.attempt) ?? iteration + (event.status === "started" ? 1 : 0),
    );
  }

  if (name === "cache")
    cache = event.status === "hit" ? "hit" : event.status === "skipped" ? "skipped" : "miss";

  if (status === "waiting") phase = "waiting";
  else if (phase !== "failed" || state.error?.retryable) phase = "running";

  const lit = status !== "skipped" && !state.lit.includes(name) ? [...state.lit, name] : state.lit;

  return {
    ...state,
    phase,
    nodes: {
      ...state.nodes,
      [name]: {
        ...prev,
        status,
        runs,
        retrying: event.status === "retry",
        detail,
        tMs: event.t_ms ?? prev.tMs,
      },
    },
    lit,
    branches,
    claims,
    iteration,
    cache,
    error: null,
  };
}

function onClaim(state: TimelineState, event: ClaimEvent): TimelineState {
  const check: ClaimCheck = {
    idx: event.idx,
    verified: event.verified,
    reason: event.reason ?? null,
    citation: event.citation ?? null,
  };
  const claims = state.claims.some((c) => c.idx === event.idx)
    ? state.claims.map((c) => (c.idx === event.idx ? check : c))
    : [...state.claims, check].sort((a, b) => a.idx - b.idx);
  return { ...state, claims };
}

/** Rewrites every node in `from` to `to`. */
function settle(nodes: Record<NodeName, NodeState>, from: NodeStatus, to: NodeStatus) {
  return Object.fromEntries(
    GRAPH_NODES.map((name) => {
      const n = nodes[name];
      return [name, n.status === from ? { ...n, status: to } : n];
    }),
  ) as Record<NodeName, NodeState>;
}

export function timelineReducer(state: TimelineState, event: AskEvent): TimelineState {
  switch (event.type) {
    case "step":
      return onStep(state, event);
    case "claim":
      return onClaim(state, event);
    case "final": {
      // The run is over: whatever was running finished, whatever never ran was skipped.
      const nodes = settle(settle(state.nodes, "active", "done"), "pending", "skipped");
      return { ...state, phase: "done", nodes, answer: event.answer, error: null };
    }
    case "error":
      return {
        ...state,
        phase: event.retryable ? state.phase : "failed",
        nodes: settle(state.nodes, "active", "failed"),
        error: event,
      };
    default:
      return state;
  }
}

/** The timeline for a whole stream (`timelineReducer` folded over the events). */
export function buildTimeline(events: readonly AskEvent[]): TimelineState {
  return events.reduce(timelineReducer, initialTimeline);
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** One sentence for the live region: what the agent is doing, or how it ended. */
export function summarizeTimeline(state: TimelineState): string {
  switch (state.phase) {
    case "idle":
      return "";
    case "waiting":
      return "Paused: waiting for human review.";
    case "failed": {
      const failed = GRAPH_NODES.find((n) => state.nodes[n].status === "failed");
      const what = failed ? `${stepLabel(failed)} failed` : "The answer stream failed";
      return `Stopped: ${what} (${state.error?.code ?? "error"}).`;
    }
    case "done": {
      const answer = state.answer;
      if (!answer) return "Done.";
      if (answer.cached) return "Done: served from the cache.";
      if (answer.status === "refused") return "Done: Driftline declined to answer.";
      if (answer.status === "insufficient_evidence") {
        const n = answer.nearest_sources?.length ?? 0;
        return `Done: not enough evidence to answer; ${plural(n, "nearest source")} found.`;
      }
      const verified = state.claims.filter((c) => c.verified).length;
      return `Done: ${verified} of ${state.claims.length} claims verified.`;
    }
    case "running": {
      const current = [...state.lit].reverse().find((n) => state.nodes[n].status === "active");
      const name = current ?? state.lit.at(-1);
      if (!name) return "Starting…";
      const pass =
        state.iteration > 0 && (name === "draft" || name === "verify")
          ? ` (pass ${state.iteration + 1})`
          : "";
      let progress = "";
      if (name === "subagent" && state.branches.length) {
        const done = state.branches.filter((b) => b.status === "done").length;
        progress = `: ${done} of ${state.branches.length} searches done`;
      } else if (name === "verify" && state.claims.length) {
        const checked = state.claims.filter((c) => c.verified !== null).length;
        progress = `: ${checked} of ${state.claims.length} claims checked`;
      }
      const label = stepLabel(name);
      return progress || pass ? `${label}${pass}${progress}.` : `${label}…`;
    }
  }
}
