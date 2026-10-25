import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { SiteHeader } from "@/components/site-header";
import { DemoBanner } from "@/components/demo/demo-banner";
import DemoPrompt from "@/demo/ai-prompt";
import { AsOfPicker } from "@/demo/ask-controls";
import { SiteHeader as DemoSiteHeader } from "@/demo/site-header";
import { setLastMatch } from "@/lib/demo/ask-store";
import { QUICK_START_URL } from "@/lib/demo/config";
import { matchAsk } from "@/lib/demo/match";
import { provideRecording } from "@/lib/demo/recording";

import { DEMO_RECORDING } from "../support/demo-fixtures";

beforeEach(() => provideRecording(DEMO_RECORDING));

describe("the demo banner", () => {
  it("says the answers are a recording, when, and links to the quick start", () => {
    render(<DemoBanner recordedAt="2026-10-25T12:00:00Z" />);
    const banner = screen.getByRole("region", { name: "Recorded demo" });
    expect(banner).toHaveTextContent(
      /Recorded demo — real answers captured from a live run on .*2026.*\. Run it yourself:/,
    );
    expect(screen.getByRole("link", { name: "quick start" })).toHaveAttribute(
      "href",
      QUICK_START_URL,
    );
  });

  it("is on every page of the demo build and absent from the normal header", () => {
    const { unmount } = render(<SiteHeader />);
    expect(screen.queryByTestId("demo-banner")).toBeNull();
    unmount();
    render(<DemoSiteHeader />);
    expect(screen.getByTestId("demo-banner")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Driftline/ })).toBeInTheDocument();
  });
});

describe("the demo Ask prompt", () => {
  it("offers every recorded question and asks a picked one at its recorded date", async () => {
    const asked: string[] = [];
    const dates: (Date | null)[] = [];
    render(
      <>
        <AsOfPicker value={null} onChange={(d) => dates.push(d)} />
        <DemoPrompt onSubmit={(q) => asked.push(q)} />
      </>,
    );
    const chips = await screen.findAllByTestId("demo-suggestion");
    expect(chips).toHaveLength(DEMO_RECORDING.asks.length);

    await userEvent.click(chips[0]);
    await waitFor(() => expect(asked).toEqual([DEMO_RECORDING.asks[0].request.question]));
    expect(dates).toHaveLength(1);
    expect(dates[0]?.getFullYear()).toBe(2024);
    expect(dates[0]?.getMonth()).toBe(5);
    expect(dates[0]?.getDate()).toBe(1);
  });

  it("disables the suggestions while an answer streams", async () => {
    render(<DemoPrompt responding onSubmit={() => undefined} />);
    for (const chip of await screen.findAllByTestId("demo-suggestion")) {
      expect(chip).toBeDisabled();
    }
  });

  it("says when a typed question was answered by the closest recorded one", async () => {
    render(<DemoPrompt onSubmit={() => undefined} />);
    expect(screen.queryByTestId("demo-match-note")).toBeNull();
    const asked = "max metformin dose";
    const match = matchAsk(asked, null, DEMO_RECORDING.asks, DEMO_RECORDING.recorded_at)!;
    act(() => setLastMatch({ ...match, asked: { question: asked, as_of: null } }));
    expect(screen.getByTestId("demo-match-note")).toHaveTextContent(
      "Showing the recorded answer to the closest demo question: “What is the maximum daily dose of metformin?”",
    );
  });
});
