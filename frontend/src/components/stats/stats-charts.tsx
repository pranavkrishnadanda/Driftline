"use client";

/**
 * The `/stats` charts. Every chart is a Bklit UI component installed from the `@bklit`
 * registry (`src/components/charts/`). Each SVG is decorative to assistive tech: the
 * figure around it (`ChartFigure`) carries the title and a sentence describing the data.
 *
 * Bklit honours reduced motion only partly, so these gate it themselves: series get
 * `animate={false}` and roots `animationDuration={0}` (no clip reveal, no bar stagger).
 * The gauge draws its notches in place by itself (`gauge.tsx` checks `useReducedMotion`).
 */
import { useMemo } from "react";

import { Bar } from "@/components/charts/bar";
import { BarChart } from "@/components/charts/bar-chart";
import { BarXAxis } from "@/components/charts/bar-x-axis";
import { Gauge } from "@/components/charts/gauge";
import { Grid } from "@/components/charts/grid";
import {
  Legend,
  LegendItem,
  LegendLabel,
  LegendMarker,
  LegendValue,
} from "@/components/charts/legend";
import { Line, LineChart } from "@/components/charts/line-chart";
import { ChartTooltip } from "@/components/charts/tooltip";
import { XAxis } from "@/components/charts/x-axis";
import { YAxis } from "@/components/charts/y-axis";
import type { Stats } from "@/lib/api/client";
import {
  backlogSeries,
  costSeries,
  driftSeries,
  evalSeries,
  formatCount,
  formatMs,
  formatScore,
  formatUsd,
  latencySeries,
} from "@/lib/stats/format";

const VERDICTS = [
  { key: "still_valid", label: "Still valid", color: "var(--chart-1)" },
  { key: "changed", label: "Changed", color: "var(--chart-2)" },
  { key: "broken", label: "Broken", color: "var(--chart-3)" },
] as const;

const P50 = "var(--chart-1)";
const P95 = "var(--chart-2)";

interface ChartProps {
  stats: Stats;
  reduceMotion: boolean;
}

/** Root props that turn the enter animation off under reduced motion. */
function motionProps(reduce: boolean): { animationDuration?: number } {
  return reduce ? { animationDuration: 0 } : {};
}

function num(value: unknown): number {
  return typeof value === "number" ? value : 0;
}

export function DriftChart({ stats, reduceMotion }: ChartProps) {
  const data = useMemo(() => driftSeries(stats), [stats]);
  const legend = useMemo(
    () =>
      VERDICTS.map((v) => ({
        label: v.label,
        color: v.color,
        value: stats.drift.per_day.reduce((n, d) => n + d[v.key], 0),
      })),
    [stats],
  );
  return (
    <div className="flex flex-col gap-3">
      <div aria-hidden="true">
        <BarChart
          aspectRatio="4 / 1"
          data={data}
          margin={{ top: 16, right: 8, bottom: 32, left: 8 }}
          stacked
          stackGap={1}
          xDataKey="day"
          {...motionProps(reduceMotion)}
        >
          <Grid horizontal />
          {VERDICTS.map((v) => (
            <Bar
              key={v.key}
              animate={!reduceMotion}
              dataKey={v.key}
              fill={v.color}
              stroke={v.color}
            />
          ))}
          <BarXAxis maxLabels={6} />
          <ChartTooltip
            rows={(point) =>
              VERDICTS.map((v) => ({ color: v.color, label: v.label, value: num(point[v.key]) }))
            }
            showDatePill={false}
          />
        </BarChart>
      </div>
      <Legend items={legend} title="Verdicts">
        <LegendItem className="flex items-center gap-2 text-sm">
          <LegendMarker />
          <LegendLabel className="flex-1" />
          <LegendValue formatValue={formatCount} />
        </LegendItem>
      </Legend>
    </div>
  );
}

