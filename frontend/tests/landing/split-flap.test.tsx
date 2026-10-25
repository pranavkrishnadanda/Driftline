import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SplitFlapText, { nextFlap } from "@/components/kokonutui/split-flap-text";
import { HERO_VERSIONS, asOfBoard } from "@/lib/landing/hero";

const BOARDS = HERO_VERSIONS.map(asOfBoard);
const CHARS = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:.-/&!?";
const DATE = /^V\d AS OF \d{4}-\d{2}-\d{2}$/;

/** The letters the board shows right now, read from its tiles. */
function boardText(container: HTMLElement): string {
  return [...container.querySelectorAll<HTMLElement>("[data-char]")]
    .map((tile) => tile.dataset.char)
    .join("")
    .trimEnd();
}

function trip(from: string, to: string): string[] {
  const seen = [from];
  for (let i = 0; i < 50 && seen.at(-1) !== to; i++) seen.push(nextFlap(seen.at(-1)!, to));
  return seen;
}

describe("split-flap drum", () => {
  it("reaches any letter from any letter within a few flaps", () => {
    for (const from of CHARS) {
      for (const to of CHARS) {
        const path = trip(from, to);
        expect(path.at(-1), `${from} -> ${to}`).toBe(to);
        expect(path.length - 1, `${from} -> ${to}`).toBeLessThanOrEqual(7);
      }
    }
  });

  it("turns a digit into another digit through digits only, so a date never shows `/` or `:`", () => {
    for (const from of "0123456789") {
      for (const to of "0123456789") {
        for (const c of trip(from, to)) expect("0123456789").toContain(c);
      }
    }
  });
});

describe("the as-of board", () => {
  it("settles on the exact next date when its text changes", async () => {
    const { container, rerender } = render(<SplitFlapText text={BOARDS[0]} />);
    expect(boardText(container)).toBe(BOARDS[0]);

    rerender(<SplitFlapText text={BOARDS[2]} />);
    await vi.waitFor(
      () => {
        expect(container.querySelector("[data-flipping]")).toBeNull();
        expect(boardText(container)).toBe(BOARDS[2]);
      },
      { timeout: 4000, interval: 50 },
    );
    expect(boardText(container)).toMatch(DATE);
  });

  it("settles on a valid date even when the text changes again mid-flip", async () => {
    const { container, rerender } = render(<SplitFlapText text={BOARDS[0]} />);
    rerender(<SplitFlapText text={BOARDS[1]} />);
    await new Promise((resolve) => setTimeout(resolve, 150));
    rerender(<SplitFlapText text={BOARDS[2]} />);
    await vi.waitFor(
      () => {
        expect(container.querySelector("[data-flipping]")).toBeNull();
        expect(boardText(container)).toBe(BOARDS[2]);
      },
      { timeout: 4000, interval: 50 },
    );
  });
});
