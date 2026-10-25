import { CircleAlert, CircleCheck, CircleX, type LucideIcon } from "lucide-react";

import type { DriftVerdict } from "@/lib/api/client";
import { cn } from "@/lib/utils";

/**
 * What each drift verdict means, in plain words, and what to do about it. The colours
 * are the app-wide verdict tokens (green, amber, red), also used by the /stats charts.
 */
export const VERDICT_COPY: Record<
  DriftVerdict,
  { label: string; next: string; icon: LucideIcon; style: string }
> = {
  still_valid: {
    label: "Still valid",
    next: "The new version still says the same thing. Nothing to do.",
    icon: CircleCheck,
    style: "bg-valid-soft text-valid",
  },
  changed: {
    label: "Changed: please review",
    next: "The cited passage was reworded in the new version. Check the answer still holds.",
    icon: CircleAlert,
    style: "bg-changed-soft text-changed",
  },
  broken: {
    label: "Broken: the cited text was removed",
    next: "The passage this answer relied on is gone. Send it to review to fix or retire it.",
    icon: CircleX,
    style: "bg-broken-soft text-broken",
  },
};

export function VerdictBadge({
  verdict,
  className,
}: {
  verdict: DriftVerdict;
  className?: string;
}) {
  const { label, icon: Icon, style } = VERDICT_COPY[verdict];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        style,
        className,
      )}
    >
      <Icon aria-hidden="true" className="size-3.5" />
      {label}
    </span>
  );
}
