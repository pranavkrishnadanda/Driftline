"use client";

import { useSearchParams } from "next/navigation";

import { ReviewQueue } from "@/components/review/review-queue";

/** The review queue, focused on `?item=` when a drift alert linked here. */
export function ReviewPageClient({ tenants }: { tenants: string[] }) {
  const focusItem = useSearchParams().get("item");
  return <ReviewQueue tenants={tenants} focusItem={focusItem} />;
}
