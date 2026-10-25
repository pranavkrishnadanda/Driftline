/**
 * Which recorded ask answers a question typed into the demo. The demo never invents an
 * answer: any question maps to the recorded one it shares the most words with, and the
 * UI says so when that is not the question that was typed.
 */
import type { RecordedAsk } from "./recording";

const STOP_WORDS = new Set(
  (
    "a an the of to is are was were be been what which who whom for in on and or does do " +
    "did it its as by with how at from that this these those when should can could would " +
    "i me my we our you your there their about into than then any"
  ).split(" "),
);

/** Lower-cased content words, with a crude plural fold ("labels" -> "label"). */
export function questionTokens(text: string): Set<string> {
  const words = text.toLowerCase().match(/[a-z0-9]+/g) ?? [];
  const out = new Set<string>();
  for (const word of words) {
    if (STOP_WORDS.has(word)) continue;
    out.add(
      word.length > 3 && word.endsWith("s") && !word.endsWith("ss") ? word.slice(0, -1) : word,
    );
  }
  return out;
}

/** Shared words over all words (Jaccard), 0 to 1. */
export function tokenOverlap(a: ReadonlySet<string>, b: ReadonlySet<string>): number {
  if (a.size === 0 && b.size === 0) return 0;
  let shared = 0;
  for (const word of a) if (b.has(word)) shared += 1;
  return shared / (a.size + b.size - shared);
}

/** The calendar day of an `as_of` (`YYYY-MM-DD`), or null for "today". */
export function asOfDay(asOf: string | null | undefined): string | null {
  return asOf ? asOf.slice(0, 10) : null;
}

function normalise(question: string): string {
  return question.trim().toLowerCase().replace(/\s+/g, " ");
}

export interface AskMatch {
  ask: RecordedAsk;
  index: number;
  /** The same question (ignoring case and spacing) on the same as-of day. */
  exact: boolean;
  /** Word overlap with the recorded question, 0 to 1. */
  score: number;
}

/**
 * The recorded ask closest to `question` on `asOf`: the most word overlap, then (among
 * recordings of that question) the nearest as-of date, then the earliest recorded.
 * `today` stands in for a missing `as_of` on either side. Null only with no recordings.
 */
export function matchAsk(
  question: string,
  asOf: string | null | undefined,
  asks: readonly RecordedAsk[],
  today: string,
): AskMatch | null {
  const wanted = questionTokens(question);
  const wantedDay = Date.parse(asOfDay(asOf) ?? today.slice(0, 10));
  let best: AskMatch | null = null;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (const [index, ask] of asks.entries()) {
    const score = tokenOverlap(wanted, questionTokens(ask.request.question));
    const day = Date.parse(asOfDay(ask.request.as_of) ?? today.slice(0, 10));
    const distance = Math.abs(day - wantedDay);
    const better =
      best === null ||
      score > best.score + 1e-9 ||
      (Math.abs(score - best.score) <= 1e-9 && distance < bestDistance);
    if (!better) continue;
    best = {
      ask,
      index,
      score,
      exact:
        normalise(question) === normalise(ask.request.question) &&
        asOfDay(asOf) === asOfDay(ask.request.as_of),
    };
    bestDistance = distance;
  }
  return best;
}
