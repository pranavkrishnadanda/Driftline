import { describe, expect, it } from "vitest";

import {
  buildTimeline,
  initialTimeline,
  summarizeTimeline,
  timelineReducer,
} from "@/components/agent-timeline/reducer";
import type { AskEvent } from "@/lib/sse/events";

import {
  ANSWERED_RUN,
  CACHE_HIT_RUN,
  ERROR_RUN,
  FAN_OUT_MERGED,
  FAN_OUT_RUN,
  INSUFFICIENT_RUN,
  RE_RETRIEVE_DONE,
  RE_RETRIEVE_RUN,
  REVIEW_WAITING_RUN,
} from "../support/timeline-fixtures";

const statuses = (events: AskEvent[]) =>
  Object.fromEntries(Object.values(buildTimeline(events).nodes).map((n) => [n.name, n.status]));

describe("timelineReducer", () => {
  it("starts idle with every graph node pending", () => {
    expect(initialTimeline.phase).toBe("idle");
    expect(Object.keys(initialTimeline.nodes)).toEqual([
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
    ]);
    expect(Object.values(initialTimeline.nodes).every((n) => n.status === "pending")).toBe(true);
    expect(initialTimeline.lit).toEqual([]);
  });

  it("is pure: it never mutates the state it is given", () => {
    const frozen = structuredClone(initialTimeline);
    const next = timelineReducer(initialTimeline, ANSWERED_RUN[0]!);
    expect(initialTimeline).toEqual(frozen);
    expect(next).not.toBe(initialTimeline);
    expect(next.nodes.classify.status).toBe("active");
  });

  it("lights the contract's answered run up in graph order", () => {
    const state = buildTimeline(ANSWERED_RUN);
    expect(state.lit).toEqual([
      "classify",
      "cache",
      "plan",
      "subagent",
      "merge",
      "draft",
      "verify",
      "respond",
    ]);
    expect(state.phase).toBe("done");
    expect(state.cache).toBe("miss");
    expect(state.nodes.cache.status).toBe("done");
    expect(state.nodes.respond.status).toBe("done");
    // Nodes the run never reached are skipped, not left pending.
    expect(state.nodes.re_retrieve.status).toBe("skipped");
    expect(state.nodes.review.status).toBe("skipped");
    expect(state.claims).toEqual([
      expect.objectContaining({ idx: 0, verified: true, reason: null }),
    ]);
    expect(state.answer?.status).toBe("answered");
  });

  it("marks a node active on started and records its timing and detail", () => {
    const state = buildTimeline(ANSWERED_RUN.slice(0, 4));
    expect(state.nodes.classify).toMatchObject({ status: "done", tMs: 2.1, runs: 1 });
    expect(state.nodes.classify.detail).toMatchObject({ source: "request" });
    expect(state.nodes.plan.status).toBe("active");
    expect(state.phase).toBe("running");
  });

  describe("fan-out", () => {
    it("expands one branch per planned sub-question as soon as the plan completes", () => {
      const planned = buildTimeline(FAN_OUT_RUN.slice(0, 5));
      expect(planned.branches.map((b) => [b.branch, b.status, b.question])).toEqual([
        [0, "pending", "How often should ALT be checked?"],
        [1, "pending", "What is the maximum daily dose?"],
        [2, "pending", "Which patients need a lower dose?"],
      ]);
    });

    it("runs the branches in parallel and finishes them out of order", () => {
      const state = buildTimeline(FAN_OUT_RUN);
      expect(state.branches.map((b) => b.status)).toEqual(["done", "done", "active"]);
      expect(state.branches[1]).toMatchObject({ retrieved: 30, kept: 6, reranked: true });
      // The subagent node stays active until every branch is back.
      expect(state.nodes.subagent.status).toBe("active");
      expect(state.nodes.subagent.runs).toBe(3);
    });

    it("completes the subagent node once every branch is done", () => {
      const state = buildTimeline(FAN_OUT_MERGED);
      expect(state.branches.map((b) => b.status)).toEqual(["done", "done", "done"]);
      expect(state.branches[2]).toMatchObject({ kept: 3, reranked: false });
      expect(state.nodes.subagent.status).toBe("done");
      expect(state.nodes.merge).toMatchObject({ status: "done", detail: { evidence: 17 } });
      expect(state.lit.indexOf("subagent")).toBeLessThan(state.lit.indexOf("merge"));
    });
  });

  describe("re-retrieve loop", () => {
    it("counts the iterations and re-runs draft and verify", () => {
      const state = buildTimeline(RE_RETRIEVE_RUN);
      expect(state.iteration).toBe(1);
      expect(state.nodes.re_retrieve).toMatchObject({ status: "done", runs: 1 });
      expect(state.nodes.draft).toMatchObject({ status: "done", runs: 2 });
      expect(state.nodes.verify).toMatchObject({ status: "active", runs: 2 });
      expect(state.lit).toEqual([
        "classify",
        "cache",
        "plan",
        "subagent",
        "merge",
        "draft",
        "verify",
        "re_retrieve",
      ]);
    });

    it("resets the claims for each verify pass and flips them as they are checked", () => {
      const first = buildTimeline(RE_RETRIEVE_RUN.slice(0, -6));
      expect(first.claims.map((c) => c.verified)).toEqual([true, false]);
      expect(first.claims[1]?.reason).toBe("quote_not_found");

      // The second verify pass starts with both claims unchecked, then flips claim 0.
      const second = buildTimeline(RE_RETRIEVE_RUN);
      expect(second.claims.map((c) => c.verified)).toEqual([true, null]);

      const done = buildTimeline(RE_RETRIEVE_DONE);
      expect(done.claims.map((c) => c.verified)).toEqual([true, true]);
      expect(done.phase).toBe("done");
      expect(done.iteration).toBe(1);
    });

    it("reports a draft repair as a retry without counting a new run", () => {
      const repair: AskEvent = {
        type: "step",
        node: "draft",
        status: "retry",
        t_ms: 2000,
        detail: { attempt: 0, reason: "repair" },
      };
      const state = buildTimeline([...RE_RETRIEVE_RUN.slice(0, 9), repair]);
      expect(state.nodes.draft).toMatchObject({ status: "active", runs: 1, retrying: true });
    });
  });

  it("records a failed node and a terminal error", () => {
    const state = buildTimeline(ERROR_RUN);
    expect(state.nodes.draft.status).toBe("failed");
    expect(state.nodes.draft.detail).toMatchObject({ error: "malformed_draft" });
    expect(state.phase).toBe("failed");
    expect(state.error).toMatchObject({ code: "internal", retryable: false });
    expect(state.nodes.verify.status).toBe("pending");
  });

  it("keeps running after a retryable error, failing only the nodes that were active", () => {
    const state = buildTimeline([
      ...ANSWERED_RUN.slice(0, 4),
      { type: "error", code: "internal", message: "Boom", retryable: true },
    ]);
    expect(state.phase).toBe("running");
    expect(state.nodes.plan.status).toBe("failed");
    expect(state.error?.retryable).toBe(true);

    // The redelivered job runs the node again.
    const resumed = timelineReducer(state, ANSWERED_RUN[3]!);
    expect(resumed.nodes.plan.status).toBe("active");
    expect(resumed.error).toBeNull();
  });

  it("pauses at the review node while it waits for a reviewer", () => {
    const state = buildTimeline(REVIEW_WAITING_RUN);
    expect(state.phase).toBe("waiting");
    expect(state.nodes.review.status).toBe("waiting");
    expect(state.nodes.review.detail).toMatchObject({ reason: "low_confidence" });
    expect(state.lit.at(-1)).toBe("review");
    expect(state.nodes.respond.status).toBe("done");
  });

  it("goes straight from a cache hit to respond, skipping the rest of the graph", () => {
    expect(statuses(CACHE_HIT_RUN)).toEqual({
      classify: "done",
      cache: "done",
      plan: "skipped",
      subagent: "skipped",
      merge: "skipped",
      draft: "skipped",
      verify: "skipped",
      re_retrieve: "skipped",
      respond: "done",
      review: "skipped",
    });
    const state = buildTimeline(CACHE_HIT_RUN);
    expect(state.cache).toBe("hit");
    expect(state.answer?.cached).toBe(true);
    expect(state.lit).toEqual(["classify", "cache", "respond"]);
  });

  it("marks a cache that is not configured as skipped", () => {
    const state = buildTimeline([
      { type: "step", node: "cache", status: "skipped", t_ms: 3, detail: {} },
    ]);
    expect(state.nodes.cache.status).toBe("skipped");
    expect(state.cache).toBe("skipped");
    expect(state.lit).toEqual([]);
  });

  it("ignores token events and nodes it does not know", () => {
    const state = buildTimeline([
      { type: "token", text: "ALT" },
      { type: "step", node: "judge", status: "started", t_ms: 1, detail: {} },
    ]);
    expect(state).toEqual(initialTimeline);
  });
});

