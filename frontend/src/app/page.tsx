import { Mark, MarkerText } from "@/components/kokonutui/marker-text";
import SlideTextButton from "@/components/kokonutui/slide-text-button";
import { AsOfBoard } from "@/components/landing/as-of-board";
import { DriftHero } from "@/components/landing/drift-hero";
import { FeatureCards } from "@/components/landing/feature-cards";

export default function Home() {
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-20 px-4 py-16 sm:py-20">
      <section className="grid items-center gap-10 lg:grid-cols-[1fr_1.1fr]">
        <div className="flex flex-col gap-6">
          <p className="text-sm font-semibold text-brand">
            Answers you can trust, for documents that change
          </p>
          <MarkerText
            as="h1"
            className="font-heading text-4xl leading-tight font-semibold tracking-tight text-balance sm:text-5xl"
          >
            Answers <Mark type="highlight">as of any date</Mark>, from the version in force{" "}
            <Mark type="underline">then</Mark>.
          </MarkerText>
          <p className="max-w-xl text-lg text-muted-foreground">
            Driftline keeps every version of your documents. It answers a question from the versions
            that were in force on the date you ask about, cites the exact quotes, and alerts you
            when a newer version changes the answer.
          </p>
          <AsOfBoard />
          <div className="flex flex-wrap gap-3">
            <SlideTextButton href="/ask" text="Try Ask" hoverText="Ask a question" />
            <SlideTextButton
              href="/drift"
              text="View drift inbox"
              hoverText="See live alerts"
              variant="ghost"
            />
          </div>
        </div>
        <DriftHero />
      </section>

      <section aria-labelledby="features-heading" className="flex flex-col gap-8">
        <div className="flex flex-col gap-2">
          <h2 id="features-heading" className="font-heading text-2xl font-semibold tracking-tight">
            What it does
          </h2>
          <p className="max-w-2xl text-muted-foreground">
            Ask questions about any date, see how each document changed, and hear about it when an
            answer goes out of date. Turn a card over to see how each part works.
          </p>
        </div>
        <FeatureCards />
      </section>
    </div>
  );
}
