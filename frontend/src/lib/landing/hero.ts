/**
 * The landing hero's illustrative document: three versions of one guideline, where v2
 * rewrites a section and v3 adds one. Pure data and geometry; the anime.js choreography
 * in `components/landing/drift-hero.tsx` reads it.
 */

export interface HeroVersion {
  label: string;
  /** ISO date the version came into force. */
  validFrom: string;
  /** How many sections the version has. */
  sections: number;
  /** The section this version rewrote, if any. */
  changed: number | null;
}

export const HERO_VERSIONS: readonly HeroVersion[] = [
  { label: "v1", validFrom: "2024-01-15", sections: 4, changed: null },
  { label: "v2", validFrom: "2024-06-01", sections: 4, changed: 2 },
  { label: "v3", validFrom: "2025-02-10", sections: 5, changed: null },
];

/** Section widths as a fraction of the page's text column. */
const BASE_WIDTHS = [0.92, 0.78, 0.86, 0.64, 0.72, 0.8];
/** A rewritten section reads differently: shorter here. */
const CHANGED_SCALE = 0.62;

export type LineState = "same" | "changed" | "added";

export interface DocumentLine {
  width: number;
  state: LineState;
}

/** `count` x positions spread evenly from `inset` to `width - inset` (centred if one). */
export function versionStops(count: number, { width, inset }: { width: number; inset: number }): number[] {
  if (count <= 0) return [];
  if (count === 1) return [width / 2];
  const step = (width - 2 * inset) / (count - 1);
  return Array.from({ length: count }, (_, i) => inset + i * step);
}

/**
 * The sections of version `index`: what each looks like, and whether it is unchanged
 * since v1, was rewritten by some version up to `index`, or was added after v1.
 */
export function documentLines(versions: readonly HeroVersion[], index: number): DocumentLine[] {
  if (!Number.isInteger(index) || index < 0 || index >= versions.length) {
    throw new RangeError(`no version at index ${index}`);
  }
  const first = versions[0].sections;
  const changed = new Set<number>();
  for (const v of versions.slice(0, index + 1)) if (v.changed !== null) changed.add(v.changed);

  return Array.from({ length: versions[index].sections }, (_, i) => {
    const base = BASE_WIDTHS[i % BASE_WIDTHS.length];
    if (i >= first) return { width: base, state: "added" };
    if (changed.has(i)) return { width: base * CHANGED_SCALE, state: "changed" };
    return { width: base, state: "same" };
  });
}

/** A version as a split-flap line: `V2 AS OF 2024-06-01`. */
export function asOfBoard(version: Pick<HeroVersion, "label" | "validFrom">): string {
  return `${version.label} as of ${version.validFrom}`.toUpperCase();
}
