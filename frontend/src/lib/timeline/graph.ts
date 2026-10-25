/**
 * Pure supersession-graph builder: the document in the middle, the documents whose
 * versions declare a relation to it (incoming) on the left, and the documents its own
 * versions point at (outgoing) on the right. One edge per relation.
 */
import { Position, type Edge, type Node } from "@xyflow/react";

import type { DocumentTimeline, TimelineRelation } from "@/lib/api/client";

export type DocNodeData = {
  label: string;
  documentId: string;
  role: "self" | "incoming" | "outgoing";
};

export type DrawnEdgeData = {
  kind: string;
  status: string;
  confidence: number;
  /** Stagger position for the drawing animation. */
  order: number;
};

export type DocNode = Node<DocNodeData, "doc">;
export type DrawnEdge = Edge<DrawnEdgeData, "drawn">;

export const COLUMN_X = { incoming: 0, self: 320, outgoing: 640 } as const;
const ROW_GAP = 90;

/** A document's name for the graph; never a raw id. */
function shortLabel(title: string | null, _documentId: string): string {
  return title?.trim() || "Untitled document";
}

export function buildSupersessionGraph(timeline: DocumentTimeline): {
  nodes: DocNode[];
  edges: DrawnEdge[];
} {
  const versionNo = new Map(timeline.versions.map((v) => [v.version_id, v.version_no]));

  function side(relations: TimelineRelation[], role: "incoming" | "outgoing"): DocNode[] {
    const nodes = new Map<string, DocNode>();
    for (const r of relations) {
      const id = `${role === "incoming" ? "in" : "out"}:${r.document_id}`;
      if (nodes.has(id)) continue;
      nodes.set(id, {
        id,
        type: "doc",
        position: { x: COLUMN_X[role], y: 0 },
        data: {
          label: shortLabel(r.document_title, r.document_id),
          documentId: r.document_id,
          role,
        },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
      });
    }
    return [...nodes.values()];
  }

  const incoming = side(timeline.relations.incoming, "incoming");
  const outgoing = side(timeline.relations.outgoing, "outgoing");
  const rows = Math.max(incoming.length, outgoing.length, 1);
  const centre = ((rows - 1) * ROW_GAP) / 2;
  const stack = (nodes: DocNode[]) => {
    const offset = centre - ((nodes.length - 1) * ROW_GAP) / 2;
    nodes.forEach((n, i) => (n.position = { x: n.position.x, y: offset + i * ROW_GAP }));
  };
  stack(incoming);
  stack(outgoing);

  const self: DocNode = {
    id: "self",
    type: "doc",
    position: { x: COLUMN_X.self, y: centre },
    data: {
      label: shortLabel(timeline.title, timeline.document_id),
      documentId: timeline.document_id,
      role: "self",
    },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
  };

  let order = 0;
  const edge = (r: TimelineRelation, source: string, target: string, label: string): DrawnEdge => ({
    id: `rel:${r.id}`,
    source,
    target,
    type: "drawn",
    label,
    data: { kind: r.kind, status: r.status, confidence: r.confidence, order: order++ },
  });

  const edges = [
    ...timeline.relations.incoming.map((r) => edge(r, `in:${r.document_id}`, "self", r.kind)),
    ...timeline.relations.outgoing.map((r) => {
      const no = versionNo.get(r.src_version_id);
      return edge(
        r,
        "self",
        `out:${r.document_id}`,
        no === undefined ? r.kind : `${r.kind} · v${no}`,
      );
    }),
  ];

  return { nodes: [...incoming, self, ...outgoing], edges };
}
