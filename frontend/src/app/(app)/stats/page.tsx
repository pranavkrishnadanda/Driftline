import type { Metadata } from "next";

import { StatsView } from "@/components/stats/stats-view";
import { parseTenants } from "@/lib/ask/format";

export const metadata: Metadata = { title: "Stats · Driftline" };

export default function StatsPage() {
  return <StatsView tenants={parseTenants(process.env.NEXT_PUBLIC_DRIFTLINE_TENANTS)} />;
}
