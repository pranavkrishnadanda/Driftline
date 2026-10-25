"use client";

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
export function DocumentPicker({ tenants, initialTenant, invalidId, client: clientProp }: DocumentPickerProps) {
  const [client] = useState(() => clientProp ?? createApiClient());
  const options = initialTenant && !tenants.includes(initialTenant) ? [initialTenant, ...tenants] : tenants;
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
        setRecent({ kind: "failed", message: error instanceof Error ? error.message : String(error) });
      },
    );
    return () => controller.abort();
  }, [client, tenant]);

  return (
    <section className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-10">
      <header className="flex flex-col gap-2">
        <SectionHeading>Timeline</SectionHeading>
        <p className="text-muted-foreground">
          Every version of a document on a time axis, with section diffs and what superseded what.
        </p>
      </header>

      <div className="flex items-center gap-2">
        <span className="text-sm text-muted-foreground">Tenant</span>
        <TenantSelect
          tenants={options}
          value={tenant}
          onChange={(next) => {
            setRecent({ kind: "loading" });
            setTenant(next);
          }}
        />
      </div>

      <form
        aria-label="Open a document"
        action="/timeline"
        method="get"
        className="flex flex-col gap-2"
      >
        <label htmlFor={inputId} className="text-sm font-medium">
          Document id
        </label>
        <div className="flex gap-2">
          <input
            id={inputId}
            name="document"
            type="text"
            required
            autoComplete="off"
            spellCheck={false}
            defaultValue={invalidId}
            placeholder="0b6f7e52-6a49-4d0e-9a3c-2f5d1c7e8a10"
            aria-invalid={invalidId ? true : undefined}
            aria-describedby={invalidId ? errorId : undefined}
            className="h-9 min-w-0 flex-1 rounded-md border border-input bg-background px-3 font-mono text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring aria-invalid:border-destructive"
          />
          <input type="hidden" name="tenant" value={tenant} />
          <Button type="submit">Open timeline</Button>
        </div>
        {invalidId ? (
          <p id={errorId} className="text-sm text-destructive">
            “{invalidId}” is not a document id (expected a UUID).
          </p>
        ) : null}
      </form>

      <div className="flex flex-col gap-2">
        <h2 className="font-heading text-lg font-semibold">Recently drifted documents</h2>
        {recent.kind === "loading" ? (
          <p role="status" className="text-sm text-muted-foreground">
            Loading recent documents…
          </p>
        ) : recent.kind === "failed" ? (
          <p role="alert" className="text-sm text-muted-foreground">
            Couldn&apos;t load recent documents: {recent.message}
          </p>
        ) : recent.documents.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No drift events yet for tenant {tenant}. Paste a document id above to open its timeline.
          </p>
        ) : (
          <ul aria-label="Recently drifted documents" className="flex flex-col divide-y divide-border rounded-md border border-border">
            {recent.documents.map((doc) => (
              <li key={doc.documentId} className="flex flex-wrap items-baseline justify-between gap-2 px-3 py-2">
                <Link
                  href={timelineHref(doc.documentId, tenant)}
                  className="font-medium underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {doc.title?.trim() || doc.documentId}
                </Link>
                <span className="text-xs text-muted-foreground tabular-nums">
                  last drift {formatDay(doc.lastDriftAt)} · {doc.events}{" "}
                  {doc.events === 1 ? "event" : "events"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
