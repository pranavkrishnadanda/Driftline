"use client";

import { CircleCheck, CircleX } from "lucide-react";
import { useId } from "react";

import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  citationNumbers,
  describeCitation,
  formatDate,
  formatValidity,
  stepLabel,
} from "@/lib/ask/format";
// The SSE contract's types: the job-status (OpenAPI) answer is assignable to them.
import type { AnswerSchema, Citation, Claim, NearestSource, StepEvent } from "@/lib/sse/events";
import { cn } from "@/lib/utils";

const bubble = "rounded-2xl border border-border bg-card px-5 py-4 text-card-foreground";

/** The answer while it streams: the tokens so far and what the agent is doing. */
export function StreamingAnswer({ text, step }: { text: string; step: StepEvent | null }) {
  return (
    <section aria-label="Answer in progress" aria-busy="true" className={bubble}>
      <p className="mb-2 text-xs font-medium text-muted-foreground">
        {step ? `${stepLabel(step.node)}…` : "Waiting for the agent…"}
      </p>
      {text ? (
        <p className="whitespace-pre-wrap leading-relaxed">{text}</p>
      ) : (
        <p className="text-sm text-muted-foreground">The answer appears here as it is written.</p>
      )}
    </section>
  );
}

function CitationChip({ citation, number }: { citation: Citation; number: number }) {
  const details = describeCitation(citation);
  const descriptionId = useId();
  const meta = [details.title ?? "Source", details.section, details.version, details.validity]
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
            className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-md border border-border bg-muted px-1 align-baseline text-[11px] font-medium tabular-nums text-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
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
    <li className="flex gap-2 text-sm leading-relaxed">
      <Icon
        role="img"
        aria-label={verified ? "Verified" : "Not verified"}
        className={cn("mt-0.5 size-4 shrink-0", verified ? "text-emerald-600" : "text-destructive")}
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
        {!verified && claim.reason ? (
          <span className="block text-xs text-muted-foreground">{claim.reason}</span>
        ) : null}
      </span>
    </li>
  );
}

function SourceList({ sources }: { sources: NearestSource[] }) {
  if (sources.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No nearby sources were found for this question and date.
      </p>
    );
  }
  return (
    <ul aria-label="Nearest sources" className="flex flex-col gap-2">
      {sources.map((source) => (
        <li key={source.version_id} className="rounded-lg border border-border px-3 py-2 text-sm">
          <span className="font-medium">{source.title}</span>{" "}
          <span className="text-muted-foreground">v{source.version_no}</span>
          {source.section_path ? (
            <span className="block text-xs text-muted-foreground">{source.section_path}</span>
          ) : null}
          <span className="block text-xs text-muted-foreground">
            {formatValidity(source.valid_from, source.valid_to)}
          </span>
        </li>
      ))}
    </ul>
  );
}

function AnswerMeta({ answer }: { answer: AnswerSchema }) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <span>As of {formatDate(answer.as_of)}</span>
      {answer.status === "answered" ? (
        <span>· Confidence {Math.round(answer.confidence * 100)}%</span>
      ) : null}
      {answer.degraded ? (
        <Badge variant="destructive" title="Answered with a fallback model or without reranking">
          Degraded
        </Badge>
      ) : null}
      {answer.cached ? (
        <Badge variant="secondary" title="Served from the answer cache">
          Cached
        </Badge>
      ) : null}
    </div>
  );
}

/** A finished answer: claims with citations, or an explicit refusal with nearest sources. */
export function FinalAnswer({ answer }: { answer: AnswerSchema }) {
  if (answer.status !== "answered") {
    const refused = answer.status === "refused";
    return (
      <section aria-label="Answer" className={cn(bubble, "border-amber-500/40")}>
        <AnswerMeta answer={answer} />
        <h2 className="mb-1 font-heading text-base font-semibold">
          {refused ? "Driftline declined to answer" : "Not enough evidence to answer"}
        </h2>
        <p className="mb-3 text-sm leading-relaxed">
          {answer.answer ||
            `Driftline didn't find evidence in force on ${formatDate(answer.as_of)} that answers this question, so it won't guess.`}
        </p>
        <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Nearest sources
        </h3>
        <SourceList sources={answer.nearest_sources ?? []} />
      </section>
    );
  }

  const claims = answer.claims ?? [];
  const numbers = citationNumbers(claims);
  return (
    <section aria-label="Answer" className={bubble}>
      <AnswerMeta answer={answer} />
      <p className="whitespace-pre-wrap leading-relaxed">
        {answer.answer || "The agent returned an empty answer."}
      </p>
      {claims.length ? (
        <>
          <h3 className="mt-4 mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Claims
          </h3>
          <ul aria-label="Claims" className="flex flex-col gap-2">
            {claims.map((claim) => (
              <ClaimItem key={claim.idx} claim={claim} numbers={numbers} />
            ))}
          </ul>
        </>
      ) : null}
      {answer.dropped_claims?.length ? (
        <p className="mt-3 text-xs text-muted-foreground">
          {answer.dropped_claims.length} unsupported claim
          {answer.dropped_claims.length === 1 ? " was" : "s were"} dropped.
        </p>
      ) : null}
    </section>
  );
}
