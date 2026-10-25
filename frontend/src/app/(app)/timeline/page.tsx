import type { Metadata } from "next";
import { Suspense } from "react";

import { TimelinePicker } from "@/components/timeline/routes";

export const metadata: Metadata = { title: "Timeline · Driftline" };

export default function TimelinePage({ searchParams }: PageProps<"/timeline">) {
  return (
    <Suspense
      fallback={
        <section className="mx-auto flex w-full max-w-3xl flex-col gap-2 px-4 py-10">
          <h1 className="font-heading text-2xl font-semibold tracking-tight">Timeline</h1>
          <p role="status" className="text-sm text-muted-foreground">
            Loading…
          </p>
        </section>
      }
    >
      <TimelinePicker searchParams={searchParams} />
    </Suspense>
  );
}
