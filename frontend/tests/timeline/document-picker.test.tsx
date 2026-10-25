import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import TimelinePage from "@/app/(app)/timeline/page";
import { DocumentPicker } from "@/components/timeline/document-picker";
import { DocumentTimelineRoute, TimelinePicker } from "@/components/timeline/routes";
import { createApiClient, type DriftEvent } from "@/lib/api/client";
import { parseDocumentId } from "@/lib/timeline/recent";

import { closedPortUrl, startApiServer, type ApiServer } from "../support/api-server";
import { DOC_ID, OTHER_DOC_ID } from "../support/version-timeline-fixtures";

let api: ApiServer | undefined;

afterEach(async () => {
  await api?.close();
  api = undefined;
});

function event(id: string, documentId: string, title: string | null, at: string): DriftEvent {
  return {
    id,
    answer_id: "c0000000-0000-4000-8000-000000000001",
    claim_idx: 0,
    verdict: "changed",
    old_version_id: null,
    new_version_id: null,
    document_id: documentId,
    document_title: title,
    created_at: at,
  };
}

describe("DocumentPicker", () => {
  it("lists recently drifted documents for the tenant, linking to their timelines", async () => {
    api = await startApiServer({
      "GET /v1/drift/events": {
        status: 200,
        json: {
          events: [
            event("e1", DOC_ID, "Metformin label", "2026-02-03T00:00:00Z"),
            event("e2", OTHER_DOC_ID, null, "2026-02-02T00:00:00Z"),
          ],
        },
      },
    });
    render(<DocumentPicker tenants={["demo"]} client={createApiClient({ baseUrl: api.url })} />);

    expect(screen.getByRole("heading", { level: 1, name: "Timeline" })).toBeInTheDocument();
    const list = await screen.findByRole("list", { name: "Recently drifted documents" });
    const links = within(list).getAllByRole("link");
    expect(links.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["Metformin label", `/documents/${DOC_ID}?tenant=demo`],
      [OTHER_DOC_ID, `/documents/${OTHER_DOC_ID}?tenant=demo`],
    ]);
    expect(api.requests[0].url).toBe("/v1/drift/events?tenant=demo&limit=200");
  });

  it("explains an empty list and keeps the paste form", async () => {
    api = await startApiServer({ "GET /v1/drift/events": { status: 200, json: { events: [] } } });
    render(<DocumentPicker tenants={["demo"]} client={createApiClient({ baseUrl: api.url })} />);
    expect(await screen.findByText(/No drift events yet/)).toBeInTheDocument();
    const form = screen.getByRole("form", { name: "Open a document" });
    expect(form).toHaveAttribute("action", "/timeline");
    expect(form).toHaveAttribute("method", "get");
    expect(within(form).getByRole("textbox", { name: "Document id" })).toHaveAttribute("name", "document");
  });

  it("reports an unreachable gateway without hiding the paste form", async () => {
    render(
      <DocumentPicker tenants={["demo"]} client={createApiClient({ baseUrl: await closedPortUrl() })} />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Driftline API unreachable");
    expect(screen.getByRole("textbox", { name: "Document id" })).toBeInTheDocument();
  });

  it("shows why a pasted id was rejected", () => {
    render(
      <DocumentPicker
        tenants={["demo"]}
        client={createApiClient({ baseUrl: "http://127.0.0.1:9" })}
        invalidId="not-a-uuid"
      />,
    );
    expect(screen.getByRole("textbox", { name: "Document id" })).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText(/“not-a-uuid” is not a document id/)).toBeInTheDocument();
  });
});

describe("parseDocumentId", () => {
  it("accepts a UUID with surrounding space or braces and normalises its case", () => {
    expect(parseDocumentId(` ${DOC_ID.toUpperCase()} `)).toBe(DOC_ID);
    expect(parseDocumentId(`{${DOC_ID}}`)).toBe(DOC_ID);
    expect(parseDocumentId("abc")).toBeNull();
    expect(parseDocumentId("")).toBeNull();
  });
});

describe("/timeline route", () => {
  it("redirects a pasted document id to its timeline", async () => {
    const error = await TimelinePicker({
      searchParams: Promise.resolve({ document: DOC_ID.toUpperCase(), tenant: "pharma" }),
    }).catch((e: unknown) => e);
    expect(error).toMatchObject({
      digest: expect.stringContaining(`/documents/${DOC_ID}?tenant=pharma`),
    });
  });

  it("hands an invalid id back to the picker", async () => {
    const element = await TimelinePicker({ searchParams: Promise.resolve({ document: "nope" }) });
    expect(element.props).toMatchObject({ invalidId: "nope", initialTenant: "demo" });
  });

  it("streams the picker behind a Suspense fallback with the Timeline heading", () => {
    const element = TimelinePage({
      params: Promise.resolve({}),
      searchParams: Promise.resolve({}),
    });
    render(element.props.fallback);
    expect(screen.getByRole("heading", { level: 1, name: "Timeline" })).toBeInTheDocument();
  });
});

describe("/documents/[id] route", () => {
  it("treats a malformed id as not found", async () => {
    const error = await DocumentTimelineRoute({
      params: Promise.resolve({ id: "not-a-uuid" }),
      searchParams: Promise.resolve({}),
    }).catch((e: unknown) => e);
    expect(error).toMatchObject({ digest: expect.stringContaining("404") });
  });

  it("loads the document for the tenant in the query", async () => {
    const element = await DocumentTimelineRoute({
      params: Promise.resolve({ id: DOC_ID }),
      searchParams: Promise.resolve({ tenant: "pharma" }),
    });
    expect(element.props).toMatchObject({ documentId: DOC_ID, tenant: "pharma" });
  });
});
