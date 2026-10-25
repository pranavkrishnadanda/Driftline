"use client";

import { ChevronRight, FileText } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useState } from "react";

import { TenantSelect } from "@/components/ask/ask-controls";
import { Button } from "@/components/ui/button";
import { SectionHeading } from "@/components/section-heading";
import { createApiClient, type ApiClient } from "@/lib/api/client";
import { formatDay } from "@/lib/timeline/format";
import { recentDocuments, timelineHref, type RecentDocument } from "@/lib/timeline/recent";

type Recent =
  | { kind: "loading" }
  | { kind: "loaded"; documents: RecentDocument[] }
  | { kind: "failed"; message: string };

export interface DocumentPickerProps {
  tenants: string[];
  initialTenant?: string;
  /** A pasted id the /timeline page rejected. */
  invalidId?: string;
  /** Defaults to a client for NEXT_PUBLIC_DRIFTLINE_API. */
  client?: ApiClient;
}

const RECENT_LIMIT = 200;

/**
 * The Timeline entry point. The gateway has no route that lists documents, so it offers
 * the documents recent drift events touched, plus a form to paste any document id.
 */
export function DocumentPicker({
  tenants,
  initialTenant,
  invalidId,
  client: clientProp,
}: DocumentPickerProps) {
  const [client] = useState(() => clientProp ?? createApiClient());
  const options =
    initialTenant && !tenants.includes(initialTenant) ? [initialTenant, ...tenants] : tenants;
  const [tenant, setTenant] = useState(initialTenant ?? options[0] ?? "demo");
  const [recent, setRecent] = useState<Recent>({ kind: "loading" });
  const inputId = useId();
  const errorId = useId();

  useEffect(() => {
    const controller = new AbortController();
    client.driftEvents({ tenant, limit: RECENT_LIMIT }, { signal: controller.signal }).then(
      (list) => setRecent({ kind: "loaded", documents: recentDocuments(list.events) }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setRecent({
          kind: "failed",
          message: error instanceof Error ? error.message : String(error),
        });
      },
    );
    return () => controller.abort();
  }, [client, tenant]);

  return (
    <section className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-4 py-10">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-2">
          <SectionHeading>Timeline</SectionHeading>
          <p className="text-muted-foreground">
            See every version of a document, what changed between them, and which documents replace
            or amend it.
          </p>
        </div>
        {options.length > 1 ? (
          <TenantSelect
            tenants={options}
            value={tenant}
            onChange={(next) => {
              setRecent({ kind: "loading" });
              setTenant(next);
            }}
          />
        ) : null}
      </header>

      <div className="flex flex-col gap-3">
        <h2 className="font-heading text-lg font-semibold">Recently changed documents</h2>
        {recent.kind === "loading" ? (
          <p role="status" className="text-sm text-muted-foreground">
            Loading recent documents…
          </p>
        ) : recent.kind === "failed" ? (
          <p role="alert" className="text-sm text-muted-foreground">
            Couldn&apos;t load recent documents: {recent.message}
          </p>
        ) : recent.documents.length === 0 ? (
          <p className="rounded-xl border border-dashed p-6 text-sm text-muted-foreground">
            No documents have changed yet in this workspace. Open one by its ID below.
          </p>
        ) : (
          <ul aria-label="Recently drifted documents" className="flex flex-col gap-2">
            {recent.documents.map((doc) => (
              <li key={doc.documentId}>
                <Link
                  href={timelineHref(doc.documentId, tenant)}
                  className="group flex items-center gap-3 rounded-xl border border-border bg-card px-4 py-3 shadow-xs transition-colors hover:border-brand/40 hover:bg-brand-soft/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <FileText aria-hidden="true" className="size-5 shrink-0 text-brand" />
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate font-medium">
                      {doc.title?.trim() || "Untitled document"}
                    </span>
                    <span className="text-xs text-muted-foreground tabular-nums">
                      Last changed {formatDay(doc.lastDriftAt)} · {doc.events}{" "}
                      {doc.events === 1 ? "change" : "changes"}
                    </span>
                  </span>
                  <ChevronRight
                    aria-hidden="true"
                    className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 motion-reduce:transition-none"
                  />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>

      <form
        aria-label="Open a document"
        action="/timeline"
        method="get"
        className="flex flex-col gap-2 rounded-xl border border-dashed p-4"
      >
        <label htmlFor={inputId} className="text-sm font-medium">
          Document id
        </label>
        <p className="-mt-1 text-xs text-muted-foreground">
          Have a document&apos;s ID from an API response or a link? Paste it here.
        </p>
        <div className="flex gap-2">
          <input
            id={inputId}
            name="document"
            type="text"
            required
            autoComplete="off"
            spellCheck={false}
            defaultValue={invalidId}
            placeholder="Paste a document ID"
            aria-invalid={invalidId ? true : undefined}
            aria-describedby={invalidId ? errorId : undefined}
            className="h-9 min-w-0 flex-1 rounded-lg border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring aria-invalid:border-destructive"
          />
          <input type="hidden" name="tenant" value={tenant} />
          <Button type="submit" size="lg">
            Open timeline
          </Button>
        </div>
        {invalidId ? (
          <p id={errorId} className="text-sm text-destructive">
            “{invalidId}” doesn&apos;t look like a document ID. IDs look like
            0b6f7e52-6a49-4d0e-9a3c-2f5d1c7e8a10.
          </p>
        ) : null}
      </form>
    </section>
  );
}
