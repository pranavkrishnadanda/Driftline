"use client";

import { CircleCheck, CircleX, FileText, Info, Loader2 } from "lucide-react";
import { useId } from "react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  citationNumbers,
  confidenceLevel,
  describeCitation,
  formatDate,
  formatSection,
  formatValidity,
  progressLine,
  type ConfidenceLevel,
} from "@/lib/ask/format";
// The SSE contract's types: the job-status (OpenAPI) answer is assignable to them.
import type { AnswerSchema, Citation, Claim, NearestSource, StepEvent } from "@/lib/sse/events";
import { cn } from "@/lib/utils";

const bubble = "rounded-2xl border border-border bg-card px-5 py-4 text-card-foreground shadow-xs";

/**
 * The answer while it streams: one friendly line about what is happening ("Searching the
 * documents in force on 1 Jun 2024…") and the words written so far.
 */
export function StreamingAnswer({
  text,
  step,
  asOf = null,
}: {
  text: string;
  step: StepEvent | null;
  /** The date being asked about; null for today. */
  asOf?: string | null;
}) {
  return (
    <section aria-label="Answer in progress" aria-busy="true" className={bubble}>
      <p className="mb-2 flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2
          aria-hidden="true"
          className="size-4 animate-spin text-brand motion-reduce:animate-none"
        />
        {progressLine(step?.node ?? null, asOf)}
      </p>
      {text ? (
        <p className="text-[15px] whitespace-pre-wrap leading-relaxed">{text}</p>
      ) : (
        <p className="text-sm text-muted-foreground">The answer appears here as it is written.</p>
      )}
    </section>
  );
}

/** Why the review node paused the ask (`step.detail.reason`), in words. */
const REVIEW_REASONS: Record<string, string> = {
  low_confidence: "The answer's confidence is below the review threshold.",
  watched_answer: "A watched answer was regenerated after its sources changed.",
};

/** The `step {node: "review", status: "waiting"}` event: the ask paused for a reviewer. */
export function isReviewWaiting(step: StepEvent | null | undefined): boolean {
  return step?.node === "review" && step.status === "waiting";
}

/**
 * The ask is paused for a human reviewer (job status `needs_review`). Not an error and
 * not busy: the answer arrives on the same stream once a reviewer resolves the item.
 */
export function ReviewPending({ text, step }: { text: string; step: StepEvent | null }) {
  const reason = step?.detail?.reason;
  const why = typeof reason === "string" ? (REVIEW_REASONS[reason] ?? null) : null;
  return (
    <section
      aria-label="Waiting for human review"
      className={cn(bubble, "border-changed/40 bg-changed-soft/40")}
    >
      <h2 className="mb-1 font-heading text-base font-semibold">Waiting for human review</h2>
      <p className="text-sm text-muted-foreground">
        {why ? `${why} ` : ""}A reviewer has to approve, edit or reject it before it is shown. The
        answer appears here once they do.
      </p>
      {text ? (
        <>
          <h3 className="mt-4 mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Draft under review
          </h3>
          <p className="whitespace-pre-wrap leading-relaxed text-muted-foreground">{text}</p>
        </>
      ) : null}
    </section>
  );
}

function CitationChip({ citation, number }: { citation: Citation; number: number }) {
  const details = describeCitation(citation);
  const descriptionId = useId();
  const meta = [details.title ?? "Source", details.version, details.section, details.validity]
    .filter(Boolean)
    .join(" · ");
  return (
    <Tooltip>
      {/* The popup only exists while open, so screen readers get the quote from here. */}
      <span id={descriptionId} className="sr-only">
        “{details.quote}” {meta}
      </span>
      <TooltipTrigger
        render={
          <button
            type="button"
            aria-label={`Citation ${number}: ${details.title ?? details.version}`}
            aria-describedby={descriptionId}
            className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-brand-soft px-1.5 align-baseline text-[11px] font-semibold tabular-nums text-brand hover:bg-brand hover:text-brand-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          />
        }
      >
        {number}
      </TooltipTrigger>
      <TooltipContent
        role="tooltip"
        className="max-w-sm flex-col items-start gap-1.5 px-3 py-2 text-left"
      >
        <blockquote className="text-sm leading-snug">“{details.quote}”</blockquote>
        <p className="text-[11px] opacity-80">{meta}</p>
      </TooltipContent>
    </Tooltip>
  );
}

