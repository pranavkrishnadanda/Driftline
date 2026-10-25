import type { Metadata } from "next";
import { Suspense } from "react";

import { DocumentTimelineRoute } from "@/components/timeline/routes";
import { DEMO } from "@/lib/demo/config";
import { demoDocumentParams } from "@/lib/demo/static-params";

export const metadata: Metadata = { title: "Timeline · Driftline" };

/** The static demo export prerenders one page per recorded document; otherwise none. */
export const generateStaticParams = DEMO ? demoDocumentParams : undefined;

/** A document's version timeline, section diff and supersession graph. */
export default function DocumentTimelinePage({
  params,
  searchParams,
}: PageProps<"/documents/[id]">) {
  return (
    <Suspense
      fallback={
        <p
          role="status"
          className="mx-auto w-full max-w-6xl px-4 py-8 text-sm text-muted-foreground"
        >
          Loading timeline…
        </p>
      }
    >
      <DocumentTimelineRoute params={params} searchParams={searchParams} />
    </Suspense>
  );
}
