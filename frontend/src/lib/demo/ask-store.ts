/**
 * Shared state of the demo's Ask view, outside React: which recorded ask the last
 * question was matched to (set by the demo client), and suggestion picks (a recorded
 * question with its as-of date) that the demo prompt and as-of picker carry out.
 */
import type { AskMatch } from "./match";

export interface AskedMatch extends AskMatch {
  /** The question and as-of date that were actually asked. */
  asked: { question: string; as_of: string | null };
}

export interface SuggestionPick {
  question: string;
  as_of: string | null;
}

let lastMatch: AskedMatch | null = null;
const matchListeners = new Set<() => void>();
const pickListeners = new Set<(pick: SuggestionPick) => void>();

export function getLastMatch(): AskedMatch | null {
  return lastMatch;
}

export function setLastMatch(match: AskedMatch | null): void {
  lastMatch = match;
  for (const listener of matchListeners) listener();
}

export function subscribeMatch(listener: () => void): () => void {
  matchListeners.add(listener);
  return () => matchListeners.delete(listener);
}

/** Ask a recorded question at its recorded as-of date. */
export function pickSuggestion(pick: SuggestionPick): void {
  for (const listener of pickListeners) listener(pick);
}

export function subscribePicks(listener: (pick: SuggestionPick) => void): () => void {
  pickListeners.add(listener);
  return () => pickListeners.delete(listener);
}
