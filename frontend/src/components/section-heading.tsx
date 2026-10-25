"use client";

import { Mark, MarkerText } from "@/components/kokonutui/marker-text";

/**
 * A view's title, underlined by a Kokonut marker stroke (`@kokonutui/marker-text`) that
 * draws once when it scrolls into view; under reduced motion it is simply there.
 */
export function SectionHeading({ children }: { children: string }) {
  return (
    <MarkerText as="h1" className="font-heading text-2xl font-semibold tracking-tight">
      <Mark type="underline">{children}</Mark>
    </MarkerText>
  );
}
