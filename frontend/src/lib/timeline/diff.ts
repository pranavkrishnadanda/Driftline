/**
 * Maps a version's `diff_from_prev` to the rows of a side-by-side section diff.
 *
 * The gateway stores a section-path classification (`driftline.ingest.hashing.diff_sections`):
 * `{added, removed, changed, unchanged}` lists of section paths, plus an optional
 * `valid_from_adjusted` note. It is null for the first version.
 */
import type { TimelineVersion } from "@/lib/api/client";

export type SectionStatus = "added" | "removed" | "changed" | "unchanged";

export interface DiffRow {
  path: string;
  status: SectionStatus;
  /** The section exists in the previous version (left column). */
  before: boolean;
  /** The section exists in this version (right column). */
  after: boolean;
}

export interface DiffRows {
  /** No predecessor: version 1 has nothing to compare against. */
  first: boolean;
  rows: DiffRow[];
  counts: Record<SectionStatus, number>;
  /** The store moved `valid_from` forward to keep validity windows ordered. */
  adjusted: { requested: string; applied: string } | null;
}

const STATUSES: SectionStatus[] = ["added", "removed", "changed", "unchanged"];

function paths(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((p): p is string => typeof p === "string") : [];
}

function adjustment(value: unknown): DiffRows["adjusted"] {
  if (!value || typeof value !== "object") return null;
  const { requested, applied } = value as { requested?: unknown; applied?: unknown };
  return typeof requested === "string" && typeof applied === "string" ? { requested, applied } : null;
}

export function diffToRows(diff: TimelineVersion["diff_from_prev"]): DiffRows {
  const counts: Record<SectionStatus, number> = { added: 0, removed: 0, changed: 0, unchanged: 0 };
  if (diff === null || diff === undefined) return { first: true, rows: [], counts, adjusted: null };

  const seen = new Map<string, SectionStatus>();
  for (const status of STATUSES) {
    for (const path of paths(diff[status])) if (!seen.has(path)) seen.set(path, status);
  }
  const rows = [...seen]
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([path, status]): DiffRow => {
      counts[status] += 1;
      return { path, status, before: status !== "added", after: status !== "removed" };
    });
  return { first: false, rows, counts, adjusted: adjustment(diff.valid_from_adjusted) };
}
