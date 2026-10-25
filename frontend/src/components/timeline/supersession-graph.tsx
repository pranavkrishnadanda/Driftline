"use client";

import {
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type EdgeTypes,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";
import Link from "next/link";
import { useId, useMemo } from "react";

import { DrawnEdgeView, StaticEdgesContext } from "@/components/timeline/drawn-edge";
import { useHasResizeObserver } from "@/hooks/use-prefers-reduced-motion";
import type { DocumentTimeline, TimelineRelation } from "@/lib/api/client";
import { buildSupersessionGraph, type DocNode } from "@/lib/timeline/graph";
import { timelineHref } from "@/lib/timeline/recent";
import { cn } from "@/lib/utils";

function DocNodeView({ data }: NodeProps<DocNode>) {
  const self = data.role === "self";
  return (
    <div
      className={cn(
        "max-w-48 rounded-md border px-3 py-2 text-xs shadow-sm",
        self
          ? "border-brand bg-brand text-brand-foreground"
          : "border-border bg-card text-card-foreground",
      )}
    >
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <span className="line-clamp-2 font-medium">{data.label}</span>
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </div>
  );
}

/** A relation's review status in plain words, coloured like the verdicts. */
const RELATION_STATUS: Record<string, { label: string; style: string }> = {
  accepted: { label: "Confirmed", style: "bg-valid-soft text-valid" },
  applied: { label: "Confirmed", style: "bg-valid-soft text-valid" },
  pending: { label: "Awaiting review", style: "bg-changed-soft text-changed" },
  rejected: { label: "Rejected", style: "bg-broken-soft text-broken" },
};

const nodeTypes: NodeTypes = { doc: DocNodeView };
const edgeTypes: EdgeTypes = { drawn: DrawnEdgeView };
const defaultEdgeOptions = { markerEnd: { type: MarkerType.ArrowClosed } };

function RelationList({
  label,
  relations,
  tenant,
  versionNo,
}: {
  label: string;
  relations: TimelineRelation[];
  tenant: string;
  /** For outgoing relations: this document's version number by version id. */
  versionNo?: Map<string, number>;
}) {
  return (
    <div className="flex flex-col gap-2">
      <h3 className="text-sm font-medium">{label}</h3>
      {relations.length ? (
        <ul aria-label={label} className="flex flex-col gap-1.5 text-sm">
          {relations.map((r) => {
            const no = versionNo?.get(r.src_version_id);
            return (
              <li key={r.id} className="flex flex-wrap items-baseline gap-x-2">
                <Link
                  href={timelineHref(r.document_id, tenant)}
                  className="font-medium underline underline-offset-4 focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {r.document_title?.trim() || "Untitled document"}
                </Link>
                <span>{r.kind}</span>
                <span
                  title={`${Math.round(r.confidence * 100)}% confidence`}
                  className={cn(
                    "rounded-full px-2 py-0.5 text-xs font-medium",
                    RELATION_STATUS[r.status]?.style ?? "bg-muted text-muted-foreground",
                  )}
                >
                  {RELATION_STATUS[r.status]?.label ?? r.status}
                </span>
                {no !== undefined ? (
                  <span className="text-xs text-muted-foreground">since v{no}</span>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">None.</p>
      )}
    </div>
  );
}

export interface SupersessionGraphProps {
  timeline: DocumentTimeline;
  tenant: string;
  reducedMotion: boolean;
}

/**
 * React Flow graph of the relations touching this document, with edges drawn by
 * anime.js, followed by the same relations as accessible lists.
 */
export function SupersessionGraph({ timeline, tenant, reducedMotion }: SupersessionGraphProps) {
  const headingId = useId();
  const canMeasure = useHasResizeObserver();
  const { nodes, edges } = useMemo(() => buildSupersessionGraph(timeline), [timeline]);
  const versionNo = useMemo(
    () => new Map(timeline.versions.map((v) => [v.version_id, v.version_no])),
    [timeline.versions],
  );
  const { incoming, outgoing } = timeline.relations;
  const empty = incoming.length === 0 && outgoing.length === 0;

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <h2 id={headingId} className="font-heading text-lg font-semibold">
        Related documents
      </h2>
      {empty ? (
        <p className="text-sm text-muted-foreground">No relations recorded for this document.</p>
      ) : (
        <>
          {/* React Flow needs ResizeObserver to measure nodes; without it the lists stand alone. */}
          {canMeasure ? (
            <div
              role="group"
              aria-label="Related documents graph"
              // On a phone the graph would shrink to unreadable; the lists below say the same.
              className="hidden h-72 w-full overflow-hidden rounded-md border border-border sm:block"
            >
              <StaticEdgesContext.Provider value={reducedMotion}>
                <ReactFlow
                  nodes={nodes}
                  edges={edges}
                  nodeTypes={nodeTypes}
                  edgeTypes={edgeTypes}
                  defaultEdgeOptions={defaultEdgeOptions}
                  fitView
                  fitViewOptions={{ padding: 0.2 }}
                  nodesDraggable={false}
                  nodesConnectable={false}
                  nodesFocusable={false}
                  edgesFocusable={false}
                  elementsSelectable={false}
                  zoomOnScroll={false}
                  preventScrolling={false}
                  minZoom={0.3}
                  maxZoom={1.5}
                />
              </StaticEdgesContext.Provider>
            </div>
          ) : null}
          <div className="grid gap-4 sm:grid-cols-2">
            <RelationList label="Documents that point here" relations={incoming} tenant={tenant} />
            <RelationList
              label="This document points to"
              relations={outgoing}
              tenant={tenant}
              versionNo={versionNo}
            />
          </div>
        </>
      )}
    </section>
  );
}
