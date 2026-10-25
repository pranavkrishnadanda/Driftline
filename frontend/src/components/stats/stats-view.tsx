"use client";

import {
  Activity,
  Clock,
  DatabaseZap,
  ExternalLink,
  FileStack,
  GitCompareArrows,
  Inbox,
  type LucideIcon,
  Receipt,
} from "lucide-react";
import { useEffect, useId, useMemo, useState, type ReactNode } from "react";

import { TenantSelect } from "@/components/ask/ask-controls";
import WidgetGrid, {
  type WidgetGridItem,
  type WidgetSize,
} from "@/components/kokonutui/bento-grid";
import {
  BacklogChart,
  CacheGauge,
  CostChart,
  DriftChart,
  EvalChart,
  LatencyChart,
  LoadingBars,
} from "@/components/stats/stats-charts";
import { Button } from "@/components/ui/button";
import { useHasResizeObserver, usePrefersReducedMotion } from "@/hooks/use-prefers-reduced-motion";
import { createApiClient, type ApiClient, type Stats } from "@/lib/api/client";
import { describeApiFailure, isAbort } from "@/lib/api/failure";
import {
  backlogTotal,
  describeBacklog,
  describeCache,
  describeCost,
  describeDrift,
  describeEval,
  describeLatency,
  evalSeries,
  formatScore,
  formatScoreFriendly,
  kpiTiles,
  type KpiTile,
} from "@/lib/stats/format";

export interface StatsViewProps {
  tenants: string[];
  /** Defaults to a client for NEXT_PUBLIC_DRIFTLINE_API. */
  client?: ApiClient;
}

export function StatsView({ tenants, client: clientProp }: StatsViewProps) {
  const [client] = useState(() => clientProp ?? createApiClient());
  const [tenant, setTenant] = useState(tenants[0] ?? "demo");
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-4 py-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-heading text-2xl font-semibold tracking-tight">Stats</h1>
          <p className="text-sm text-muted-foreground">
            How Driftline is doing: your documents, the changes it caught, how fast and how cheaply
            it answers, and how well it scores on quality checks. Covers the last 30 days.
          </p>
        </div>
        {tenants.length > 1 ? (
          <TenantSelect tenants={tenants} value={tenant} onChange={setTenant} />
        ) : null}
      </header>
      <StatsBody key={tenant} tenant={tenant} client={client} />
    </div>
  );
}

type Load =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; stats: Stats };

function StatsBody({ tenant, client }: { tenant: string; client: ApiClient }) {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    client.stats({ tenant }, { signal: controller.signal }).then(
      (stats) => setLoad({ state: "ready", stats }),
      (error: unknown) => {
        if (!isAbort(error)) setLoad({ state: "error", message: describeApiFailure(error) });
      },
    );
    return () => controller.abort();
  }, [client, tenant, attempt]);

  const retry = () => {
    setLoad({ state: "loading" });
    setAttempt((n) => n + 1);
  };

  if (load.state === "error") {
    return (
      <div
        role="alert"
        className="flex flex-wrap items-center gap-3 rounded-lg border border-destructive/40 p-3 text-sm"
      >
        <p>Could not load the stats. {load.message}</p>
        <Button variant="outline" size="sm" onClick={retry}>
          Retry
        </Button>
      </div>
    );
  }
  if (load.state === "loading") return <StatsLoading />;
  return <StatsReady stats={load.stats} />;
}

function StatsLoading() {
  const canMeasure = useHasResizeObserver();
  return (
    <div className="flex flex-col gap-4">
      <p role="status" className="text-sm text-muted-foreground">
        Loading stats…
      </p>
      {canMeasure ? (
        <div className="grid gap-4 md:grid-cols-2">
          <Panel title="Changes detected per day">
            <LoadingBars />
          </Panel>
          <Panel title="Answer time">
            <LoadingBars />
          </Panel>
        </div>
      ) : null}
    </div>
  );
}

const TILE_ICONS: Record<KpiTile["id"], LucideIcon> = {
  corpus: FileStack,
  drift: GitCompareArrows,
  latency: Clock,
  cost: Receipt,
  cache: DatabaseZap,
  backlog: Inbox,
};

function TileBody({
  tile,
  size,
  showTitle,
}: {
  tile: KpiTile;
  size: WidgetSize;
  showTitle: boolean;
}) {
  return (
    <div
      role="group"
      aria-label={tile.title}
      title={tile.exact}
      className="flex h-full flex-col justify-end gap-1"
    >
      {showTitle ? <p className="text-sm font-medium text-muted-foreground">{tile.title}</p> : null}
      <p
        className={
          size === "s"
            ? "font-heading text-3xl font-semibold tabular-nums tracking-tight"
            : "font-heading text-4xl font-semibold tabular-nums tracking-tight"
        }
      >
        {tile.value}
      </p>
      <p className="text-xs text-muted-foreground">{tile.detail}</p>
    </div>
  );
}

/**
 * The KPI tiles: Kokonut's Widget Grid cards (`@kokonutui/bento-grid`), which the
 * reader can reorder and resize with pointer or keyboard. It measures its cells with
 * `ResizeObserver`, so where that is missing (server render, jsdom) the same tiles
 * render as a plain list.
 */
