"use client";

/**
 * A departure board (`@kokonutui/split-flap-text`) cycling through the hero document's
 * versions. Under reduced motion it holds the latest version instead of flipping.
 */
import SplitFlapText from "@/components/kokonutui/split-flap-text";
import { usePrefersReducedMotion } from "@/hooks/use-prefers-reduced-motion";
import { HERO_VERSIONS, asOfBoard } from "@/lib/landing/hero";

const BOARDS = HERO_VERSIONS.map(asOfBoard);

export function AsOfBoard({ reducedMotion }: { reducedMotion?: boolean }) {
  const prefersReduced = usePrefersReducedMotion();
  const reduced = reducedMotion ?? prefersReduced;
  return (
    // `data-ambient`: a looping decoration; the browser checks don't wait for it to stop.
    <div data-ambient>
      <SplitFlapText
        {...(reduced ? { text: BOARDS.at(-1) } : { words: BOARDS, interval: 2800 })}
        length={Math.max(...BOARDS.map((b) => b.length))}
        className="text-base sm:text-2xl"
        tileClassName="bg-foreground text-background"
      />
    </div>
  );
}
