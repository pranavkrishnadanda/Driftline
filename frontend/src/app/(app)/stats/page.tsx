import type { Metadata } from "next";

import { ComingSoon } from "@/components/coming-soon";

export const metadata: Metadata = { title: "Stats · Driftline" };

export default function StatsPage() {
  return (
    <ComingSoon
      title="Stats"
      summary="Corpus size, drift over time, latency, cost per answer and eval scores."
    />
  );
}
