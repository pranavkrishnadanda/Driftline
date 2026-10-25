"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { FinalAnswer, StreamingAnswer } from "@/components/ask/answer";
import { AsOfPicker, TenantSelect } from "@/components/ask/ask-controls";
import AI_Prompt from "@/components/kokonutui/ai-prompt";
import { Button } from "@/components/ui/button";
import { TooltipProvider } from "@/components/ui/tooltip";
import { createApiClient, type ApiClient, type AskRequest } from "@/lib/api/client";
import {
  classifyAskFailure,
  formatCountdown,
  resolveEventsUrl,
  toAsOfParam,
  type AskFailure,
} from "@/lib/ask/format";
import { useCountdown } from "@/lib/ask/useCountdown";
import type { AnswerSchema, StepEvent } from "@/lib/sse/events";
import { useEventStream, type UseEventStreamOptions } from "@/lib/sse/useEventStream";

type Phase =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "streaming"; eventsUrl: string; jobId: string }
  | { kind: "stopped" }
  | { kind: "failed"; failure: AskFailure; start: number; until: number };

/** The outcome of fetching a job's status after its event stream expired. */
interface Recovery {
  jobId: string;
  answer: AnswerSchema | null;
  failure: AskFailure | null;
}

export interface AskViewProps {
  tenants: string[];
  /** Defaults to a client for NEXT_PUBLIC_DRIFTLINE_API. */
  client?: ApiClient;
  streamOptions?: UseEventStreamOptions;
}

const STREAMING = new Set(["idle", "connecting", "open", "reconnecting"]);

