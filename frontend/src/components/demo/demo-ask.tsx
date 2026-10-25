"use client";

import { History, Info } from "lucide-react";
import { useEffect, useState, useSyncExternalStore } from "react";

import { formatDate } from "@/lib/ask/format";
import { getLastMatch, pickSuggestion, subscribeMatch } from "@/lib/demo/ask-store";
import { loadRecording, type DemoRecording } from "@/lib/demo/recording";

/** The recording, once loaded (null until then, or if it cannot be loaded). */
export function useDemoRecording(): DemoRecording | null {
  const [recording, setRecording] = useState<DemoRecording | null>(null);
  useEffect(() => {
    let live = true;
    loadRecording().then(
      (r) => {
        if (live) setRecording(r);
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, []);
  return recording;
}

/** `2024-06-01T00:00:00Z` as that calendar day at local midnight (the as-of picker's form). */
export function fromAsOfParam(asOf: string | null | undefined): Date | null {
  const m = asOf?.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
}

function asOfLabel(asOf: string | null | undefined): string | null {
  return asOf ? `as of ${formatDate(asOf)}` : null;
}

/**
 * Says when the answer shown is the recording of a different question (or date) than
 * the one asked. The demo never makes an answer up.
 */
export function DemoMatchNote() {
  const match = useSyncExternalStore(subscribeMatch, getLastMatch, () => null);
  if (!match || match.exact) return null;
  const date = asOfLabel(match.ask.request.as_of);
  return (
    <p
      role="note"
      data-testid="demo-match-note"
      className="flex items-start gap-2 rounded-xl border border-changed/40 bg-changed-soft px-3 py-2 text-sm"
    >
      <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-changed" />
      <span>
        Showing the recorded answer to the closest demo question: “{match.ask.request.question}”
        {date ? ` (${date})` : ""}
      </span>
    </p>
  );
}

/** The recorded questions, as one-click suggestions. */
export function DemoSuggestions({ disabled }: { disabled: boolean }) {
  const recording = useDemoRecording();
  if (!recording || recording.asks.length === 0) return null;
  return (
    <section aria-labelledby="demo-questions" className="flex flex-col gap-2">
      <h2
        id="demo-questions"
        className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground"
      >
        <History aria-hidden="true" className="size-3.5" />
        Recorded questions: pick one, or type your own
      </h2>
      <ul className="flex flex-wrap gap-2">
        {recording.asks.map((ask, i) => {
          const date = asOfLabel(ask.request.as_of);
          return (
            // A recording can repeat a question at another date; the list never reorders.
            <li key={i}>
              <button
                type="button"
                disabled={disabled}
                data-testid="demo-suggestion"
                onClick={() =>
                  pickSuggestion({
                    question: ask.request.question,
                    as_of: ask.request.as_of ?? null,
                  })
                }
                className="rounded-full border border-border bg-card px-3 py-1.5 text-left text-sm shadow-xs transition-colors hover:border-brand/40 hover:bg-brand-soft/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50"
              >
                {ask.request.question}
                {date ? <span className="ml-1 text-xs text-muted-foreground">{date}</span> : null}
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
