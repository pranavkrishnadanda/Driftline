import { diffWords } from "@/lib/drift/diff";

/**
 * A cited section's text before and after a change, as one paragraph with removed words
 * struck through and added words highlighted. `<del>`/`<ins>` carry the meaning for
 * assistive tech, with a visually hidden prefix since most screen readers skip them.
 */
export function TextDiff({ before, after }: { before: string | null; after: string | null }) {
  const parts = diffWords(before, after);
  return (
    <div role="group" aria-label="Before and after" className="flex flex-col gap-1.5">
      {before === null ? (
        <p className="text-xs text-muted-foreground">This section is new in the latest version.</p>
      ) : null}
      {after === null ? (
        <p className="text-xs text-muted-foreground">
          This section was removed in the latest version.
        </p>
      ) : null}
      {parts.length ? (
        <p className="rounded-md bg-muted/50 p-3 text-sm leading-relaxed whitespace-pre-wrap">
          {parts.map((part, i) => {
            if (part.op === "delete") {
              return (
                <del
                  key={i}
                  className="rounded-sm bg-destructive/15 text-destructive decoration-destructive/70"
                >
                  <span className="sr-only">removed: </span>
                  {part.text}
                </del>
              );
            }
            if (part.op === "insert") {
              return (
                <ins
                  key={i}
                  className="rounded-sm bg-emerald-500/15 text-emerald-800 no-underline dark:text-emerald-300"
                >
                  <span className="sr-only">added: </span>
                  {part.text}
                </ins>
              );
            }
            return <span key={i}>{part.text}</span>;
          })}
        </p>
      ) : (
        <p className="text-sm text-muted-foreground">
          No section text was recorded for this change.
        </p>
      )}
    </div>
  );
}