export function LatencyChart({ stats, reduceMotion }: ChartProps) {
  const data = useMemo(() => latencySeries(stats), [stats]);
  return (
    <div aria-hidden="true">
      <LineChart
        aspectRatio="5 / 2"
        data={data}
        margin={{ top: 16, right: 16, bottom: 32, left: 56 }}
        xDataKey="date"
        {...motionProps(reduceMotion)}
      >
        <Grid horizontal />
        <Line animate={!reduceMotion} dataKey="p50" stroke={P50} />
        <Line animate={!reduceMotion} dataKey="p95" stroke={P95} />
        <XAxis />
        <YAxis formatValue={formatMs} />
        <ChartTooltip
          rows={(point) => [
            { color: P50, label: "p50", value: formatMs(num(point.p50)) },
            { color: P95, label: "p95", value: formatMs(num(point.p95)) },
          ]}
        />
      </LineChart>
    </div>
  );
}

export function CostChart({ stats, reduceMotion }: ChartProps) {
  const data = useMemo(() => costSeries(stats), [stats]);
  return (
    <div aria-hidden="true">
      <LineChart
        aspectRatio="5 / 2"
        data={data}
        margin={{ top: 16, right: 16, bottom: 32, left: 64 }}
        xDataKey="date"
        {...motionProps(reduceMotion)}
      >
        <Grid horizontal />
        <Line animate={!reduceMotion} dataKey="perAnswer" stroke="var(--chart-line-primary)" />
        <XAxis />
        <YAxis formatValue={formatUsd} />
        <ChartTooltip
          rows={(point) => [
            {
              color: "var(--chart-line-primary)",
              label: "Per answer",
              value: formatUsd(num(point.perAnswer)),
            },
          ]}
        />
      </LineChart>
    </div>
  );
}

export function CacheGauge({ stats }: { stats: Stats }) {
  const rate = stats.cache.hit_rate ?? 0;
  return (
    <div aria-hidden="true" className="mx-auto h-44 w-full max-w-64">
      <Gauge
        centerValue={rate * 100}
        defaultLabel="hit rate"
        formatOptions={{ maximumFractionDigits: 1 }}
        suffix="%"
        value={rate * 100}
      />
    </div>
  );
}

export function BacklogChart({ stats, reduceMotion }: ChartProps) {
  const data = useMemo(() => backlogSeries(stats), [stats]);
  return (
    <div aria-hidden="true">
      <BarChart
        aspectRatio="5 / 2"
        data={data}
        margin={{ top: 16, right: 8, bottom: 32, left: 8 }}
        xDataKey="kind"
        {...motionProps(reduceMotion)}
      >
        <Grid horizontal />
        <Bar animate={!reduceMotion} dataKey="open" fill="var(--chart-4)" stroke="var(--chart-4)" />
        <BarXAxis showAllLabels />
        <ChartTooltip
          rows={(point) => [
            { color: "var(--chart-4)", label: "Open", value: formatCount(num(point.open)) },
          ]}
          showDatePill={false}
        />
      </BarChart>
    </div>
  );
}

export function EvalChart({ stats, reduceMotion }: ChartProps) {
  const data = useMemo(() => evalSeries(stats), [stats]);
  return (
    <div aria-hidden="true">
      <BarChart
        aspectRatio="4 / 1"
        data={data}
        margin={{ top: 16, right: 8, bottom: 32, left: 8 }}
        xDataKey="metric"
        {...motionProps(reduceMotion)}
      >
        <Grid horizontal />
        <Bar
          animate={!reduceMotion}
          dataKey="score"
          fill="var(--chart-5)"
          stroke="var(--chart-5)"
        />
        <BarXAxis showAllLabels />
        <ChartTooltip
          rows={(point) => [
            { color: "var(--chart-5)", label: "Score", value: formatScore(num(point.score)) },
          ]}
          showDatePill={false}
        />
      </BarChart>
    </div>
  );
}

/** A loading placeholder in the shape of the chart that will replace it. */
export function LoadingBars() {
  return (
    <div aria-hidden="true">
      <BarChart aspectRatio="5 / 2" data={[]} status="loading" />
    </div>
  );
}
