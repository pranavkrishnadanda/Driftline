"use client";

import Link from "next/link";
import { useId, useState } from "react";

import { TextDiff } from "@/components/drift/text-diff";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import type { ApiClient, DriftVerdict } from "@/lib/api/client";
import type { DriftAlert } from "@/lib/drift/inbox";
import { describeApiFailure } from "@/lib/api/failure";
import { cn } from "@/lib/utils";

const VERDICTS: Record<
  DriftVerdict,
  { label: string; variant: "destructive" | "secondary" | "outline" }
> = {
  broken: { label: "Broken", variant: "destructive" },
  changed: { label: "Changed", variant: "secondary" },
  still_valid: { label: "Still valid", variant: "outline" },
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
  const verdict = VERDICTS[alert.verdict];

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
        alert.verdict === "broken" && "border-destructive/40",
      )}
    >
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h2 id={headingId} className="font-heading text-base font-semibold">
            {alert.documentTitle ?? "Untitled document"}
          </h2>
          <p className="text-xs text-muted-foreground">
            <time dateTime={alert.at}>{formatTime(alert.at)}</time>
            {alert.sectionPath ? <> · {alert.sectionPath}</> : null}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          {alert.live ? <Badge variant="outline">New</Badge> : null}
          <Badge variant={verdict.variant}>{verdict.label}</Badge>
        </div>
      </header>

      <TextDiff before={alert.before} after={alert.after} />

      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          size="sm"
          aria-expanded={open}
          aria-controls={detailsId}
          onClick={() => setOpen((o) => !o)}
        >
          Open answer
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
          <dt className="text-muted-foreground">Answer</dt>
          <dd className="font-mono text-xs break-all">{alert.answerId}</dd>
          {alert.claimIdx !== null ? (
            <>
              <dt className="text-muted-foreground">Claim</dt>
              <dd>#{alert.claimIdx + 1}</dd>
            </>
          ) : null}
          {alert.sectionPath ? (
            <>
              <dt className="text-muted-foreground">Section</dt>
              <dd>{alert.sectionPath}</dd>
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
