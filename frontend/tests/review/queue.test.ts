import { describe, expect, it } from "vitest";

import {
  INITIAL_QUEUE,
  RELATION_KINDS,
  describeItem,
  editBody,
  groupByKind,
  queueReducer,
  type QueueState,
} from "@/lib/review/queue";

import {
  BROKEN,
  LEGACY_ANSWER,
  LOW_CONFIDENCE,
  RELATION,
  reviewItem,
} from "../support/drift-fixtures";

const loaded = (items = [LOW_CONFIDENCE, BROKEN, RELATION]): QueueState =>
  queueReducer(INITIAL_QUEUE, { type: "load", items });

describe("groupByKind", () => {
  it("groups items by kind in a fixed order, skipping empty kinds", () => {
    const groups = groupByKind([RELATION, LEGACY_ANSWER, BROKEN, LOW_CONFIDENCE]);
    expect(groups.map((g) => [g.kind, g.items.map((i) => i.id)])).toEqual([
      ["low_confidence_answer", [LOW_CONFIDENCE.id]],
      ["broken_answer", [BROKEN.id]],
      ["relation", [RELATION.id]],
      ["answer", [LEGACY_ANSWER.id]],
    ]);
    expect(groups.map((g) => g.label)).toEqual([
      "Low-confidence answers",
      "Broken answers",
      "Suggested document links",
      "Regenerated answers",
    ]);
    expect(groupByKind([])).toEqual([]);
  });
});

describe("describeItem", () => {
  it("shows a low-confidence answer's question and draft, editable as text", () => {
    const view = describeItem(LOW_CONFIDENCE);
    expect(view.title).toBe("What is the maximum daily dose?");
    expect(view.body).toBe("The maximum daily dose is 40 mg.");
    expect(view.facts).toContainEqual({ label: "Confidence", value: "Low (42%)" });
    expect(view.status).toMatchObject({ tone: "changed", label: "Needs a second look" });
    expect(view.edit).toEqual({ field: "answer", initial: "The maximum daily dose is 40 mg." });
  });

  it("shows a broken answer's affected claims", () => {
    const view = describeItem(BROKEN);
    expect(view.title).toBe("A watched answer no longer matches its source");
    expect(view.body).toBe("Take 10 mg twice daily.");
    expect(view.status).toMatchObject({
      tone: "broken",
      label: "Broken: the cited text was removed",
    });
    expect(view.edit).toEqual({ field: "answer", initial: "" });
  });

  it("shows a proposed relation, editable as one of the relation kinds", () => {
    const view = describeItem(RELATION);
    expect(view.title).toBe("Amends SOP-12");
    expect(view.body).toBe("This revision amends SOP-12.");
    expect(view.facts).toContainEqual({ label: "Confidence", value: "Medium (61%)" });
    expect(view.status.next).toContain("Driftline thinks this document amends SOP-12.");
    expect(view.edit).toEqual({ field: "kind", initial: "amends", options: RELATION_KINDS });
  });

  it("describes a malformed extraction, which cannot be edited", () => {
    const view = describeItem(
      reviewItem({
        id: "m1",
        kind: "relation",
        payload: { error: "malformed_extraction", detail: "bad JSON", raw: "{" },
      }),
    );
    expect(view.title).toBe("Couldn't read a document link");
    expect(view.body).toBe("bad JSON");
    expect(view.edit).toBeNull();
  });

  it("never throws on an unexpected payload", () => {
    const view = describeItem(
      reviewItem({ id: "x", kind: "low_confidence_answer", payload: { answer: 3 } }),
    );
    expect(view.title).toBe("Low-confidence answer");
    expect(view.body).toBeNull();
  });
});

describe("editBody", () => {
  it("shapes the edit the gateway expects for each kind", () => {
    expect(editBody(LOW_CONFIDENCE, "  40 mg  ")).toEqual({ answer: "40 mg" });
    expect(editBody(RELATION, "supersedes")).toEqual({ kind: "supersedes" });
  });
});

describe("queueReducer", () => {
  it("loads items", () => {
    expect(loaded().items.map((i) => i.id)).toEqual([LOW_CONFIDENCE.id, BROKEN.id, RELATION.id]);
  });

  it("removes an item optimistically and puts it back in place on rollback", () => {
    let state = queueReducer(loaded(), { type: "resolving", id: BROKEN.id });
    expect(state.items.map((i) => i.id)).toEqual([LOW_CONFIDENCE.id, RELATION.id]);

    state = queueReducer(state, { type: "rollback", id: BROKEN.id });
    expect(state.items.map((i) => i.id)).toEqual([LOW_CONFIDENCE.id, BROKEN.id, RELATION.id]);
    expect(state.pending).toEqual({});
  });

  it("forgets the item once the resolve is confirmed", () => {
    let state = queueReducer(loaded(), { type: "resolving", id: RELATION.id });
    state = queueReducer(state, { type: "resolved", id: RELATION.id });
    expect(state.pending).toEqual({});
    expect(queueReducer(state, { type: "rollback", id: RELATION.id })).toBe(state);
  });

  it("keeps a resolving item hidden when a refresh still lists it", () => {
    let state = queueReducer(loaded(), { type: "resolving", id: BROKEN.id });
    state = queueReducer(state, { type: "load", items: [LOW_CONFIDENCE, BROKEN, RELATION] });
    expect(state.items.map((i) => i.id)).toEqual([LOW_CONFIDENCE.id, RELATION.id]);
  });

  it("ignores unknown ids", () => {
    const state = loaded();
    expect(queueReducer(state, { type: "resolving", id: "nope" })).toBe(state);
  });
});
