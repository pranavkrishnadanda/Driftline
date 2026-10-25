import type { Metadata } from "next";

import { DriftInbox } from "@/components/drift/drift-inbox";
import { parseTenants } from "@/lib/ask/format";

export const metadata: Metadata = { title: "Drift · Driftline" };

export default function DriftPage() {
  return <DriftInbox tenants={parseTenants(process.env.NEXT_PUBLIC_DRIFTLINE_TENANTS)} />;
}
