import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import {
  FinalAnswer,
  ReviewPending,
  StreamingAnswer,
  isReviewWaiting,
} from "@/components/ask/answer";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { AnswerSchema, Citation } from "@/lib/api/client";

import {
  ANSWERED,
  ANSWERED_TEXT,
  LAST_STEP,
  REVIEW_WAITING_STEP,
  insufficientAnswer,
} from "../support/ask-fixtures";

function renderFinal(answer: AnswerSchema) {
  return render(
    <TooltipProvider>
      <FinalAnswer answer={answer} />
    </TooltipProvider>,
  );
}

describe("StreamingAnswer", () => {
  it("shows the streamed text and the step the agent is on", () => {
    render(<StreamingAnswer text={ANSWERED_TEXT} step={LAST_STEP} />);
    expect(screen.getByText(ANSWERED_TEXT)).toBeInTheDocument();
    expect(screen.getByText(/Finishing/)).toBeInTheDocument();
  });

  it("is never an empty bubble before the first token", () => {
    render(<StreamingAnswer text="" step={null} />);
    expect(screen.getByText(/Getting started/)).toBeInTheDocument();
  });
});

describe("ReviewPending", () => {
  it("says the answer waits for a human reviewer, with the reason and the draft", () => {
    render(<ReviewPending text={ANSWERED_TEXT} step={REVIEW_WAITING_STEP} />);
    const pending = screen.getByRole("region", { name: "Waiting for human review" });
    expect(
      within(pending).getByRole("heading", { name: "Waiting for human review" }),
    ).toBeInTheDocument();
    expect(pending).toHaveTextContent("confidence is below the review threshold");
    expect(pending).toHaveTextContent(ANSWERED_TEXT);
    // Not an error and not a busy spinner.
    expect(pending).not.toHaveAttribute("aria-busy", "true");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("explains a regenerated watched answer and works before any token", () => {
    render(
      <ReviewPending
        text=""
        step={{ ...REVIEW_WAITING_STEP, detail: { reason: "watched_answer" } }}
      />,
    );
    const pending = screen.getByRole("region", { name: "Waiting for human review" });
    expect(pending).toHaveTextContent("regenerated after its sources changed");
    expect(pending).not.toHaveTextContent("Draft under review");
  });

  it("recognises only the review node's waiting step", () => {
    expect(isReviewWaiting(REVIEW_WAITING_STEP)).toBe(true);
    expect(isReviewWaiting(LAST_STEP)).toBe(false);
    expect(isReviewWaiting({ ...REVIEW_WAITING_STEP, status: "completed" })).toBe(false);
    expect(isReviewWaiting(null)).toBe(false);
  });
});

describe("FinalAnswer: answered", () => {
  it("renders the answer and each claim with its verification state", () => {
    renderFinal(ANSWERED);
    expect(screen.getByText(ANSWERED.answer)).toBeInTheDocument();
    const claims = screen.getByRole("list", { name: "Claims" });
    const [claim] = within(claims).getAllByRole("listitem");
    expect(claim).toHaveTextContent(ANSWERED.claims![0].text);
    expect(claim).toHaveTextContent("Verified against the source");
    // The sources the answer rests on, as cards under it.
    const sources = screen.getByRole("list", { name: "Sources" });
    expect(sources).toHaveTextContent("Lipitor (atorvastatin calcium) label");
    expect(sources).toHaveTextContent("v2");
    expect(sources).toHaveTextContent("Warnings and Precautions › Liver Dysfunction");
    expect(sources).toHaveTextContent("In force from 15 Apr 2024");
  });

  it("says how confident it is in words, with the score on hover", async () => {
    const user = userEvent.setup();
    renderFinal(ANSWERED);
    const badge = screen.getByRole("button", { name: /confidence/ });
    expect(badge).toHaveTextContent(/^(High|Medium|Low) confidence$/);
    await user.hover(badge);
    expect(await screen.findByRole("tooltip")).toHaveTextContent(/Confidence score \d+%/);
  });

  it("shows the exact quote with title, version, section and valid-from when a citation is focused", async () => {
    const user = userEvent.setup();
    // No nearest_sources: an answered answer's citations carry their own metadata.
    renderFinal({ ...ANSWERED, nearest_sources: [] });

    await user.tab(); // the confidence badge
    await user.tab();
    const chip = screen.getByRole("button", { name: /Citation 1/ });
    expect(chip).toHaveFocus();
    expect(chip).toHaveAccessibleName("Citation 1: Lipitor (atorvastatin calcium) label");

    const tip = await screen.findByRole("tooltip");
    expect(tip).toHaveTextContent("Check ALT monthly during therapy.");
    expect(tip).toHaveTextContent("Lipitor (atorvastatin calcium) label");
    expect(tip).toHaveTextContent("Warnings and Precautions › Liver Dysfunction");
    expect(tip).toHaveTextContent("v2");
    expect(tip).toHaveTextContent("In force from 15 Apr 2024");
  });

  it("shows the valid-to of a superseded cited version", async () => {
    const user = userEvent.setup();
    const cite = (c: Citation): Citation => ({ ...c, valid_to: "2025-01-01T00:00:00Z" });
    renderFinal({
      ...ANSWERED,
      claims: ANSWERED.claims!.map((claim) => ({ ...claim, citations: claim.citations.map(cite) })),
    });

    await user.hover(screen.getByRole("button", { name: /Citation 1/ }));
    const tip = await screen.findByRole("tooltip");
    expect(tip).toHaveTextContent("In force 15 Apr 2024 to 1 Jan 2025");
  });

  it("shows the quote and version id for a citation stored without metadata", async () => {
    const user = userEvent.setup();
    // The API sends a citation stored before metadata existed with the fields null.
    const legacy = ({ chunk_id, version_id, quote }: Citation): Citation => ({
      chunk_id,
      version_id,
      quote,
      document_id: null,
      title: null,
      external_id: null,
      version_no: null,
      section_path: null,
      valid_from: null,
      valid_to: null,
    });
    renderFinal({
      ...ANSWERED,
      claims: ANSWERED.claims!.map((claim) => ({
        ...claim,
        citations: claim.citations.map(legacy),
      })),
    });

    await user.hover(screen.getByRole("button", { name: /Citation 1/ }));
    const tip = await screen.findByRole("tooltip");
    expect(tip).toHaveTextContent("Check ALT monthly during therapy.");
    expect(tip).toHaveTextContent("version 00000000…00a2");
    expect(tip).not.toHaveTextContent("In force");
  });

  it("shows degraded and cached badges only when the answer says so", () => {
    const { unmount } = renderFinal(ANSWERED);
    expect(screen.queryByText("Backup model")).not.toBeInTheDocument();
    expect(screen.queryByText("Saved answer")).not.toBeInTheDocument();
    unmount();

    renderFinal({ ...ANSWERED, degraded: true, cached: true });
    expect(screen.getByText("Backup model")).toBeInTheDocument();
    expect(screen.getByText("Saved answer")).toBeInTheDocument();
  });

  it("states the as-of date the answer was computed for", () => {
    renderFinal(ANSWERED);
    expect(screen.getByText(/As of 1 Jun 2024/)).toBeInTheDocument();
  });
});

describe("FinalAnswer: insufficient evidence", () => {
  it("refuses explicitly and lists the nearest sources", () => {
    renderFinal(insufficientAnswer());
    expect(
      screen.getByRole("heading", { name: "Not enough evidence to answer" }),
    ).toBeInTheDocument();
    const sources = screen.getByRole("list", { name: "Nearest sources" });
    const items = within(sources).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Acme tablets label");
    expect(items[0]).toHaveTextContent("v3");
    expect(items[0]).toHaveTextContent("In force from 14 Feb 2023");
    expect(items[1]).toHaveTextContent("Acme tablets label (2019)");
    expect(items[1]).toHaveTextContent("In force 1 May 2019 to 14 Feb 2023");
  });

  it("still says why, and that no sources were near, when the answer is empty", () => {
    renderFinal(insufficientAnswer({ nearest_sources: [] }));
    expect(
      screen.getByRole("heading", { name: "Not enough evidence to answer" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/didn't find evidence in force on 1 Jun 2024/)).toBeInTheDocument();
    expect(screen.getByText(/No nearby sources/)).toBeInTheDocument();
  });

  it("shows a refusal with the agent's reason", () => {
    renderFinal(
      insufficientAnswer({ status: "refused", answer: "That question is out of scope." }),
    );
    expect(
      screen.getByRole("heading", { name: "Driftline declined to answer" }),
    ).toBeInTheDocument();
    expect(screen.getByText("That question is out of scope.")).toBeInTheDocument();
  });
});
