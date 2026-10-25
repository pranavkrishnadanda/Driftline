import Link from "next/link";

/** A placeholder for a view that a later phase builds, so the navigation never 404s. */
export function ComingSoon({ title, summary }: { title: string; summary: string }) {
  return (
    <section className="mx-auto flex w-full max-w-3xl flex-col gap-3 px-4 py-16">
      <h1 className="font-heading text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="text-muted-foreground">{summary}</p>
      <p className="text-sm text-muted-foreground">This view is coming soon.</p>
      <p>
        <Link
          href="/ask"
          className="text-sm font-medium underline underline-offset-4 focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          Ask a question in the meantime
        </Link>
      </p>
    </section>
  );
}
