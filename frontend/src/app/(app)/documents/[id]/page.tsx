import type { Metadata } from "next";
import { Suspense } from "react";

import { DocumentTimelineRoute } from "@/components/timeline/routes";

export const metadata: Metadata = { title: "Timeline · Driftline" };

/** A document's version timeline, section diff and supersession graph. */
export default function DocumentTimelinePage({ params, searchParams }: PageProps<"/documents/[id]">) {
  return (
    <Suspense
      fallback={
        <p role="status" className="mx-auto w-full max-w-6xl px-4 py-8 text-sm text-muted-foreground">
          Loading timeline…
        </p>
      }
    >
      <DocumentTimelineRoute params={params} searchParams={searchParams} />
    </Suspense>
  );
}
