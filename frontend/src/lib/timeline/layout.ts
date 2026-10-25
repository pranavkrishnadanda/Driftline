/**
 * Pure layout for the version timeline: where each version sits on a horizontal axis
 * of `width` units, proportional to its `valid_from`.
 */
import type { TimelineVersion } from "@/lib/api/client";

export interface TimelineItem {
  versionId: string;
  versionNo: number;
  validFrom: Date;
  /** null: the version in force now. */
  validTo: Date | null;
  /** Where the version starts on the axis. */
  x: number;
  /** Where it ends: the next version's start, its own `valid_to`, or the right edge. */
  x2: number;
  openEnded: boolean;
}

export interface TimelineLayout {
  width: number;
  start: Date;
  end: Date;
  items: TimelineItem[];
}

export interface LayoutOptions {
  /** "Now", which the open-ended current version runs to. Defaults to the current time. */
  now?: Date;
  /** The smallest distance between two version starts, so same-day versions stay apart. */
  minGap?: number;
}

const DAY_MS = 86_400_000;

export function layoutTimeline(
  versions: readonly TimelineVersion[],
  width: number,
  options: LayoutOptions = {},
): TimelineLayout {
  const now = options.now ?? new Date();
  const minGap = options.minGap ?? 16;
  const sorted = [...versions]
    .map((v) => ({
      v,
      from: new Date(v.valid_from),
      to: v.valid_to === null ? null : new Date(v.valid_to),
    }))
    .sort((a, b) => a.from.getTime() - b.from.getTime() || a.v.version_no - b.v.version_no);

  if (sorted.length === 0) return { width, start: now, end: now, items: [] };

  const first = sorted[0];
  const last = sorted[sorted.length - 1];
  const t0 = first.from.getTime();
  const lastEnd = last.to === null ? now.getTime() : last.to.getTime();
  let t1 = Math.max(lastEnd, last.from.getTime());
  if (t1 <= t0) t1 = t0 + DAY_MS;
  const scale = (t: number) => ((t - t0) / (t1 - t0)) * width;

  const n = sorted.length;
  let xs = sorted.map((s) => scale(s.from.getTime()));
  if (n * minGap > width) {
    // Too many versions to keep minGap apart: spread them evenly instead.
    xs = sorted.map((_, i) => (i * width) / n);
  } else {
    for (let i = 1; i < n; i++) xs[i] = Math.max(xs[i], xs[i - 1] + minGap);
    xs[n - 1] = Math.min(xs[n - 1], width - minGap);
    for (let i = n - 2; i >= 0; i--) xs[i] = Math.min(xs[i], xs[i + 1] - minGap);
    xs[0] = Math.max(0, xs[0]);
  }

  const items = sorted.map((s, i): TimelineItem => {
    const openEnded = s.to === null;
    let x2: number;
    if (i < n - 1) x2 = xs[i + 1];
    else if (openEnded) x2 = width;
    else x2 = Math.min(width, Math.max(scale(s.to!.getTime()), xs[i] + Math.min(minGap, width - xs[i])));
    return {
      versionId: s.v.version_id,
      versionNo: s.v.version_no,
      validFrom: s.from,
      validTo: s.to,
      x: xs[i],
      x2,
      openEnded,
    };
  });

  return { width, start: new Date(t0), end: new Date(t1), items };
}

/** The index of the version whose segment holds `x` (clamped to the axis). */
export function nearestVersionIndex(layout: TimelineLayout, x: number): number {
  const { items } = layout;
  if (items.length === 0) return -1;
  let index = 0;
  for (let i = 0; i < items.length; i++) {
    if (items[i].x <= x) index = i;
    else break;
  }
  return index;
}
