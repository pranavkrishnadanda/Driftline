import { Mark, MarkerText } from "@/components/kokonutui/marker-text";
import SlideTextButton from "@/components/kokonutui/slide-text-button";
import { AsOfBoard } from "@/components/landing/as-of-board";
import { DriftHero } from "@/components/landing/drift-hero";
import { FeatureCards } from "@/components/landing/feature-cards";

const STACK = ["FastAPI", "Postgres + pgvector", "Redis Streams", "LangGraph", "Claude", "Next.js"];

export default function Home() {
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-20 px-4 py-16 sm:py-20">
      <section className="grid items-center gap-10 lg:grid-cols-[1fr_1.1fr]">
        <div className="flex flex-col gap-6">
          <p className="text-sm font-medium text-muted-foreground">
            A version-aware knowledge engine
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
            Four parts, all built and running in this repository. Turn a card over (click it, or
            focus it and press Enter) to see how it is built.
          </p>
        </div>
        <FeatureCards />
      </section>

      <section aria-labelledby="stack-heading" className="flex flex-col gap-3">
        <h2 id="stack-heading" className="font-heading text-lg font-semibold tracking-tight">
          Built with
        </h2>
        <ul className="flex flex-wrap gap-2">
          {STACK.map((name) => (
            <li
              key={name}
              className="rounded-full border border-border px-3 py-1 text-sm text-muted-foreground"
            >
              {name}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
