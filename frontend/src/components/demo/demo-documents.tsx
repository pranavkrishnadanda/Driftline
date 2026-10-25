"use client";

import { ChevronRight, FileText } from "lucide-react";
import Link from "next/link";

import { useDemoRecording } from "@/components/demo/demo-ask";
import { timelineHref } from "@/lib/timeline/recent";

/** Every document in the recording (the demo cannot open ids it did not record). */
export function DemoDocuments({ tenant }: { tenant: string }) {
  const recording = useDemoRecording();
  const timelines = recording ? Object.entries(recording.timelines) : [];
  if (timelines.length === 0) return null;
  return (
    <div className="flex flex-col gap-3">
      <h2 className="font-heading text-lg font-semibold">Every document in this recording</h2>
      <ul aria-label="Recorded documents" className="flex flex-col gap-2">
        {timelines.map(([id, timeline]) => (
          <li key={id}>
            <Link
              href={timelineHref(id, tenant)}
              className="group flex items-center gap-3 rounded-xl border border-border bg-card px-4 py-3 shadow-xs transition-colors hover:border-brand/40 hover:bg-brand-soft/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <FileText aria-hidden="true" className="size-5 shrink-0 text-brand" />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate font-medium">
                  {timeline.title?.trim() || "Untitled document"}
                </span>
                <span className="text-xs text-muted-foreground tabular-nums">
                  {timeline.versions.length}{" "}
                  {timeline.versions.length === 1 ? "version" : "versions"}
                </span>
              </span>
              <ChevronRight
                aria-hidden="true"
                className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 motion-reduce:transition-none"
              />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
