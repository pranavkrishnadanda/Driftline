import type { Metadata } from "next";

import { AskView } from "@/components/ask/ask-view";
import { parseTenants } from "@/lib/ask/format";

export const metadata: Metadata = { title: "Ask · Driftline" };

export default function AskPage() {
  return <AskView tenants={parseTenants(process.env.NEXT_PUBLIC_DRIFTLINE_TENANTS)} />;
}