describe("summarizeTimeline", () => {
  it("is empty before anything happens", () => {
    expect(summarizeTimeline(initialTimeline)).toBe("");
  });

  it("names the running step and the parallel branch progress", () => {
    expect(summarizeTimeline(buildTimeline(FAN_OUT_RUN))).toBe(
      "Searching sources: 2 of 3 searches done.",
    );
  });

  it("counts the claims checked in a verify pass, with the re-retrieve iteration", () => {
    expect(summarizeTimeline(buildTimeline(RE_RETRIEVE_RUN))).toBe(
      "Verifying claims (pass 2): 1 of 2 claims checked.",
    );
  });

  it("summarises each outcome", () => {
    expect(summarizeTimeline(buildTimeline(ANSWERED_RUN))).toBe("Done: 1 of 1 claims verified.");
    expect(summarizeTimeline(buildTimeline(CACHE_HIT_RUN))).toBe("Done: served from the cache.");
    expect(summarizeTimeline(buildTimeline(INSUFFICIENT_RUN))).toBe(
      "Done: not enough evidence to answer; 2 nearest sources found.",
    );
    expect(summarizeTimeline(buildTimeline(REVIEW_WAITING_RUN))).toBe(
      "Paused: waiting for human review.",
    );
    expect(summarizeTimeline(buildTimeline(ERROR_RUN))).toBe("Stopped: Drafting failed (internal).");
  });
});