function KpiTiles({ stats }: { stats: Stats }) {
  const canMeasure = useHasResizeObserver();
  const tiles = useMemo(() => kpiTiles(stats), [stats]);
  const items = useMemo<WidgetGridItem[]>(
    () =>
      tiles.map((tile) => {
        const Icon = TILE_ICONS[tile.id];
        return {
          id: tile.id,
          title: tile.title,
          icon: <Icon className="size-3.5" />,
          defaultSpan: 2,
          render: (size: WidgetSize) => <TileBody tile={tile} size={size} showTitle={false} />,
        };
      }),
    [tiles],
  );
  if (canMeasure) {
    return <WidgetGrid items={items} label="Key figures" rowHeight={136} className="max-w-none" />;
  }
  return (
    <ul aria-label="Key figures" className="grid grid-cols-2 gap-3 md:grid-cols-3">
      {tiles.map((tile) => (
        <li key={tile.id} className="rounded-2xl border bg-card p-4">
          <TileBody tile={tile} size="m" showTitle />
        </li>
      ))}
    </ul>
  );
}

function Panel({
  title,
  description,
  children,
  className,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
}) {
  const titleId = useId();
  const descriptionId = useId();
  return (
    <figure
      aria-labelledby={titleId}
      aria-describedby={description ? descriptionId : undefined}
      className={`flex min-w-0 flex-col gap-3 rounded-2xl border bg-card p-4 ${className ?? ""}`}
    >
      <figcaption className="flex flex-col gap-1">
        <h2 id={titleId} className="font-heading text-base font-semibold">
          {title}
        </h2>
        {description ? (
          <p id={descriptionId} className="text-sm text-muted-foreground">
            {description}
          </p>
        ) : null}
      </figcaption>
      {children}
    </figure>
  );
}

/** The chart when there is data to draw (and a way to measure it), else nothing. */
function ChartSlot({ show, children }: { show: boolean; children: ReactNode }) {
  const canMeasure = useHasResizeObserver();
  return show && canMeasure ? <>{children}</> : null;
}

/** Where the full evaluation write-up lives. */
const EVAL_REPORT_URL =
  process.env.NEXT_PUBLIC_DRIFTLINE_EVAL_REPORT_URL?.trim() ||
  "https://github.com/pranavkrishnadanda/Driftline/blob/main/evals/RESULTS.md";

/** The latest check's scores as plain figures; the exact value is on hover. */
function EvalScores({ stats }: { stats: Stats }) {
  const scores = evalSeries(stats);
  if (!scores.length) return null;
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {scores.map((m) => (
        <div key={m.metric} className="rounded-xl border bg-background p-3">
          <dt className="text-xs text-muted-foreground">{m.metric}</dt>
          <dd
            title={`Exact score: ${formatScore(m.score)}`}
            className="font-heading text-2xl font-semibold tabular-nums text-brand"
          >
            {formatScoreFriendly(m.score)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function StatsReady({ stats }: { stats: Stats }) {
  const reduceMotion = usePrefersReducedMotion();
  const charts = { stats, reduceMotion };
  return (
    <div className="flex flex-col gap-6">
      <KpiTiles stats={stats} />
      <div className="grid gap-4 md:grid-cols-2">
        <Panel
          title="Changes detected per day"
          description={describeDrift(stats)}
          className="md:col-span-2"
        >
          <ChartSlot show={stats.drift.total > 0}>
            <DriftChart {...charts} />
          </ChartSlot>
        </Panel>
        <Panel title="Answer time" description={describeLatency(stats)}>
          <ChartSlot show={stats.asks.latency.samples > 0}>
            <LatencyChart {...charts} />
          </ChartSlot>
        </Panel>
        <Panel title="Cost per answer" description={describeCost(stats)}>
          <ChartSlot show={stats.cost.answers > 0}>
            <CostChart {...charts} />
          </ChartSlot>
        </Panel>
        <Panel title="Answers reused" description={describeCache(stats)}>
          <ChartSlot show={stats.cache.hit_rate !== null}>
            <CacheGauge stats={stats} />
          </ChartSlot>
        </Panel>
        <Panel title="Waiting for review" description={describeBacklog(stats)}>
          <ChartSlot show={backlogTotal(stats) > 0}>
            <BacklogChart {...charts} />
          </ChartSlot>
        </Panel>
        <Panel
          title="Latest quality check"
          description={describeEval(stats)}
          className="md:col-span-2"
        >
          {stats.latest_eval ? (
            <>
              <EvalScores stats={stats} />
              <ChartSlot show={Object.keys(stats.latest_eval.metrics).length > 0}>
                <EvalChart {...charts} />
              </ChartSlot>
              <a
                href={EVAL_REPORT_URL}
                target="_blank"
                rel="noreferrer"
                className="inline-flex w-fit items-center gap-1 text-sm font-medium text-brand underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Read the full report
                <ExternalLink aria-hidden="true" className="size-3.5" />
                <span className="sr-only">(opens in a new tab)</span>
              </a>
            </>
          ) : (
            <p className="flex items-center gap-2 rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
              <Activity aria-hidden className="size-4" />
              Scores appear here after the first quality check.
            </p>
          )}
        </Panel>
      </div>
    </div>
  );
}
