import type { Metadata } from "next";

import { ComingSoon } from "@/components/coming-soon";

export const metadata: Metadata = { title: "Review · Driftline" };

export default function ReviewPage() {
  return (
    <ComingSoon
      title="Review"
      summary="Low-confidence answers and proposed supersession relations waiting for a person to decide."
    />
  );
}
