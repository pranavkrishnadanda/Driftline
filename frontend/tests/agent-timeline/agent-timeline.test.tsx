import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AgentTimeline } from "@/components/agent-timeline/agent-timeline";
import { buildTimeline } from "@/components/agent-timeline/reducer";
import type { AskEvent } from "@/lib/sse/events";

import {
  ANSWERED_RUN,
  CACHE_HIT_RUN,
  ERROR_RUN,
  FAN_OUT_MERGED,
  FAN_OUT_RUN,
  INSUFFICIENT_RUN,
  RE_RETRIEVE_DONE,
  RE_RETRIEVE_RUN,
  REVIEW_WAITING_RUN,
} from "../support/timeline-fixtures";

function show(events: AskEvent[], reducedMotion: "user" | "always" | "never" = "user") {
  render(<AgentTimeline state={buildTimeline(events)} reducedMotion={reducedMotion} />);
  return screen.getByRole("region", { name: "How this answer was built" });
}

const steps = () => screen.getByRole("list", { name: "Agent steps" });

function nodeItem(name: string): HTMLElement {
  const item = steps().querySelector<HTMLElement>(`[data-node="${name}"]`);
  if (!item) throw new Error(`no timeline node ${name}`);
  return item;
}

describe("AgentTimeline", () => {
  it("shows the graph's nodes lit in order for an answered run", () => {
    show(ANSWERED_RUN);
    const items = within(steps())
      .getAllByRole("listitem")
      .filter((li) => li.dataset.node);
    expect(items.map((li) => li.dataset.node)).toEqual([
      "classify",
      "cache",
      "plan",
      "subagent",
      "merge",
      "draft",
      "verify",
      "respond",
    ]);
    expect(items.map((li) => li.dataset.status)).toEqual(Array(8).fill("done"));
    expect(items.map((li) => li.dataset.litOrder)).toEqual([
      "0",
      "1",
      "2",
      "3",
      "4",
      "5",
      "6",
      "7",
    ]);
    expect(within(nodeItem("verify")).getByRole("button")).toHaveAccessibleName(
      /Checking claims against sources: done/,
    );
  });

  it("marks the running node and leaves the rest pending", () => {
    show(ANSWERED_RUN.slice(0, 4));
    expect(nodeItem("classify").dataset.status).toBe("done");
    expect(nodeItem("plan").dataset.status).toBe("active");
    expect(nodeItem("draft").dataset.status).toBe("pending");
    expect(nodeItem("draft").dataset.litOrder).toBeUndefined();
  });

  it("expands the subagent branches side by side for a fan-out", () => {
    show(FAN_OUT_RUN);
    const branches = within(nodeItem("subagent")).getByRole("list", { name: "Parallel searches" });
    const items = within(branches).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items.map((li) => li.dataset.status)).toEqual(["done", "done", "active"]);
    expect(items[1]).toHaveTextContent("What is the maximum daily dose?");
    expect(items[1]).toHaveTextContent("Searched 30 passages, used the 6 most relevant");
  });

  it("flips each claim to verified or not as the claim events arrive", () => {
    show(RE_RETRIEVE_RUN);
    const checks = within(nodeItem("verify")).getByRole("list", { name: "Claim checks" });
    expect(
      within(checks)
        .getAllByRole("img")
        .map((i) => i.getAttribute("aria-label")),
    ).toEqual(["Claim 1 verified", "Claim 2 being checked"]);
  });

  it("shows a rejected claim with its reason", () => {
    show(RE_RETRIEVE_RUN.slice(0, -6));
    const checks = within(nodeItem("verify")).getByRole("list", { name: "Claim checks" });
    expect(within(checks).getByRole("img", { name: "Claim 2 not verified" })).toBeInTheDocument();
    expect(checks).toHaveTextContent("quote not found");
  });

  it("makes the re-retrieve loop visible as an iteration count", () => {
    show(RE_RETRIEVE_DONE);
    expect(nodeItem("re_retrieve").dataset.status).toBe("done");
    expect(nodeItem("re_retrieve")).toHaveTextContent("×1");
    expect(screen.getByText("Pass 2")).toBeInTheDocument();
    expect(nodeItem("draft")).toHaveTextContent("×2");
  });

  it("shows a failed node and the error", () => {
    show(ERROR_RUN);
    expect(nodeItem("draft").dataset.status).toBe("failed");
    expect(screen.getByText(/The agent stopped before finishing/)).toBeInTheDocument();
    // The error code is a technical detail, one click away.
    fireEvent.click(screen.getByRole("button", { name: "Technical details" }));
    expect(screen.getByText(/The agent stopped before finishing: internal/)).toBeInTheDocument();
  });

  it("shows the review node waiting for a reviewer", () => {
    show(REVIEW_WAITING_RUN);
    expect(nodeItem("review").dataset.status).toBe("waiting");
    expect(within(nodeItem("review")).getByRole("button")).toHaveAccessibleName(
      /Waiting for a reviewer: waiting/,
    );
  });

  it("shows a cache hit skipping the rest of the graph", () => {
    show(CACHE_HIT_RUN);
    expect(nodeItem("cache")).toHaveTextContent("reused a saved answer");
    expect(nodeItem("plan").dataset.status).toBe("skipped");
    expect(nodeItem("respond").dataset.status).toBe("done");
  });

  it("shows an explicit refusal and the nearest sources for insufficient evidence", () => {
    const region = show(INSUFFICIENT_RUN);
    expect(
      within(region).getByRole("heading", { name: "Refused: not enough evidence" }),
    ).toBeInTheDocument();
    const sources = within(region).getByRole("list", { name: "Sources the agent considered" });
    expect(
      within(sources)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual([
      expect.stringContaining("Acme tablets label"),
      expect.stringContaining("Acme tablets label (2019)"),
    ]);
  });

  it("summarises progress in a polite live region", () => {
    const region = show(FAN_OUT_RUN);
    const live = region.querySelector('[aria-live="polite"]');
    expect(live).toHaveTextContent("Searching the documents: 2 of 3 searches done.");
  });

  it("is keyboard-reachable: each node opens its details, and the steps collapse", async () => {
    const user = userEvent.setup();
    show(ANSWERED_RUN);
    await user.tab();
    const technical = screen.getByRole("button", { name: "Technical details" });
    expect(technical).toHaveFocus();
    await user.tab();
    const toggle = screen.getByRole("button", { name: "Hide steps" });
    expect(toggle).toHaveFocus();
    await user.tab();
    const classify = within(nodeItem("classify")).getByRole("button");
    expect(classify).toHaveFocus();
    expect(classify).toHaveAttribute("aria-expanded", "false");
    await user.keyboard("{Enter}");
    expect(classify).toHaveAttribute("aria-expanded", "true");
    expect(nodeItem("classify")).toHaveTextContent("As of 1 Jun 2024");

    await user.click(toggle);
    expect(screen.getByRole("button", { name: "Show steps" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.queryByRole("list", { name: "Agent steps" })).not.toBeInTheDocument();
  });
});

describe("AgentTimeline with reduced motion", () => {
  it("renders every node, branch and claim with no animation styles", () => {
    // Mount at the first event, then stream the rest in: everything below enters after
    // mount, which is exactly what would animate in (start hidden) with motion on.
    const events = [...FAN_OUT_MERGED, ...RE_RETRIEVE_DONE.slice(8)];
    const { rerender } = render(
      <AgentTimeline state={buildTimeline(events.slice(0, 1))} reducedMotion="always" />,
    );
    rerender(<AgentTimeline state={buildTimeline(events)} reducedMotion="always" />);
    const region = screen.getByRole("region", { name: "How this answer was built" });
    for (const name of [
      "classify",
      "cache",
      "plan",
      "subagent",
      "merge",
      "draft",
      "verify",
      "re_retrieve",
      "respond",
    ]) {
      expect(nodeItem(name)).toBeVisible();
    }
    expect(within(region).getByRole("list", { name: "Parallel searches" }).children).toHaveLength(
      3,
    );
    expect(within(region).getAllByRole("img", { name: /^Claim \d verified$/ })).toHaveLength(2);
    expect(region.querySelector('[aria-live="polite"]')).toHaveTextContent(
      "Done: 2 of 2 claims verified against the sources.",
    );

    // Nothing starts hidden, shifted or scaled for an entrance animation.
    for (const el of region.querySelectorAll<HTMLElement>("*")) {
      expect(el.style.opacity === "" || el.style.opacity === "1").toBe(true);
      expect(
        el.style.transform === "" || el.style.transform === "none",
        `${el.outerHTML.slice(0, 160)}`,
      ).toBe(true);
    }
  });
});
