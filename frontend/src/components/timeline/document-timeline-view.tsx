"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { DocumentTimeline } from "@/components/timeline/document-timeline";
import { Button } from "@/components/ui/button";
import {
  ApiError,
  createApiClient,
  type ApiClient,
  type DocumentTimeline as Timeline,
} from "@/lib/api/client";

type State =
  | { kind: "loading" }
  | { kind: "loaded"; timeline: Timeline }
  | { kind: "failed"; error: unknown };

export interface DocumentTimelineViewProps {
  documentId: string;
  tenant: string;
  /** Defaults to a client for NEXT_PUBLIC_DRIFTLINE_API. */
  client?: ApiClient;
  now?: Date;
  reducedMotion?: boolean;
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Loads `GET /v1/documents/{id}/timeline` and renders it. */
export function DocumentTimelineView({
  documentId,
  tenant,
  client: clientProp,
  now,
  reducedMotion,
}: DocumentTimelineViewProps) {
  const [client] = useState(() => clientProp ?? createApiClient());
  const [state, setState] = useState<State>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    client.timeline(documentId, tenant, { signal: controller.signal }).then(
      (timeline) => setState({ kind: "loaded", timeline }),
      (error: unknown) => {
        if (!controller.signal.aborted) setState({ kind: "failed", error });
      },
    );
    return () => controller.abort();
  }, [client, documentId, tenant, attempt]);

  if (state.kind === "loading") {
    return (
      <p role="status" className="mx-auto w-full max-w-6xl px-4 py-8 text-sm text-muted-foreground">
        Loading timeline…
      </p>
    );
  }

  if (state.kind === "failed") {
    const notFound = state.error instanceof ApiError && state.error.status === 404;
    return (
      <div className="mx-auto w-full max-w-6xl px-4 py-8">
        <div
          role="alert"
          className="flex flex-col items-start gap-3 rounded-md border border-border p-4"
        >
          {notFound ? (
            <>
              <p className="font-medium">This document was not found in tenant {tenant}.</p>
              <Link
                href="/timeline"
                className="text-sm font-medium underline underline-offset-4 focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Choose another document
              </Link>
            </>
          ) : (
            <>
              <p className="font-medium">Couldn&apos;t load the timeline.</p>
              <p className="text-sm text-muted-foreground">{message(state.error)}</p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setState({ kind: "loading" });
                  setAttempt((n) => n + 1);
                }}
              >
                Retry
              </Button>
            </>
          )}
        </div>
      </div>
    );
  }

  return (
    <DocumentTimeline
      timeline={state.timeline}
      tenant={tenant}
      now={now}
      reducedMotion={reducedMotion}
    />
  );
}
