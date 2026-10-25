/**
 * Version timeline against the real backend stack (deploy/compose with DRIFTLINE_LLM_OFFLINE=true).
 *
 *   DRIFTLINE_E2E_API          the gateway URL, e.g. http://localhost:8010 (required; the spec
 *                              skips without it). Start the frontend with NEXT_PUBLIC_DRIFTLINE_API
 *                              set to the same URL.
 *   DRIFTLINE_E2E_TENANT       tenant (default "demo").
 *   DRIFTLINE_E2E_DOCUMENT_ID  a document with at least two versions. Without it the spec
 *                              uses the first document named by the tenant's drift events.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext } from "@playwright/test";

const API = process.env.DRIFTLINE_E2E_API;
const TENANT = process.env.DRIFTLINE_E2E_TENANT ?? "demo";

test.skip(
  !API,
  "DRIFTLINE_E2E_API is not set: this spec needs the real backend stack (Compose with " +
    "DRIFTLINE_LLM_OFFLINE=true). See the header of timeline.spec.ts.",
);

interface Timeline {
  versions: { version_no: number; valid_from: string }[];
}

async function findDocument(request: APIRequestContext): Promise<{ id: string; timeline: Timeline } | null> {
  const fromEnv = process.env.DRIFTLINE_E2E_DOCUMENT_ID;
  let ids: string[] = fromEnv ? [fromEnv] : [];
  if (!ids.length) {
    const res = await request.get(`${API}/v1/drift/events?tenant=${TENANT}&limit=200`);
    expect(res.ok(), "listing drift events failed").toBe(true);
    const { events } = (await res.json()) as { events: { document_id: string | null }[] };
    ids = [...new Set(events.map((e) => e.document_id).filter((id): id is string => !!id))];
  }
  for (const id of ids) {
    const res = await request.get(`${API}/v1/documents/${id}/timeline?tenant=${TENANT}`);
    if (!res.ok()) continue;
    const timeline = (await res.json()) as Timeline;
    if (timeline.versions.length >= 2) return { id, timeline };
  }
  return null;
}

test.describe("Version timeline (real backend)", () => {
  test("the Timeline nav entry opens the document picker", async ({ page }) => {
    await page.goto("/ask");
    await page.getByRole("navigation", { name: "Views" }).getByRole("link", { name: "Timeline" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Timeline" })).toBeVisible();
    await expect(page.getByRole("form", { name: "Open a document" })).toBeVisible();
  });

  test("scrubbing selects a version and updates the diff", async ({ page, request }) => {
    const doc = await findDocument(request);
    test.skip(!doc, `no document with two or more versions in tenant ${TENANT}`);
    const { id, timeline } = doc!;
    const nos = timeline.versions.map((v) => v.version_no).sort((a, b) => a - b);
    const latest = nos[nos.length - 1];

    await page.goto(`/documents/${id}?tenant=${TENANT}`);
    const slider = page.getByRole("slider", { name: "Version" });
    await expect(slider).toHaveAttribute("aria-valuenow", String(latest));
    await expect(
      page.getByRole("heading", { level: 2, name: `Changes in v${latest} since v${nos[nos.length - 2]}` }),
    ).toBeVisible();

    // Drag the scrubber from the right end of the axis to the left end.
    const box = (await slider.boundingBox())!;
    const y = box.y + box.height / 2;
    await page.mouse.move(box.x + box.width - 2, y);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2, y, { steps: 8 });
    await page.mouse.move(box.x + 2, y, { steps: 8 });
    await page.mouse.up();

    await expect(slider).toHaveAttribute("aria-valuenow", String(nos[0]));
    await expect(page.getByRole("heading", { level: 2, name: `v${nos[0]} is the first version` })).toBeVisible();

    // The keyboard scrubs too.
    await slider.press("ArrowRight");
    await expect(slider).toHaveAttribute("aria-valuenow", String(nos[1]));
    await expect(
      page.getByRole("heading", { level: 2, name: `Changes in v${nos[1]} since v${nos[0]}` }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: new RegExp(`^v${nos[1]}`) })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    const results = await new AxeBuilder({ page }).analyze();
    const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
  });
});
