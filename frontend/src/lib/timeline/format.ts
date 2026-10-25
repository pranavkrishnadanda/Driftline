import type { TimelineItem } from "./layout";

const DATE = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

/** "11 Jan 2026" (UTC, so a validity boundary reads the same in every time zone). */
export function formatDay(date: Date | string): string {
  return DATE.format(typeof date === "string" ? new Date(date) : date);
}

/** "11 Jan 2026 – 31 Jan 2026", or "from 31 Jan 2026" for the version in force now. */
export function formatWindow(item: Pick<TimelineItem, "validFrom" | "validTo">): string {
  return item.validTo === null
    ? `from ${formatDay(item.validFrom)}`
    : `${formatDay(item.validFrom)} – ${formatDay(item.validTo)}`;
}

/** The slider's spoken value, e.g. "v3: from 31 Jan 2026, in force now". */
export function versionValueText(item: TimelineItem): string {
  return `v${item.versionNo}: ${formatWindow(item)}${item.openEnded ? ", in force now" : ""}`;
}
