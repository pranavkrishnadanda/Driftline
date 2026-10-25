/**
 * Server parts of the Timeline routes that read runtime data (`params`, `searchParams`).
 * With Cache Components they render inside a `<Suspense>` boundary in the page, so the
 * page's static shell prerenders and these stream in at request time.
 */
import { notFound, redirect } from "next/navigation";

import { DocumentPicker } from "@/components/timeline/document-picker";
import { DocumentTimelineView } from "@/components/timeline/document-timeline-view";
import { parseTenants } from "@/lib/ask/format";
import { parseDocumentId, timelineHref } from "@/lib/timeline/recent";

type Query = Promise<Record<string, string | string[] | undefined>>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function tenantFrom(query: Awaited<Query>): string {
  return first(query.tenant)?.trim() || parseTenants(process.env.NEXT_PUBLIC_DRIFTLINE_TENANTS)[0];
}

/**
 * The picker. Its paste form submits to /timeline as a plain GET (`?document=&tenant=`),
 * so a valid id redirects to the document's timeline without client-side routing.
 */
export async function TimelinePicker({ searchParams }: { searchParams: Query }) {
  const query = await searchParams;
  const tenants = parseTenants(process.env.NEXT_PUBLIC_DRIFTLINE_TENANTS);
  const tenant = tenantFrom(query);
  const pasted = first(query.document)?.trim();

  if (pasted) {
    const id = parseDocumentId(pasted);
    if (id) redirect(timelineHref(id, tenant));
    return <DocumentPicker tenants={tenants} initialTenant={tenant} invalidId={pasted} />;
  }
  return <DocumentPicker tenants={tenants} initialTenant={tenant} />;
}

/** A document's timeline; `?tenant=` picks the tenant. A malformed id is a 404. */
export async function DocumentTimelineRoute({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Query;
}) {
  const { id } = await params;
  const documentId = parseDocumentId(decodeURIComponent(id));
  if (!documentId) notFound();
  const tenant = tenantFrom(await searchParams);
  return (
    <DocumentTimelineView key={`${tenant}:${documentId}`} documentId={documentId} tenant={tenant} />
  );
}
