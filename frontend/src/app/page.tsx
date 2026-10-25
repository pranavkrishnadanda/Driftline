import Link from "next/link";

export default function Home() {
  return (
    <section className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center gap-4 px-4 py-24">
      <h1 className="font-heading text-4xl font-semibold tracking-tight">
        Answers as of any date.
      </h1>
      <p className="max-w-xl text-lg text-muted-foreground">
        Driftline answers questions from the document versions that were in force on the date you
        ask about, cites the exact quotes, and alerts you when a newer version changes the answer.
      </p>
      <p>
        <Link
          href="/ask"
          className="inline-flex h-9 items-center rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          Ask a question
        </Link>
      </p>
    </section>
  );
}
