import { useId } from "react";

import type { TimelineVersion } from "@/lib/api/client";
import { diffToRows, type DiffRow, type SectionStatus } from "@/lib/timeline/diff";
import { formatSection } from "@/lib/ask/format";
import { formatDay } from "@/lib/timeline/format";
import { cn } from "@/lib/utils";

const STATUS_STYLE: Record<SectionStatus, string> = {
  added: "bg-valid-soft/60",
  removed: "bg-broken-soft/60",
  changed: "bg-changed-soft/60",
  unchanged: "",
};

const STATUS_BADGE: Record<SectionStatus, { label: string; style: string }> = {
  added: { label: "Added", style: "bg-valid-soft text-valid" },
  removed: { label: "Removed", style: "bg-broken-soft text-broken" },
  changed: { label: "Changed", style: "bg-changed-soft text-changed" },
  unchanged: { label: "No change", style: "border border-border text-muted-foreground" },
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
      <span className={row.status === "unchanged" ? "text-muted-foreground" : "font-medium"}>
        {formatSection(row.path) ?? row.path}
      </span>{" "}
      <span
        className={cn(
          "ml-1 inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium",
          STATUS_BADGE[row.status].style,
        )}
      >
        {STATUS_BADGE[row.status].label}
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
            {[
              counts.added ? `${counts.added} added` : null,
              counts.changed ? `${counts.changed} changed` : null,
              counts.removed ? `${counts.removed} removed` : null,
              counts.unchanged ? `${counts.unchanged} unchanged` : null,
            ]
              .filter(Boolean)
              .join(" · ") || "No sections recorded"}
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
