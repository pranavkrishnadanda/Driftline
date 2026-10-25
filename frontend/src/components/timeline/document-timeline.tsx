"use client";

import { useMemo, useState } from "react";

import { SectionDiff } from "@/components/timeline/section-diff";
import { SupersessionGraph } from "@/components/timeline/supersession-graph";
import { AXIS_WIDTH, VersionAxis } from "@/components/timeline/version-axis";
import { usePrefersReducedMotion } from "@/hooks/use-prefers-reduced-motion";
import type { DocumentTimeline as Timeline } from "@/lib/api/client";
import { formatWindow } from "@/lib/timeline/format";
import { layoutTimeline } from "@/lib/timeline/layout";
import { cn } from "@/lib/utils";

export interface DocumentTimelineProps {
  timeline: Timeline;
  tenant: string;
  /** "Now" for the open-ended current version; defaults to the time of first render. */
  now?: Date;
  /** Overrides the `prefers-reduced-motion` media query. */
  reducedMotion?: boolean;
}

export function DocumentTimeline({ timeline, tenant, now, reducedMotion }: DocumentTimelineProps) {
  const prefersReduced = usePrefersReducedMotion();
  const staticMotion = reducedMotion ?? prefersReduced;
  const [renderedAt] = useState(() => now ?? new Date());
  const layout = useMemo(
    () => layoutTimeline(timeline.versions, AXIS_WIDTH, { now: now ?? renderedAt }),
    [timeline.versions, now, renderedAt],
  );
  const byId = useMemo(
    () => new Map(timeline.versions.map((v) => [v.version_id, v])),
    [timeline.versions],
  );
  const [selected, setSelected] = useState(() => Math.max(0, layout.items.length - 1));

  const item = layout.items[selected];
  const version = item ? byId.get(item.versionId) : undefined;
  const prevItem = selected > 0 ? layout.items[selected - 1] : undefined;
  const previous = prevItem ? (byId.get(prevItem.versionId) ?? null) : null;
  const count = timeline.versions.length;

  return (
    <article className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-4 py-8">
      <header className="flex flex-col gap-1">
        <h1 className="font-heading text-2xl font-semibold tracking-tight">
          {timeline.title?.trim() || timeline.external_id}
        </h1>
        <p className="text-sm text-muted-foreground">
          <span className="font-mono">{timeline.external_id}</span> · {count}{" "}
          {count === 1 ? "version" : "versions"}
        </p>
      </header>

      {count === 0 ? (
        <p className="text-sm text-muted-foreground">This document has no versions yet.</p>
      ) : (
        <section aria-label="Version timeline" className="flex flex-col gap-4">
          <VersionAxis
            layout={layout}
            selectedIndex={selected}
            onSelect={setSelected}
            reducedMotion={staticMotion}
          />
          <ol aria-label="Versions" className="flex flex-wrap gap-2">
            {layout.items.map((it, i) => (
              <li key={it.versionId}>
                <button
                  type="button"
                  aria-pressed={i === selected}
                  onClick={() => setSelected(i)}
                  className={cn(
                    "flex flex-col items-start rounded-md border px-3 py-1.5 text-left text-xs",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                    i === selected
                      ? "border-primary bg-primary/10 text-foreground"
                      : "border-border text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  <span className="text-sm font-semibold text-foreground">v{it.versionNo}</span>
                  <span className="tabular-nums">{formatWindow(it)}</span>
                  {it.openEnded ? <span>in force now</span> : null}
                </button>
              </li>
            ))}
          </ol>
        </section>
      )}

      {version ? <SectionDiff version={version} previous={previous} /> : null}

      <SupersessionGraph timeline={timeline} tenant={tenant} reducedMotion={staticMotion} />
    </article>
  );
}
