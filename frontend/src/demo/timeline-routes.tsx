/**
 * Demo build only (next.config.ts aliases `@/components/timeline/routes` here). A static
 * export has no query string at build time, so these never read `searchParams`: the demo
 * has one recorded tenant, and its picker lists the recorded documents.
 */
import { notFound } from "next/navigation";

import { DemoDocuments } from "../components/demo/demo-documents";
import { SectionHeading } from "../components/section-heading";
import { DocumentTimelineView } from "../components/timeline/document-timeline-view";
import { parseTenants } from "../lib/ask/format";
import { parseDocumentId } from "../lib/timeline/recent";

type Query = Promise<Record<string, string | string[] | undefined>>;

function demoTenant(): string {
  return parseTenants(process.env.NEXT_PUBLIC_DRIFTLINE_TENANTS)[0];
}

export async function TimelinePicker(_props: { searchParams: Query }) {
  return (
    <section className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-4 py-10">
      <header className="flex flex-col gap-2">
        <SectionHeading>Timeline</SectionHeading>
        <p className="text-muted-foreground">
          See every version of a document, what changed between them, and which documents replace or
          amend it.
        </p>
      </header>
      <DemoDocuments tenant={demoTenant()} />
    </section>
  );
}

export async function DocumentTimelineRoute({
  params,
}: {
  params: Promise<{ id: string }>;
  searchParams: Query;
}) {
  const { id } = await params;
  const documentId = parseDocumentId(decodeURIComponent(id));
  if (!documentId) notFound();
  const tenant = demoTenant();
  return (
    <DocumentTimelineView key={`${tenant}:${documentId}`} documentId={documentId} tenant={tenant} />
  );
}
