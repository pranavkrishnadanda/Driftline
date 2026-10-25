"use client";

import { AnimatePresence, MotionConfig, motion, useReducedMotion } from "motion/react";
import { useEffect, useReducer, useState } from "react";

import { TenantSelect } from "@/components/ask/ask-controls";
import { AlertCard } from "@/components/drift/alert-card";
import { Button } from "@/components/ui/button";
import { SectionHeading } from "@/components/section-heading";
import { createApiClient, type ApiClient } from "@/lib/api/client";
import { describeApiFailure, isAbort } from "@/lib/api/failure";
import { INITIAL_INBOX, alertStreamUrl, inboxReducer } from "@/lib/drift/inbox";
import type { AlertStreamEvent } from "@/lib/sse/events";
import {
  useEventStream,
  type EventStreamStatus,
  type UseEventStreamOptions,
} from "@/lib/sse/useEventStream";

/** How many past drift events to load; the gateway allows up to 500. */
const HISTORY_LIMIT = 100;

const STREAM_LABELS: Record<EventStreamStatus, string> = {
  idle: "Not connected",
  connecting: "Connecting…",
  open: "Live",
  reconnecting: "Reconnecting…",
  done: "Stream ended",
  expired: "Catching up…",
  failed: "Disconnected",
};

export interface DriftInboxProps {
  tenants: string[];
  /** Defaults to a client for NEXT_PUBLIC_DRIFTLINE_API. */
  client?: ApiClient;
  /** Origin of the alert stream; defaults to the client's gateway. */
  streamBaseUrl?: string;
  streamOptions?: UseEventStreamOptions;
}

export function DriftInbox({ tenants, client: clientProp, streamBaseUrl, streamOptions }: DriftInboxProps) {
  const [client] = useState(() => clientProp ?? createApiClient());
  const [tenant, setTenant] = useState(tenants[0] ?? "demo");

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4 px-4 py-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <SectionHeading>Drift</SectionHeading>
          <p className="text-sm text-muted-foreground">
            Watched answers re-checked against each new document version, as it lands.
          </p>
        </div>
        {tenants.length > 1 ? (
          <TenantSelect tenants={tenants} value={tenant} onChange={setTenant} />
        ) : null}
      </header>
      {/* A new tenant is a new inbox: fresh history, stream and state. */}
      <Inbox
        key={tenant}
        tenant={tenant}
        client={client}
        streamBaseUrl={streamBaseUrl ?? client.baseUrl}
        streamOptions={streamOptions}
      />
    </div>
  );
}

function Inbox({
  tenant,
  client,
  streamBaseUrl,
  streamOptions,
}: {
  tenant: string;
  client: ApiClient;
  streamBaseUrl: string;
  streamOptions?: UseEventStreamOptions;
}) {
  const [state, dispatch] = useReducer(inboxReducer, INITIAL_INBOX);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyAttempt, setHistoryAttempt] = useState(0);
  /** answer id -> its open `broken_answer` review item id. */
  const [reviewItems, setReviewItems] = useState<ReadonlyMap<string, string>>(new Map());
  const reduceMotion = useReducedMotion();

  const stream = useEventStream<AlertStreamEvent>(
    alertStreamUrl(streamBaseUrl, tenant, state.resync),
    streamOptions,
  );

  useEffect(() => {
    if (stream.events.length) dispatch({ type: "live", events: stream.events });
  }, [stream.events]);

  // The stream missed alerts that are no longer stored: reload history, follow the tail.
  useEffect(() => {
    if (stream.status === "expired") dispatch({ type: "expired" });
  }, [stream.status]);

  useEffect(() => {
    const controller = new AbortController();
    client.driftEvents({ tenant, limit: HISTORY_LIMIT }, { signal: controller.signal }).then(
      (list) => {
        setHistoryError(null);
        dispatch({ type: "history", events: list.events });
      },
      (error: unknown) => {
        if (!isAbort(error)) setHistoryError(describeApiFailure(error));
      },
    );
    return () => controller.abort();
  }, [client, tenant, state.resync, historyAttempt]);

  // Which answers have an open broken-answer item; a new broken verdict opens one.
  const brokenCount = state.alerts.filter((a) => a.verdict === "broken").length;
  useEffect(() => {
    const controller = new AbortController();
    client.review({ tenant, kind: "broken_answer" }, { signal: controller.signal }).then(
      (list) =>
        setReviewItems(
          new Map(
            list.items.filter((item) => item.status === "open").map((item) => [item.ref_id, item.id]),
          ),
        ),
      // Without the queue the inbox still works; it just cannot link to review items.
      () => undefined,
    );
    return () => controller.abort();
  }, [client, tenant, brokenCount]);

  const retryHistory = () => {
    setHistoryError(null);
    setHistoryAttempt((n) => n + 1);
  };

  const streamLabel = STREAM_LABELS[stream.status];
  const streamDown = stream.status === "failed";

  return (
    <MotionConfig reducedMotion="user">
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span
            aria-hidden="true"
            className={
              stream.status === "open"
                ? "size-2 rounded-full bg-emerald-500"
                : streamDown
                  ? "size-2 rounded-full bg-destructive"
                  : "size-2 rounded-full bg-muted-foreground"
            }
          />
          <p role="status" className="text-muted-foreground">
            {streamLabel}
          </p>
          {streamDown ? (
            <Button variant="outline" size="sm" onClick={() => dispatch({ type: "expired" })}>
              Reconnect
            </Button>
          ) : null}
        </div>

        {historyError ? (
          <div
            role="alert"
            className="flex flex-wrap items-center gap-3 rounded-lg border border-destructive/40 p-3 text-sm"
          >
            <p>Could not load drift history. {historyError}</p>
            <Button variant="outline" size="sm" onClick={retryHistory}>
              Retry
            </Button>
          </div>
        ) : null}

        {state.alerts.length === 0 && state.historyLoaded ? (
          <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
            No drift yet. Watch an answer and alerts appear here when a document it cites
            changes.
          </p>
        ) : null}

        <ol aria-label="Drift alerts" className="relative flex flex-col gap-3">
          <AnimatePresence initial={false}>
            {state.alerts.map((alert) => (
              <motion.li
                key={alert.id}
                layout={reduceMotion ? false : "position"}
                // Only alerts that arrive live make an entrance; history is already there.
                initial={alert.live && !reduceMotion ? { opacity: 0, y: -16, scale: 0.98 } : false}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={reduceMotion ? undefined : { opacity: 0 }}
                transition={{ type: "spring", duration: 0.45, bounce: 0.15 }}
              >
                <AlertCard
                  alert={alert}
                  tenant={tenant}
                  client={client}
                  reviewItemId={reviewItems.get(alert.answerId) ?? null}
                />
              </motion.li>
            ))}
          </AnimatePresence>
        </ol>
      </div>
    </MotionConfig>
  );
}
