import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import Home from "@/app/page";
import { DriftHero } from "@/components/landing/drift-hero";
import { FEATURES } from "@/components/landing/feature-cards";
import { HERO_VERSIONS, versionStops } from "@/lib/landing/hero";

const doc = (container: HTMLElement) => container.querySelector<SVGGElement>("[data-hero=doc]")!;
const translateX = (el: SVGElement): number => {
  const match = /translateX\((-?[\d.]+)px\)/.exec(el.style.transform);
  return match ? Number(match[1]) : Number.NaN;
};
const STOPS = versionStops(HERO_VERSIONS.length, { width: 640, inset: 120 });

describe("landing page", () => {
  it("states what Driftline is, with the two primary calls to action", () => {
    render(<Home />);

    expect(
      screen.getByRole("heading", { level: 1, name: /Answers as of any date, from the version in force then/ }),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "Try Ask" })).toHaveAttribute("href", "/ask");
    expect(screen.getByRole("link", { name: "View drift inbox" })).toHaveAttribute("href", "/drift");
    expect(
      screen.getByRole("img", { name: "A document drifting through three versions" }),
    ).toBeInTheDocument();
  });

  it("lists the four features as keyboard-flippable cards", async () => {
    render(<Home />);
    const list = screen.getByRole("list", { name: "Features" });
    const cards = within(list).getAllByRole("group");
    expect(cards.map((c) => c.getAttribute("aria-label"))).toEqual(FEATURES.map((f) => f.title));
    for (const card of cards) expect(card).toHaveAttribute("tabindex", "0");

    const ask = cards[0];
    expect(within(ask).getByText(FEATURES[0].summary)).toBeVisible();
    act(() => {
      ask.focus();
      fireEvent.keyDown(ask, { key: "Enter" });
    });
    expect(ask).toHaveAccessibleDescription(/Showing the back/);
    // The back face is inert until the card has turned past edge-on.
    const link = await vi.waitFor(() => within(ask).getByRole("link", { name: /Try Ask/ }));
    expect(link).toHaveAttribute("href", "/ask");
  });

  it("only makes claims about what is built: MCP lists the gateway's five tools", () => {
    const mcp = FEATURES.find((f) => f.title === "MCP for agents")!;
    expect(mcp.details.join(" ")).toMatch(/ask, list_sources, diff_versions, get_timeline and watch_answer/);
  });
});

describe("DriftHero", () => {
  it("under reduced motion renders the finished picture and no animation control", () => {
    const { container } = render(<DriftHero reducedMotion />);

    expect(translateX(doc(container))).toBeCloseTo(STOPS.at(-1)! - 66);
    for (const ghost of container.querySelectorAll("[data-hero=ghost]")) {
      expect(ghost.getAttribute("opacity")).toBe("0.4");
      expect((ghost as SVGElement).style.opacity).toBe("");
    }
    expect(screen.queryByRole("button", { name: "Pause animation" })).toBeNull();
  });

  it("replays the drift from v1 with anime.js when motion is allowed, and can be paused", async () => {
    const { container, unmount } = render(<DriftHero reducedMotion={false} />);

    // The timeline rewinds the document to v1 first...
    await vi.waitFor(() => expect(translateX(doc(container))).toBeCloseTo(STOPS[0] - 66));
    const ghost = container.querySelector<SVGElement>("[data-hero=ghost]")!;
    expect(Number(ghost.style.opacity)).toBe(0);

    const pause = screen.getByRole("button", { name: "Pause animation" });
    expect(pause).toHaveAttribute("aria-pressed", "false");
    act(() => pause.click());
    expect(pause).toHaveAttribute("aria-pressed", "true");

    // ...and reverting on unmount leaves no inline animation state behind.
    const docEl = doc(container);
    unmount();
    expect(translateX(docEl)).toBeCloseTo(STOPS.at(-1)! - 66);
  });
});
