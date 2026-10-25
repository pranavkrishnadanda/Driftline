/**
 * Build-time helpers for the static demo export (server only): the recording is read from
 * `public/demo/recording.json` while `next build` runs.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import type { DemoRecording } from "./recording";

export function readRecordingFile(root: string = process.cwd()): DemoRecording {
  return JSON.parse(
    readFileSync(join(root, "public", "demo", "recording.json"), "utf8"),
  ) as DemoRecording;
}

/** One `/documents/[id]` page per recorded document timeline. */
export async function demoDocumentParams(): Promise<{ id: string }[]> {
  return Object.keys(readRecordingFile().timelines).map((id) => ({ id }));
}
