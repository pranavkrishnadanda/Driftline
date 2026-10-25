/**
 * The gateway has no "list documents" route, so the Timeline picker offers the
 * documents that drift events touched recently (`GET /v1/drift/events`).
 */
import type { DriftEvent } from "@/lib/api/client";

export interface RecentDocument {
  documentId: string;
  title: string | null;
  lastDriftAt: string;
  events: number;
}

/** One entry per document, in the order of its latest event (events arrive latest first). */
export function recentDocuments(events: readonly DriftEvent[]): RecentDocument[] {
  const byId = new Map<string, RecentDocument>();
  for (const event of events) {
    if (!event.document_id) continue;
    const known = byId.get(event.document_id);
    if (known) {
      known.events += 1;
      known.title ??= event.document_title;
      if (event.created_at > known.lastDriftAt) known.lastDriftAt = event.created_at;
    } else {
      byId.set(event.document_id, {
        documentId: event.document_id,
        title: event.document_title,
        lastDriftAt: event.created_at,
        events: 1,
      });
    }
  }
  return [...byId.values()].sort((a, b) => (a.lastDriftAt < b.lastDriftAt ? 1 : -1));
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** A pasted document id as the gateway expects it (a UUID), or null. */
export function parseDocumentId(raw: string): string | null {
  const id = raw
    .trim()
    .replace(/^\{(.*)\}$/, "$1")
    .toLowerCase();
  return UUID.test(id) ? id : null;
}

/** The timeline URL of a document for a tenant. */
export function timelineHref(documentId: string, tenant: string): string {
  return `/documents/${encodeURIComponent(documentId)}?tenant=${encodeURIComponent(tenant)}`;
}
