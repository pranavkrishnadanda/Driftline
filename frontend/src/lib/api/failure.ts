import { ApiError } from "@/lib/api/client";

/** A short, human sentence for a failed gateway call (drift inbox and review queue). */
export function describeApiFailure(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return "The Driftline API is unreachable.";
    if (error.status === 429 || error.status === 503) {
      return error.retryAfter !== null
        ? `The Driftline API is busy; try again in ${error.retryAfter}s.`
        : "The Driftline API is busy; try again shortly.";
    }
    return `The Driftline API returned ${error.status}${error.code ? ` (${error.code})` : ""}.`;
  }
  return "Something went wrong.";
}

export function isAbort(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}
