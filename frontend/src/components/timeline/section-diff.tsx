import { useId } from "react";

import type { TimelineVersion } from "@/lib/api/client";
import { diffToRows, type DiffRow, type SectionStatus } from "@/lib/timeline/diff";
import { formatDay } from "@/lib/timeline/format";
import { cn } from "@/lib/utils";

const STATUS_STYLE: Record<SectionStatus, string> = {
  added: "bg-emerald-500/10 text-emerald-900 dark:text-emerald-200",
  removed: "bg-red-500/10 text-red-900 dark:text-red-200",
  changed: "bg-amber-500/10 text-amber-950 dark:text-amber-200",
  unchanged: "text-muted-foreground",
};

function Cell({ row, present }: { row: DiffRow; present: boolean }) {
  if (!present) {
    return (
      <td className="border-t border-border px-3 py-2 align-top text-muted-foreground">
        <span aria-hidden="true">—</span>
        <span className="sr-only">not present</span>
      </td>
    );
  }
  return (
    <td className={cn("border-t border-border px-3 py-2 align-top", STATUS_STYLE[row.status])}>
      <span className="font-mono text-[13px]">{row.path}</span>{" "}
      <span className="ml-1 rounded-sm border border-current/20 px-1 text-[11px] uppercase tracking-wide">
        {row.status}
      </span>
    </td>
  );
}

export interface SectionDiffProps {
  version: TimelineVersion;
  previous: TimelineVersion | null;
}

/**
 * Side-by-side section diff of a version against its predecessor, from `diff_from_prev`.
 * The gateway records which sections were added, removed or changed (by section path),
 * not their text, so each side lists section paths.
 */
export function SectionDiff({ version, previous }: SectionDiffProps) {
  const headingId = useId();
  const diff = diffToRows(previous ? version.diff_from_prev : null);
  const { counts } = diff;

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <h2 id={headingId} className="font-heading text-lg font-semibold">
        {previous
          ? `Changes in v${version.version_no} since v${previous.version_no}`
          : `v${version.version_no} is the first version`}
      </h2>
      {diff.first ? (
        <p className="text-sm text-muted-foreground">
          Nothing to compare against: this version has no predecessor.
        </p>
      ) : (
        <>
          <p className="text-sm text-muted-foreground tabular-nums">
            {counts.added} added · {counts.changed} changed · {counts.removed} removed ·{" "}
            {counts.unchanged} unchanged
          </p>
          {diff.adjusted ? (
            <p className="text-sm text-muted-foreground">
              Its start was moved from {formatDay(diff.adjusted.requested)} to{" "}
              {formatDay(diff.adjusted.applied)} to keep validity windows in order.
            </p>
          ) : null}
          {diff.rows.length ? (
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full table-fixed border-collapse text-sm">
                <caption className="sr-only">
                  Sections of v{previous?.version_no} beside sections of v{version.version_no}
                </caption>
                <thead>
                  <tr className="bg-muted/50 text-left">
                    <th scope="col" className="px-3 py-2 font-medium">
                      v{previous?.version_no} (before)
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      v{version.version_no} (after)
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {diff.rows.map((row) => (
                    <tr key={row.path}>
                      <Cell row={row} present={row.before} />
                      <Cell row={row} present={row.after} />
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No section-level changes were recorded.</p>
          )}
        </>
      )}
    </section>
  );
}
