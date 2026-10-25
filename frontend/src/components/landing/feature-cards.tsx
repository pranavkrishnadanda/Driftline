"use client";

/**
 * The landing feature grid: Kokonut UI flip cards (`@kokonutui/card-flip`). The front
 * says what the feature does; the back says how it is built and links to the view.
 */
import { BellRing, Bot, FileCheck2, RotateCcw, UserCheck, type LucideIcon } from "lucide-react";
import Link from "next/link";

import CardFlip from "@/components/kokonutui/card-flip";

export interface Feature {
  title: string;
  icon: LucideIcon;
  summary: string;
  details: string[];
  link: { href: string; label: string } | null;
}

export const FEATURES: Feature[] = [
  {
    title: "As-of answers with verified citations",
    icon: FileCheck2,
    summary:
      "Ask a question as of a date. Driftline answers only from the document versions in force then, and every claim cites an exact quote.",
    details: [
      "Hybrid retrieval: pgvector and Postgres full-text, fused with RRF, then reranked.",
      "A LangGraph agent drafts the answer and checks each quote against the source text.",
      "Too little evidence gets an explicit refusal with the nearest sources, never a guess.",
    ],
    link: { href: "/ask", label: "Try Ask" },
  },
  {
    title: "Live drift alerts",
    icon: BellRing,
    summary:
      "Watch an answer. When a new version of a cited document lands, Driftline re-checks the answer and alerts you as it happens.",
    details: [
      "Each alert shows the before and after text and a verdict.",
      "Alerts stream over server-sent events and resume with Last-Event-ID after a drop.",
      "Accept an alert, or send it to review.",
    ],
    link: { href: "/drift", label: "View drift inbox" },
  },
  {
    title: "Human review",
    icon: UserCheck,
    summary:
      "Low-confidence answers, broken answers and proposed links between documents wait for a person to approve, edit or reject.",
    details: [
      "Items are grouped by kind in one queue.",
      "Resolving an item twice is caught: the second reviewer sees it was already resolved.",
    ],
    link: { href: "/review", label: "Open review queue" },
  },
  {
    title: "MCP for agents",
    icon: Bot,
    summary:
      "Coding agents such as Claude Code and Cursor can use Driftline through an MCP server on the gateway.",
    details: [
      "Streamable HTTP at /mcp, with the tenant's API key.",
      "Five tools: ask, list_sources, diff_versions, get_timeline and watch_answer.",
    ],
    link: null,
  },
];

function Front({ feature }: { feature: Feature }) {
  const Icon = feature.icon;
  return (
    <div className="flex h-full flex-col gap-3 p-5">
      <Icon aria-hidden className="size-6 text-primary" />
      <h3 className="font-heading text-lg leading-snug font-semibold">{feature.title}</h3>
      <p className="text-sm text-muted-foreground">{feature.summary}</p>
      <p className="mt-auto inline-flex items-center gap-1.5 text-xs text-muted-foreground">
        <RotateCcw aria-hidden className="size-3.5" />
        Turn over for how it works
      </p>
    </div>
  );
}

function Back({ feature }: { feature: Feature }) {
  return (
    <div className="flex h-full flex-col gap-3 p-5">
      <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
        How it works
      </p>
      <ul className="flex list-disc flex-col gap-2 pl-4 text-sm">
        {feature.details.map((d) => (
          <li key={d}>{d}</li>
        ))}
      </ul>
      {feature.link ? (
        <Link
          href={feature.link.href}
          className="mt-auto text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {feature.link.label} →
        </Link>
      ) : null}
    </div>
  );
}

export function FeatureCards() {
  return (
    <ul aria-label="Features" className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
      {FEATURES.map((feature) => (
        <li key={feature.title} className="flex justify-center">
          <CardFlip
            label={feature.title}
            className="aspect-auto h-64 w-full sm:h-80 max-w-sm focus-visible:ring-ring focus-visible:ring-offset-background"
            faceClassName="border-border bg-card text-card-foreground dark:border-border dark:bg-card dark:text-card-foreground"
            front={<Front feature={feature} />}
            back={<Back feature={feature} />}
          />
        </li>
      ))}
    </ul>
  );
}