export function AskView({ tenants, client: clientProp, streamOptions }: AskViewProps) {
  const [client] = useState(() => clientProp ?? createApiClient());
  const [tenant, setTenant] = useState(tenants[0] ?? "demo");
  const [asOf, setAsOf] = useState<Date | null>(null);
  const [request, setRequest] = useState<AskRequest | null>(null);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [recovery, setRecovery] = useState<Recovery | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const streaming = phase.kind === "streaming" ? phase : null;
  const stream = useEventStream(streaming?.eventsUrl ?? null, streamOptions);
  const jobId = streaming?.jobId ?? null;

  useEffect(() => () => abortRef.current?.abort(), []);

  /** POST the ask, then hand its events URL to the stream. Never rejects. */
  const run = useCallback(
    async (body: AskRequest) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setRequest(body);
      setRecovery(null);
      setPhase({ kind: "submitting" });
      try {
        const accepted = await client.ask(body, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setPhase({
          kind: "streaming",
          eventsUrl: resolveEventsUrl(accepted.events_url, client.baseUrl),
          jobId: accepted.job_id,
        });
      } catch (error) {
        const failure = classifyAskFailure(error);
        if (!failure || controller.signal.aborted) return;
        const start = Date.now();
        const wait = failure.kind === "rate_limited" ? failure.retryAfter * 1000 : 0;
        setPhase({ kind: "failed", failure, start, until: start + wait });
      }
    },
    [client],
  );

  // An expired stream no longer has the events: read the outcome from the job instead.
  const expired = stream.status === "expired";
  useEffect(() => {
    if (!expired || jobId === null) return;
    const controller = new AbortController();
    client.job(jobId, { signal: controller.signal }).then(
      (job) =>
        setRecovery({
          jobId,
          answer: job.answer ?? null,
          failure: job.answer
            ? null
            : { kind: "error", message: `The answer stream expired and the job is ${job.status}.` },
        }),
      (error: unknown) => {
        const failure = classifyAskFailure(error);
        if (failure) setRecovery({ jobId, answer: null, failure });
      },
    );
    return () => controller.abort();
  }, [expired, jobId, client]);

  const submit = (question: string) => {
    const body: AskRequest = { question, tenant };
    const asOfParam = toAsOfParam(asOf);
    if (asOfParam) body.as_of = asOfParam;
    void run(body);
  };

  const retry = () => {
    if (request) void run(request);
  };

  const stop = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setPhase({ kind: "stopped" });
  };

  const rateLimit =
    phase.kind === "failed" && phase.failure.kind === "rate_limited"
      ? { start: phase.start, until: phase.until }
      : null;
  const waitSeconds = useCountdown(rateLimit);

  // What to show, derived from the phase and the stream.
  const recovered = recovery && recovery.jobId === jobId ? recovery : null;
  const answer: AnswerSchema | null = streaming
    ? (stream.final?.answer ?? recovered?.answer ?? null)
    : null;
  const responding =
    phase.kind === "submitting" || (streaming !== null && STREAMING.has(stream.status));
  let failure: AskFailure | null = phase.kind === "failed" ? phase.failure : null;
  if (streaming && stream.status === "failed") {
    failure = {
      kind: "backend_down",
      message: `The answer stream failed (${stream.error?.code ?? "unknown error"}).`,
    };
  }
  if (streaming && recovered?.failure) failure = recovered.failure;

  const lastStep =
    (stream.events.filter((e): e is StepEvent => e.type === "step").at(-1) as StepEvent | undefined) ??
    null;

  let announcement = "";
  if (responding) announcement = "Answering…";
  else if (answer) announcement = "Answer ready.";

  return (
    <TooltipProvider>
      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4 px-4 py-8">
        <header>
          <h1 className="font-heading text-2xl font-semibold tracking-tight">Ask</h1>
          <p className="text-sm text-muted-foreground">
            Answers come only from the document versions in force on the as-of date, with the
            exact quotes they rest on.
          </p>
        </header>

        <p role="status" className="sr-only">
          {announcement}
        </p>

        {request && phase.kind !== "idle" ? (
          <p className="max-w-[85%] self-end rounded-2xl bg-primary px-4 py-2 text-primary-foreground">
            {request.question}
          </p>
        ) : null}

        {answer ? (
          <FinalAnswer answer={answer} />
        ) : responding ? (
          <StreamingAnswer text={stream.text} step={lastStep} />
        ) : null}

        {phase.kind === "stopped" ? (
          <p className="text-sm text-muted-foreground">Stopped. Ask again when you are ready.</p>
        ) : null}

        {failure ? (
          <FailureNotice failure={failure} waitSeconds={waitSeconds} onRetry={retry} />
        ) : null}

        <AI_Prompt
          className="mt-auto"
          placeholder="Ask about your documents, as of any date"
          responding={responding}
          disabled={waitSeconds > 0}
          onSubmit={submit}
          onStop={stop}
          toolbar={
            <>
              <TenantSelect tenants={tenants} value={tenant} onChange={setTenant} />
              <AsOfPicker value={asOf} onChange={setAsOf} />
            </>
          }
        />
      </div>
    </TooltipProvider>
  );
}

function FailureNotice({
  failure,
  waitSeconds,
  onRetry,
}: {
  failure: AskFailure;
  waitSeconds: number;
  onRetry: () => void;
}) {
  if (failure.kind === "rate_limited") {
    const waiting = waitSeconds > 0;
    return (
      <div role="alert" className="rounded-2xl border border-amber-500/40 px-5 py-4 text-sm">
        <p className="font-medium">Driftline is busy right now.</p>
        <p className="mb-3 text-muted-foreground">
          The gateway asked to wait before the next question. Retry in{" "}
          <span className="tabular-nums">{formatCountdown(waitSeconds)}</span>.
        </p>
        <Button size="sm" variant="outline" disabled={waiting} onClick={onRetry}>
          {waiting ? `Retry in ${formatCountdown(waitSeconds)}` : "Retry now"}
        </Button>
      </div>
    );
  }
  return (
    <div role="alert" className="rounded-2xl border border-destructive/40 px-5 py-4 text-sm">
      <p className="mb-3 font-medium">{failure.message}</p>
      {failure.kind === "backend_down" ? (
        <Button size="sm" variant="outline" onClick={onRetry}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}
