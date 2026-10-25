import type { Metadata } from "next";

import { ComingSoon } from "@/components/coming-soon";

export const metadata: Metadata = { title: "Drift · Driftline" };

export default function DriftPage() {
  return (
    <ComingSoon
      title="Drift"
      summary="Live alerts when a new document version changes an answer you are watching."
    />
  );
}
