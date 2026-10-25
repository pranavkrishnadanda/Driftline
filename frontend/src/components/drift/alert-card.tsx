"use client";

import Link from "next/link";
import { useId, useState } from "react";

import { TextDiff } from "@/components/drift/text-diff";
import { Badge } from "@/components/ui/badge";
import { VerdictBadge, VERDICT_COPY } from "@/components/verdict";
import { Button, buttonVariants } from "@/components/ui/button";
import type { ApiClient, DriftVerdict } from "@/lib/api/client";
import type { DriftAlert } from "@/lib/drift/inbox";
import { describeApiFailure } from "@/lib/api/failure";
import { formatSection } from "@/lib/ask/format";
import { cn } from "@/lib/utils";

const BORDER: Record<DriftVerdict, string> = {
  broken: "border-broken/40",
  changed: "border-changed/40",
  still_valid: "border-border",
};

const TIME_FORMAT = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "UTC",
  timeZoneName: "short",
});

function formatTime(iso: string): string {
  const at = Date.parse(iso);
  return Number.isNaN(at) ? iso : TIME_FORMAT.format(at);
}

export interface AlertCardProps {
  alert: DriftAlert;
  tenant: string;
  client: ApiClient;
  /** The open `broken_answer` review item for this alert's answer, if any. */
  reviewItemId: string | null;
}

type WatchState =
  | { kind: "watching" }
  | { kind: "pending"; next: boolean }
  | { kind: "unwatched" }
  | { kind: "failed"; message: string; watched: boolean };

export function AlertCard({ alert, tenant, client, reviewItemId }: AlertCardProps) {
  const headingId = useId();
  const detailsId = useId();
  const [open, setOpen] = useState(false);
  const [watch, setWatch] = useState<WatchState>({ kind: "watching" });
  const verdict = VERDICT_COPY[alert.verdict];
  const section = formatSection(alert.sectionPath);

  const watched =
    watch.kind === "watching" ||
    (watch.kind === "pending" && !watch.next) ||
    (watch.kind === "failed" && watch.watched);

  const toggleWatch = async () => {
    const next = !watched;
    setWatch({ kind: "pending", next });
    try {
      const state = next
        ? await client.watch(alert.answerId, tenant)
        : await client.unwatch(alert.answerId, tenant);
      setWatch(state.watched ? { kind: "watching" } : { kind: "unwatched" });
    } catch (error) {
      setWatch({ kind: "failed", message: describeApiFailure(error), watched });
    }
  };

  return (
    <article
      aria-labelledby={headingId}
      className={cn(
        "flex flex-col gap-3 rounded-xl border bg-card p-4 text-card-foreground shadow-xs",
        BORDER[alert.verdict],
      )}
    >
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h2 id={headingId} className="font-heading text-base font-semibold">
            {alert.documentTitle ?? "Untitled document"}
          </h2>
          <p className="text-xs text-muted-foreground">
            <time dateTime={alert.at}>{formatTime(alert.at)}</time>
            {section ? <> · {section}</> : null}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          {alert.live ? <Badge variant="outline">New</Badge> : null}
          <VerdictBadge verdict={alert.verdict} />
        </div>
      </header>

      <p className="text-sm text-muted-foreground">{verdict.next}</p>

      <TextDiff before={alert.before} after={alert.after} />

      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          size="sm"
          aria-expanded={open}
          aria-controls={detailsId}
          onClick={() => setOpen((o) => !o)}
        >
          Details
        </Button>
        {reviewItemId ? (
          <Link
            href={`/review?item=${encodeURIComponent(reviewItemId)}`}
            className={buttonVariants({ variant: "default", size: "sm" })}
          >
            Send to review
          </Link>
        ) : null}
      </div>

      <section
        id={detailsId}
        aria-label="Answer details"
        hidden={!open}
        className="flex flex-col gap-3 rounded-md border border-dashed p-3 text-sm"
      >
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          <dt className="text-muted-foreground">Answer ID</dt>
          <dd className="font-mono text-xs break-all">{alert.answerId}</dd>
          {alert.claimIdx !== null ? (
            <>
              <dt className="text-muted-foreground">Claim</dt>
              <dd>#{alert.claimIdx + 1}</dd>
            </>
          ) : null}
          {section ? (
            <>
              <dt className="text-muted-foreground">Section</dt>
              <dd>{section}</dd>
            </>
          ) : null}
          <dt className="text-muted-foreground">Old version</dt>
          <dd className="font-mono text-xs break-all">{alert.oldVersionId ?? "none"}</dd>
          <dt className="text-muted-foreground">New version</dt>
          <dd className="font-mono text-xs break-all">{alert.newVersionId ?? "none"}</dd>
        </dl>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            disabled={watch.kind === "pending"}
            onClick={() => void toggleWatch()}
          >
            {watched ? "Stop watching" : "Watch again"}
          </Button>
          {watch.kind === "failed" ? (
            <p role="alert" className="text-xs text-destructive">
              {watch.message}
            </p>
          ) : null}
        </div>
      </section>
    </article>
  );
}
