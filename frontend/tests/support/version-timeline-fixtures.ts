/**
 * Timeline fixtures shaped exactly like `GET /v1/documents/{id}/timeline`
 * (backend/src/driftline/gateway/drift.py): `diff_from_prev` is the section-path
 * classification from `driftline.ingest.hashing.diff_sections`, null on version 1.
 */
import type { DocumentTimeline, TimelineVersion } from "@/lib/api/client";

export const DOC_ID = "0b6f7e52-6a49-4d0e-9a3c-2f5d1c7e8a10";
export const OTHER_DOC_ID = "5a1d3c9e-1b2f-4e6a-8c7d-9e0f1a2b3c4d";
export const OLD_DOC_ID = "9f8e7d6c-5b4a-4392-8170-6f5e4d3c2b1a";

export function version(
  no: number,
  validFrom: string,
  validTo: string | null,
  diff: TimelineVersion["diff_from_prev"] = null,
): TimelineVersion {
  return {
    version_id: `00000000-0000-4000-8000-00000000000${no}`,
    version_no: no,
    version_key: `rev-${no}`,
    valid_from: validFrom,
    valid_to: validTo,
    diff_from_prev: diff,
    created_at: validFrom,
  };
}

export const TIMELINE: DocumentTimeline = {
  document_id: DOC_ID,
  external_id: "label/metformin",
  title: "Metformin label",
  versions: [
    version(1, "2026-01-01T00:00:00Z", "2026-01-11T00:00:00Z"),
    version(2, "2026-01-11T00:00:00Z", "2026-01-31T00:00:00Z", {
      added: ["B > Renal"],
      removed: [],
      changed: ["A > Dose"],
      unchanged: ["A > Intro"],
    }),
    version(3, "2026-01-31T00:00:00Z", null, {
      added: [],
      removed: ["B > Renal"],
      changed: ["A > Intro"],
      unchanged: ["A > Dose"],
    }),
  ],
  relations: {
    outgoing: [
      {
        id: "a0000000-0000-4000-8000-000000000001",
        kind: "supersedes",
        status: "accepted",
        confidence: 0.92,
        src_version_id: "00000000-0000-4000-8000-000000000002",
        document_id: OLD_DOC_ID,
        document_title: "Metformin label (2019)",
      },
    ],
    incoming: [
      {
        id: "a0000000-0000-4000-8000-000000000002",
        kind: "amends",
        status: "pending",
        confidence: 0.61,
        src_version_id: "11111111-0000-4000-8000-000000000001",
        document_id: OTHER_DOC_ID,
        document_title: null,
      },
    ],
  },
};
