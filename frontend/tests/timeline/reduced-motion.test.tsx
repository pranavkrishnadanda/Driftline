import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DocumentTimeline } from "@/components/timeline/document-timeline";
import { AXIS_WIDTH } from "@/components/timeline/version-axis";
import { layoutTimeline } from "@/lib/timeline/layout";

import { TIMELINE } from "../support/version-timeline-fixtures";

const NOW = new Date("2026-02-10T00:00:00Z");
const layout = layoutTimeline(TIMELINE.versions, AXIS_WIDTH, { now: NOW });
const at = (no: number) => layout.items.find((i) => i.versionNo === no)!.x;

function thumbX(): number {
  const transform = screen.getByTestId("scrubber-thumb").style.transform;
  const match = /translateX\((-?[\d.]+)px\)/.exec(transform);
  return match ? Number(match[1]) : Number.NaN;
}

function progressWidth(): number {
  return Number(screen.getByTestId("scrubber-progress").getAttribute("width"));
}

describe("reduced motion", () => {
  it("places the scrubber at the selected version at once, with every section visible", () => {
    render(<DocumentTimeline timeline={TIMELINE} tenant="demo" now={NOW} reducedMotion />);

    expect(thumbX()).toBeCloseTo(at(3));
    expect(progressWidth()).toBeCloseTo(at(3));

    act(() => screen.getByRole("button", { name: /^v1/ }).click());
    // No animation: the final position is applied synchronously.
    expect(thumbX()).toBeCloseTo(at(1));
    expect(progressWidth()).toBeCloseTo(at(1));

    // All content is present without waiting for any animation.
    expect(screen.getByRole("heading", { level: 1, name: "Metformin label" })).toBeVisible();
    expect(screen.getByRole("slider", { name: "Version" })).toBeVisible();
    expect(screen.getByRole("region", { name: "v1 is the first version" })).toBeVisible();
    expect(screen.getByRole("region", { name: "Supersession" })).toBeVisible();
    expect(screen.getByRole("list", { name: "Declared by this document" })).toBeVisible();
  });

  it("animates the scrubber with anime.js when motion is allowed", async () => {
    render(<DocumentTimeline timeline={TIMELINE} tenant="demo" now={NOW} reducedMotion={false} />);
    // The first placement is instant either way.
    expect(thumbX()).toBeCloseTo(at(3));

    act(() => screen.getByRole("button", { name: /^v1/ }).click());
    // The move is tweened, not applied at once...
    expect(thumbX()).not.toBeCloseTo(at(1));
    // ...and it lands on the selected version.
    await vi.waitFor(() => expect(thumbX()).toBeCloseTo(at(1)), { timeout: 3000 });
  });
});
