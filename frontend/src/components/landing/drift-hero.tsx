"use client";

/**
 * The landing hero: one document drifting through three versions on a time axis, drawn
 * as SVG and choreographed by anime.js (spec §9: anime.js owns choreographed SVG; Motion
 * never touches these elements).
 *
 * The markup is the finished picture (v3 in force, v1 and v2 left behind as faded
 * ghosts, the rewritten and added sections marked). Under reduced motion that is all
 * that renders. Otherwise an anime.js timeline rewinds it to v1 and replays the drift
 * in a loop; reverting the scope restores the finished picture exactly.
 */
import { createScope, createTimeline, stagger, svg, type Scope, type Timeline } from "animejs";
import { Pause, Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { usePrefersReducedMotion } from "@/hooks/use-prefers-reduced-motion";
import { HERO_VERSIONS, documentLines, versionStops, type DocumentLine } from "@/lib/landing/hero";
import { cn } from "@/lib/utils";

const WIDTH = 640;
const HEIGHT = 300;
const AXIS_Y = 250;
const DOC_W = 132;
const DOC_H = 168;
const DOC_TOP = 40;
const TEXT_X = 14;
const TEXT_W = DOC_W - 2 * TEXT_X;
const LINE_H = 8;
const lineY = (i: number) => 44 + i * 22;

const STOPS = versionStops(HERO_VERSIONS.length, { width: WIDTH, inset: 120 });
const docX = (i: number) => STOPS[i] - DOC_W / 2;
const LAST = HERO_VERSIONS.length - 1;
const FINAL_LINES = documentLines(HERO_VERSIONS, LAST);
const CHANGED = HERO_VERSIONS.findIndex((v) => v.changed !== null);
const CHANGED_LINE = HERO_VERSIONS[CHANGED].changed!;
const ADDED_LINE = FINAL_LINES.findIndex((l) => l.state === "added");

/** Width in px of section `line` in version `version`. */
const widthAt = (version: number, line: number) =>
  documentLines(HERO_VERSIONS, version)[line].width * TEXT_W;

function Lines({ lines, ghost = false }: { lines: DocumentLine[]; ghost?: boolean }) {
  return lines.map((line, i) => (
    <rect
      key={i}
      x={TEXT_X}
      y={lineY(i)}
      width={line.width * TEXT_W}
      height={LINE_H}
      rx={2}
      className={cn(
        ghost || line.state === "same" ? "fill-muted-foreground/45" : null,
        !ghost && line.state === "changed" && "fill-amber-500",
        !ghost && line.state === "added" && "fill-emerald-600",
      )}
    />
  ));
}

function Page({ className }: { className?: string }) {
  return (
    <>
      <rect
        width={DOC_W}
        height={DOC_H}
        rx={10}
        className={cn("fill-card stroke-border", className)}
        strokeWidth={1.5}
      />
      <rect x={TEXT_X} y={18} width={70} height={9} rx={2} className="fill-foreground/80" />
    </>
  );
}

export interface DriftHeroProps {
  /** Defaults to the user's `prefers-reduced-motion` setting. */
  reducedMotion?: boolean;
  className?: string;
}

export function DriftHero({ reducedMotion: reducedProp, className }: DriftHeroProps) {
  const prefersReduced = usePrefersReducedMotion();
  const reduced = reducedProp ?? prefersReduced;
  const root = useRef<SVGSVGElement>(null);
  const timeline = useRef<Timeline | null>(null);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (reduced || !root.current) return;
    const scope: Scope = createScope({ root }).add(() => {
      const canDraw = typeof root.current?.querySelector("path")?.getTotalLength === "function";
      const axis = canDraw ? svg.createDrawable("[data-hero=axis]") : null;
      const check = canDraw ? svg.createDrawable("[data-hero=check-mark]") : null;
      const drawIn = { draw: ["0 0", "0 1"], duration: 420, ease: "outQuad" };

      const tl = createTimeline({ loop: true, loopDelay: 2600, defaults: { ease: "inOutQuad" } })
        // Rewind the finished picture to v1.
        .set("[data-hero=ghost]", { opacity: 0 })
        .set("[data-hero=doc]", { translateX: docX(0) })
        .set("[data-hero=cursor]", { translateX: STOPS[0] })
        .set("[data-hero=changed]", { width: widthAt(0, CHANGED_LINE), opacity: 0 })
        .set("[data-hero=changed-base]", { opacity: 1 })
        .set("[data-hero=added]", { width: 0 })
        .set("[data-hero=alert]", { opacity: 0 })
        .set("[data-hero=check]", { opacity: 1 })
        .set("[data-hero=marker]", { opacity: 0 })
        .set("[data-hero=label]", { opacity: 0 });
      if (axis) tl.add(axis, { draw: ["0 0", "0 1"], duration: 800 }, 0);
      tl.add("[data-hero=marker]", { opacity: 1, duration: 260, delay: stagger(140) }, 150).add(
        "[data-hero=label]",
        { opacity: 1, duration: 260, delay: stagger(140) },
        250,
      );
      if (check) tl.add(check, drawIn, 800);

      // v1 -> v2: the document drifts right, leaving v1 behind; a section is rewritten.
      tl.add("[data-hero=check]", { opacity: 0, duration: 200 }, 1900)
        .add("[data-hero=ghost][data-version='0']", { opacity: 0.4, duration: 500 }, 2000)
        .add("[data-hero=doc]", { translateX: docX(1), duration: 1100 }, 2000)
        .add("[data-hero=cursor]", { translateX: STOPS[1], duration: 1100 }, 2000)
        .add(
          "[data-hero=changed]",
          { width: widthAt(1, CHANGED_LINE), opacity: 1, duration: 450 },
          3100,
        )
        .add("[data-hero=changed-base]", { opacity: 0, duration: 450 }, 3100)
        .add(
          "[data-hero=pulse]",
          { r: [4, 20], opacity: [0.8, 0], duration: 800, ease: "outQuad" },
          3100,
        )
        .add("[data-hero=alert]", { opacity: 1, duration: 300 }, 3250)
        .add("[data-hero=check]", { opacity: 1, duration: 1 }, 3500);
      if (check) tl.add(check, drawIn, 3500);

      // v2 -> v3: drifts again; a section is added.
      tl.add("[data-hero=check]", { opacity: 0, duration: 200 }, 4600)
        .add("[data-hero=ghost][data-version='1']", { opacity: 0.4, duration: 500 }, 4700)
        .add("[data-hero=doc]", { translateX: docX(2), duration: 1100 }, 4700)
        .add("[data-hero=cursor]", { translateX: STOPS[2], duration: 1100 }, 4700)
        .add(
          "[data-hero=added]",
          { width: FINAL_LINES[ADDED_LINE].width * TEXT_W, duration: 500 },
          5800,
        )
        .add("[data-hero=check]", { opacity: 1, duration: 1 }, 6200);
      if (check) tl.add(check, drawIn, 6200);
      timeline.current = tl;
    });
    return () => {
      timeline.current = null;
      scope.revert();
    };
  }, [reduced]);

  const togglePause = () => {
    const tl = timeline.current;
    if (!tl) return;
    if (paused) tl.play();
    else tl.pause();
    setPaused(!paused);
  };

  const last = HERO_VERSIONS[LAST];
  return (
    // `data-ambient`: a looping decoration; the browser checks don't wait for it to stop.
    <figure data-ambient className={cn("relative w-full", className)}>
      <svg
        ref={root}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-labelledby="drift-hero-title"
        aria-describedby="drift-hero-desc"
        className="h-auto w-full overflow-visible"
      >
        <title id="drift-hero-title">A document drifting through three versions</title>
        <desc id="drift-hero-desc">
          An illustrative guideline moves along a time axis from v1 to v3. Version 2 rewrites a
          section and raises a drift alert; version 3 adds a section. Earlier versions stay behind
          as faded copies, still answerable as of their own dates.
        </desc>

        {/* Ghosts: the versions left behind. */}
        {HERO_VERSIONS.slice(0, LAST).map((v, i) => (
          <g key={v.label} transform={`translate(${docX(i)} ${DOC_TOP})`}>
            <g data-hero="ghost" data-version={i} opacity={0.4}>
              <Page className="fill-transparent stroke-muted-foreground/50 [stroke-dasharray:4_4]" />
              <Lines lines={documentLines(HERO_VERSIONS, i)} ghost />
            </g>
          </g>
        ))}

        {/* The time axis, its version markers and the as-of cursor. */}
        <path
          data-hero="axis"
          d={`M40 ${AXIS_Y} H${WIDTH - 40}`}
          className="stroke-muted-foreground/60"
          strokeWidth={2}
          strokeLinecap="round"
          fill="none"
        />
        {HERO_VERSIONS.map((v, i) => (
          <g key={v.label}>
            <circle
              data-hero="marker"
              cx={STOPS[i]}
              cy={AXIS_Y}
              r={6}
              className="fill-background stroke-foreground"
              strokeWidth={2}
            />
            <text
              data-hero="label"
              x={STOPS[i]}
              y={AXIS_Y + 28}
              textAnchor="middle"
              className="fill-foreground font-mono text-[12px]"
            >
              {v.label} · {v.validFrom}
            </text>
          </g>
        ))}
        <g data-hero="cursor" style={{ transform: `translateX(${STOPS[LAST]}px)` }}>
          <path
            d={`M0 ${DOC_TOP - 14} V${AXIS_Y - 8}`}
            className="stroke-primary/50"
            strokeWidth={1.5}
            strokeDasharray="3 4"
            fill="none"
          />
          <path d={`M-6 ${DOC_TOP - 22} H6 L0 ${DOC_TOP - 14} Z`} className="fill-primary" />
        </g>

        {/* The document, in force as of the cursor. */}
        <g transform={`translate(0 ${DOC_TOP})`}>
          <g data-hero="doc" style={{ transform: `translateX(${docX(LAST)}px)` }}>
            <Page className="drop-shadow-sm" />
            {/* The rewritten section as v1 had it; only shown while rewinding. */}
            <rect
              data-hero="changed-base"
              x={TEXT_X}
              y={lineY(CHANGED_LINE)}
              width={widthAt(0, CHANGED_LINE)}
              height={LINE_H}
              rx={2}
              opacity={0}
              className="fill-muted-foreground/45"
            />
            {FINAL_LINES.map((line, i) => (
              <rect
                key={i}
                data-hero={i === CHANGED_LINE ? "changed" : i === ADDED_LINE ? "added" : undefined}
                x={TEXT_X}
                y={lineY(i)}
                width={line.width * TEXT_W}
                height={LINE_H}
                rx={2}
                className={cn(
                  line.state === "same" && "fill-muted-foreground/45",
                  line.state === "changed" && "fill-amber-500",
                  line.state === "added" && "fill-emerald-600",
                )}
              />
            ))}
            <circle
              data-hero="pulse"
              cx={TEXT_X + widthAt(1, CHANGED_LINE) + 8}
              cy={lineY(CHANGED_LINE) + LINE_H / 2}
              r={4}
              opacity={0}
              className="fill-none stroke-amber-500"
              strokeWidth={2}
            />
            {/* A verified citation: the answer's quote is still in this version. */}
            <g data-hero="check" transform={`translate(${DOC_W - 14} -10)`}>
              <circle r={13} className="fill-emerald-600" />
              <path
                data-hero="check-mark"
                d="M-5.5 0.5 L-1.5 4.5 L6 -4"
                fill="none"
                stroke="white"
                strokeWidth={2.5}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </g>
            <g data-hero="alert" transform={`translate(0 ${DOC_H + 10})`}>
              <rect
                width={DOC_W}
                height={22}
                rx={11}
                className="fill-amber-100 stroke-amber-600"
                strokeWidth={1}
              />
              <text
                x={DOC_W / 2}
                y={15}
                textAnchor="middle"
                className="fill-amber-950 text-[11px] font-medium"
              >
                drift alert · {HERO_VERSIONS[CHANGED].label}
              </text>
            </g>
          </g>
        </g>
      </svg>
      <figcaption className="mt-2 flex items-center justify-between gap-3 text-xs text-muted-foreground">
        <span>
          Illustration: one document, three versions. Ask as of any date and Driftline answers from
          the version in force then ({last.label} since {last.validFrom} here).
        </span>
        {reduced ? null : (
          <button
            type="button"
            onClick={togglePause}
            aria-pressed={paused}
            className="inline-flex size-8 shrink-0 items-center justify-center rounded-md border border-border text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {paused ? (
              <Play aria-hidden className="size-4" />
            ) : (
              <Pause aria-hidden className="size-4" />
            )}
            <span className="sr-only">Pause animation</span>
          </button>
        )}
      </figcaption>
    </figure>
  );
}
