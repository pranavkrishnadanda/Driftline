import type { Metadata } from "next";

import { ComingSoon } from "@/components/coming-soon";

export const metadata: Metadata = { title: "Timeline · Driftline" };

export default function TimelinePage() {
  return (
    <ComingSoon
      title="Timeline"
      summary="Every version of a document on a time axis, with section diffs and what superseded what."
    />
  );
}