function ClaimItem({ claim, numbers }: { claim: Claim; numbers: Map<string, number> }) {
  const verified = claim.verified !== false;
  const Icon = verified ? CircleCheck : CircleX;
  return (
    <li className="flex gap-2.5 text-sm leading-relaxed">
      <Icon
        aria-hidden="true"
        className={cn("mt-0.5 size-4 shrink-0", verified ? "text-valid" : "text-broken")}
      />
      <span>
        {claim.text}
        {claim.citations.map((citation) => (
          <CitationChip
            key={citation.chunk_id}
            citation={citation}
            number={numbers.get(citation.chunk_id) ?? 0}
          />
        ))}
        <span className={cn("block text-xs", verified ? "text-valid" : "text-broken")}>
          {verified ? "Verified against the source" : "Couldn't be verified against the source"}
          {!verified && claim.reason ? (
            <span className="text-muted-foreground"> · {claim.reason.replaceAll("_", " ")}</span>
          ) : null}
        </span>
      </span>
    </li>
  );
}

interface SourceCardData {
  key: string;
  number: number | null;
  title: string;
  version: string | null;
  section: string | null;
  validity: string | null;
  quote: string | null;
}

/** One card per cited passage: which document, which version, where, and when in force. */
function SourceCards({ label, sources }: { label: string; sources: SourceCardData[] }) {
  return (
    <ul aria-label={label} className="grid gap-2 sm:grid-cols-2">
      {sources.map((source) => (
        <li
          key={source.key}
          className="flex flex-col gap-1.5 rounded-xl border border-border bg-background p-3 text-sm"
        >
          <div className="flex items-start gap-2">
            {source.number !== null ? (
              <span className="mt-0.5 inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-brand-soft px-1.5 text-[11px] font-semibold tabular-nums text-brand">
                {source.number}
              </span>
            ) : (
              <FileText
                aria-hidden="true"
                className="mt-0.5 size-4 shrink-0 text-muted-foreground"
              />
            )}
            <span className="min-w-0 flex-1 font-medium leading-snug">{source.title}</span>
            {source.version ? (
              <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                {source.version}
              </span>
            ) : null}
          </div>
          {source.section ? (
            <span className="text-xs text-muted-foreground">{source.section}</span>
          ) : null}
          {source.quote ? (
            <blockquote className="line-clamp-3 border-l-2 border-brand/40 pl-2 text-xs leading-relaxed text-foreground/80">
              “{source.quote}”
            </blockquote>
          ) : null}
          {source.validity ? (
            <span className="text-xs text-muted-foreground">{source.validity}</span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function citedSources(claims: Claim[], numbers: Map<string, number>): SourceCardData[] {
  const seen = new Map<string, SourceCardData>();
  for (const claim of claims) {
    for (const citation of claim.citations) {
      if (seen.has(citation.chunk_id)) continue;
      const details = describeCitation(citation);
      seen.set(citation.chunk_id, {
        key: citation.chunk_id,
        number: numbers.get(citation.chunk_id) ?? null,
        title: details.title?.trim() || "Untitled document",
        version: details.version,
        section: details.section,
        validity: details.validity,
        quote: details.quote,
      });
    }
  }
  return [...seen.values()];
}

function nearestSources(sources: NearestSource[]): SourceCardData[] {
  return sources.map((source) => ({
    key: source.version_id,
    number: null,
    title: source.title?.trim() || "Untitled document",
    version: `v${source.version_no}`,
    section: formatSection(source.section_path),
    validity: formatValidity(source.valid_from, source.valid_to),
    quote: null,
  }));
}

const LEVEL_STYLE: Record<ConfidenceLevel, string> = {
  High: "bg-valid-soft text-valid",
  Medium: "bg-changed-soft text-changed",
  Low: "bg-broken-soft text-broken",
};

function ConfidenceBadge({ confidence }: { confidence: number }) {
  const { level, explanation } = confidenceLevel(confidence);
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <button
            type="button"
            aria-label={`${level} confidence. ${explanation}`}
            className={cn(
              "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              LEVEL_STYLE[level],
            )}
          />
        }
      >
        {level} confidence
        <Info aria-hidden="true" className="size-3 opacity-70" />
      </TooltipTrigger>
      <TooltipContent role="tooltip" className="max-w-64">
        {explanation}
      </TooltipContent>
    </Tooltip>
  );
}

function Pill({ title, children }: { title: string; children: string }) {
  return (
    <span
      title={title}
      className="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground"
    >
      {children}
    </span>
  );
}

function AnswerMeta({ answer }: { answer: AnswerSchema }) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <span>As of {formatDate(answer.as_of)}</span>
      {answer.status === "answered" ? <ConfidenceBadge confidence={answer.confidence} /> : null}
      {answer.degraded ? (
        <Pill title="Answered with a backup model or without reranking, so it may be less precise">
          Backup model
        </Pill>
      ) : null}
      {answer.cached ? (
        <Pill title="The same question was answered for this date before; this is that answer">
          Saved answer
        </Pill>
      ) : null}
    </div>
  );
}

/** A finished answer: the answer first, its claims, then the sources it rests on. */
export function FinalAnswer({ answer }: { answer: AnswerSchema }) {
  if (answer.status !== "answered") {
    const refused = answer.status === "refused";
    return (
      <section aria-label="Answer" className={cn(bubble, "border-changed/40")}>
        <AnswerMeta answer={answer} />
        <h2 className="mb-1 font-heading text-base font-semibold">
          {refused ? "Driftline declined to answer" : "Not enough evidence to answer"}
        </h2>
        <p className="mb-4 text-sm leading-relaxed">
          {answer.answer ||
            `Driftline didn't find evidence in force on ${formatDate(answer.as_of)} that answers this question, so it won't guess.`}
        </p>
        <h3 className="mb-2 text-sm font-semibold">Closest sources</h3>
        {answer.nearest_sources?.length ? (
          <SourceCards label="Nearest sources" sources={nearestSources(answer.nearest_sources)} />
        ) : (
          <p className="text-sm text-muted-foreground">
            No nearby sources were found for this question and date.
          </p>
        )}
      </section>
    );
  }

  const claims = answer.claims ?? [];
  const numbers = citationNumbers(claims);
  const sources = citedSources(claims, numbers);
  return (
    <section aria-label="Answer" className={bubble}>
      <AnswerMeta answer={answer} />
      <p className="text-base whitespace-pre-wrap leading-relaxed sm:text-[17px]">
        {answer.answer || "The agent returned an empty answer."}
      </p>
      {claims.length ? (
        <>
          <h3 className="mt-5 mb-2 text-sm font-semibold">What this answer is based on</h3>
          <ul aria-label="Claims" className="flex flex-col gap-2.5">
            {claims.map((claim) => (
              <ClaimItem key={claim.idx} claim={claim} numbers={numbers} />
            ))}
          </ul>
        </>
      ) : null}
      {answer.dropped_claims?.length ? (
        <p className="mt-3 text-xs text-muted-foreground">
          {answer.dropped_claims.length} statement
          {answer.dropped_claims.length === 1 ? " was" : "s were"} left out because the sources
          didn&apos;t support {answer.dropped_claims.length === 1 ? "it" : "them"}.
        </p>
      ) : null}
      {sources.length ? (
        <>
          <h3 className="mt-5 mb-2 text-sm font-semibold">Sources</h3>
          <SourceCards label="Sources" sources={sources} />
        </>
      ) : null}
    </section>
  );
}
