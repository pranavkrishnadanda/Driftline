"use client";

import { useEffect, useId, useReducer, useRef, useState } from "react";

import { TenantSelect } from "@/components/ask/ask-controls";
import { ReviewItemCard, type Resolution } from "@/components/review/review-item-card";
import { Button } from "@/components/ui/button";
import { ApiError, createApiClient, type ApiClient, type ReviewItem } from "@/lib/api/client";
import { describeApiFailure, isAbort } from "@/lib/api/failure";
import {
  INITIAL_QUEUE,
  describeItem,
  groupByKind,
  queueReducer,
  type ReviewGroup,
} from "@/lib/review/queue";

const DONE: Record<Resolution["action"], string> = {
  approve: "Approved",
  edit: "Edited",
  reject: "Rejected",
};

const DEFAULT_REVIEWER = process.env.NEXT_PUBLIC_DRIFTLINE_REVIEWER?.trim() || "driftline-web";

export interface ReviewQueueProps {
  tenants: string[];
  /** Defaults to a client for NEXT_PUBLIC_DRIFTLINE_API. */
  client?: ApiClient;
  /** Recorded as `resolved_by`; defaults to NEXT_PUBLIC_DRIFTLINE_REVIEWER. */
  reviewer?: string;
  /** An item to bring into view and focus once loaded (`/review?item=`). */
  focusItem?: string | null;
}

export function ReviewQueue({ tenants, client: clientProp, reviewer, focusItem }: ReviewQueueProps) {
  const [client] = useState(() => clientProp ?? createApiClient());
  const [tenant, setTenant] = useState(tenants[0] ?? "demo");

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4 px-4 py-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-heading text-2xl font-semibold tracking-tight">Review</h1>
          <p className="text-sm text-muted-foreground">
            Low-confidence answers, broken answers and proposed relations waiting for a
            person to decide.
          </p>
        </div>
        {tenants.length > 1 ? (
          <TenantSelect tenants={tenants} value={tenant} onChange={setTenant} />
        ) : null}
      </header>
      <Queue
        key={tenant}
        tenant={tenant}
        client={client}
        reviewer={reviewer ?? DEFAULT_REVIEWER}
        focusItem={focusItem ?? null}
      />
    </div>
  );
}

type Notice = { kind: "done" | "error"; text: string };

function Queue({
  tenant,
  client,
  reviewer,
  focusItem,
}: {
  tenant: string;
  client: ApiClient;
  reviewer: string;
  focusItem: string | null;
}) {
  const [state, dispatch] = useReducer(queueReducer, INITIAL_QUEUE);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadCount, setLoadCount] = useState(0);
  const [notice, setNotice] = useState<Notice | null>(null);
  /** The item to move focus to after the list changes (focus must not fall to <body>). */
  const [focusTarget, setFocusTarget] = useState<string | null>(focusItem);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    client.review({ tenant }, { signal: controller.signal }).then(
      (list) => {
        setLoadError(null);
        setLoaded(true);
        dispatch({ type: "load", items: list.items });
      },
      (error: unknown) => {
        if (!isAbort(error)) setLoadError(describeApiFailure(error));
      },
    );
    return () => controller.abort();
  }, [client, tenant, loadCount]);

  useEffect(() => {
    if (focusTarget === null) return;
    const root = listRef.current;
    const target =
      root?.querySelector<HTMLElement>(`[data-item-id="${CSS.escape(focusTarget)}"]`) ??
      (focusTarget === "" ? root : null);
    if (!target) return;
    target.focus();
    target.scrollIntoView?.({ block: "nearest" });
    setFocusTarget(null);
  }, [focusTarget, state.items]);

  const reload = () => {
    setLoadError(null);
    setLoadCount((n) => n + 1);
  };

  const resolve = async (item: ReviewItem, resolution: Resolution) => {
    const title = describeItem(item).title;
    const index = state.items.findIndex((i) => i.id === item.id);
    const neighbour = state.items[index + 1] ?? state.items[index - 1];
    dispatch({ type: "resolving", id: item.id });
    setNotice(null);
    // "" focuses the list itself when nothing is left to move to.
    setFocusTarget(neighbour?.id ?? "");
    try {
      await client.resolve(item.id, { ...resolution, by: reviewer }, tenant);
      dispatch({ type: "resolved", id: item.id });
      setNotice({ kind: "done", text: `${DONE[resolution.action]} “${title}”.` });
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        dispatch({ type: "resolved", id: item.id });
        setNotice({
          kind: "error",
          text: `“${title}” was already resolved by someone else. The queue has been refreshed.`,
        });
        reload();
        return;
      }
      dispatch({ type: "rollback", id: item.id });
      setFocusTarget(item.id);
      setNotice({
        kind: "error",
        text: `Could not ${resolution.action} “${title}”. ${describeApiFailure(error)}`,
      });
    }
  };

  const groups = groupByKind(state.items);

  return (
    <div className="flex flex-col gap-4">
      <p role="status" className={notice?.kind === "done" ? "text-sm" : "sr-only"}>
        {notice?.kind === "done" ? notice.text : ""}
      </p>
      {notice?.kind === "error" ? (
        <p role="alert" className="rounded-lg border border-destructive/40 p-3 text-sm">
          {notice.text}
        </p>
      ) : null}

      {loadError ? (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-3 rounded-lg border border-destructive/40 p-3 text-sm"
        >
          <p>Could not load the review queue. {loadError}</p>
          <Button variant="outline" size="sm" onClick={reload}>
            Retry
          </Button>
        </div>
      ) : null}

      <div ref={listRef} tabIndex={-1} aria-label="Review items" className="flex flex-col gap-6 outline-none">
        {loaded && groups.length === 0 ? (
          <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
            Nothing to review. New items appear here when an answer or relation needs a
            person to decide.
          </p>
        ) : null}
        {groups.map((group) => (
          <Group key={group.kind} group={group} focusItem={focusItem} onResolve={resolve} />
        ))}
      </div>
    </div>
  );
}

function Group({
  group,
  focusItem,
  onResolve,
}: {
  group: ReviewGroup;
  focusItem: string | null;
  onResolve: (item: ReviewItem, resolution: Resolution) => void;
}) {
  const headingId = useId();
  const count = group.items.length;
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex items-baseline gap-2">
        <h2 id={headingId} className="font-heading text-lg font-semibold">
          {group.label}
        </h2>
        <span className="text-sm text-muted-foreground">
          {count} {count === 1 ? "item" : "items"}
        </span>
      </div>
      <ul className="flex flex-col gap-3">
        {group.items.map((item) => (
          <li key={item.id}>
            <ReviewItemCard
              item={item}
              highlighted={item.id === focusItem}
              onResolve={(i, r) => void onResolve(i, r)}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}
