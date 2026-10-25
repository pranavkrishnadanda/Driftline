import type { Metadata } from "next";
import { Suspense } from "react";

import { ReviewPageClient } from "@/components/review/review-page";
import { parseTenants } from "@/lib/ask/format";

export const metadata: Metadata = { title: "Review · Driftline" };

export default function ReviewPage() {
  const tenants = parseTenants(process.env.NEXT_PUBLIC_DRIFTLINE_TENANTS);
  return (
    // The query string is only known at request time; the shell around it prerenders.
    <Suspense
      fallback={
        <div className="mx-auto w-full max-w-3xl px-4 py-8">
          <h1 className="font-heading text-2xl font-semibold tracking-tight">Review</h1>
        </div>
      }
    >
      <ReviewPageClient tenants={tenants} />
    </Suspense>
  );
}
