import { describe, expect, it } from "vitest";

import { buildSupersessionGraph } from "@/lib/timeline/graph";
import { recentDocuments } from "@/lib/timeline/recent";
import type { DriftEvent } from "@/lib/api/client";

import { DOC_ID, OLD_DOC_ID, OTHER_DOC_ID, TIMELINE } from "../support/version-timeline-fixtures";

describe("buildSupersessionGraph", () => {
  it("puts the document in the middle, incoming on the left and outgoing on the right", () => {
    const graph = buildSupersessionGraph(TIMELINE);
    const self = graph.nodes.find((n) => n.id === "self")!;
    const incoming = graph.nodes.find((n) => n.id === `in:${OTHER_DOC_ID}`)!;
    const outgoing = graph.nodes.find((n) => n.id === `out:${OLD_DOC_ID}`)!;

    expect(self.data).toMatchObject({ label: "Metformin label", documentId: DOC_ID, role: "self" });
    expect(incoming.position.x).toBeLessThan(self.position.x);
    expect(outgoing.position.x).toBeGreaterThan(self.position.x);
    // An untitled document says so, never a hash id.
    expect(incoming.data.label).toBe("Untitled document");
  });

  it("draws one edge per relation, pointing from declarer to target, labelled by kind", () => {
    const graph = buildSupersessionGraph(TIMELINE);
    expect(graph.edges.map((e) => [e.source, e.target, e.data?.kind, e.data?.order])).toEqual([
      [`in:${OTHER_DOC_ID}`, "self", "amends", 0],
      ["self", `out:${OLD_DOC_ID}`, "supersedes", 1],
    ]);
    expect(graph.edges[1].label).toBe("supersedes · v2");
    expect(graph.edges.every((e) => e.type === "drawn")).toBe(true);
  });

  it("keeps one node per related document even with several relations", () => {
    const graph = buildSupersessionGraph({
      ...TIMELINE,
      relations: {
        incoming: [],
        outgoing: [
          TIMELINE.relations.outgoing[0],
          {
            ...TIMELINE.relations.outgoing[0],
            id: "b0000000-0000-4000-8000-000000000009",
            kind: "amends",
          },
        ],
      },
    });
    expect(graph.nodes.map((n) => n.id)).toEqual(["self", `out:${OLD_DOC_ID}`]);
    expect(graph.edges).toHaveLength(2);
  });

  it("is just the document when nothing relates to it", () => {
    const graph = buildSupersessionGraph({
      ...TIMELINE,
      relations: { incoming: [], outgoing: [] },
    });
    expect(graph.nodes.map((n) => n.id)).toEqual(["self"]);
    expect(graph.edges).toEqual([]);
  });
});

function driftEvent(
  id: string,
  documentId: string | null,
  title: string | null,
  at: string,
): DriftEvent {
  return {
    id,
    answer_id: "c0000000-0000-4000-8000-000000000001",
    claim_idx: 0,
    verdict: "changed",
    old_version_id: null,
    new_version_id: null,
    document_id: documentId,
    document_title: title,
    created_at: at,
  };
}

describe("recentDocuments", () => {
  it("lists each drifted document once, most recent first", () => {
    const docs = recentDocuments([
      driftEvent("e1", DOC_ID, "Metformin label", "2026-02-03T00:00:00Z"),
      driftEvent("e2", OTHER_DOC_ID, null, "2026-02-02T00:00:00Z"),
      driftEvent("e3", DOC_ID, "Metformin label", "2026-02-01T00:00:00Z"),
      driftEvent("e4", null, null, "2026-01-01T00:00:00Z"),
    ]);
    expect(docs).toEqual([
      {
        documentId: DOC_ID,
        title: "Metformin label",
        lastDriftAt: "2026-02-03T00:00:00Z",
        events: 2,
      },
      { documentId: OTHER_DOC_ID, title: null, lastDriftAt: "2026-02-02T00:00:00Z", events: 1 },
    ]);
  });
});
