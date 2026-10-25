import { formatDate } from "@/lib/ask/format";
import { DEMO_RECORDED_AT, QUICK_START_URL } from "@/lib/demo/config";

/** The recorded demo's label, on every page of the demo build (never in a normal build). */
export function DemoBanner({ recordedAt = DEMO_RECORDED_AT }: { recordedAt?: string }) {
  return (
    <div
      role="region"
      aria-label="Recorded demo"
      data-testid="demo-banner"
      className="border-b border-changed/40 bg-changed-soft px-4 py-2 text-center text-sm"
    >
      <strong className="font-semibold">Recorded demo</strong> — real answers captured from a live
      run on {recordedAt ? formatDate(recordedAt) : "an earlier date"}. Run it yourself:{" "}
      <a
        href={QUICK_START_URL}
        className="font-medium underline underline-offset-4 focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        quick start
      </a>
      .
    </div>
  );
}
