/**
 * Drift inbox and review queue against the real backend stack (deploy/compose with
 * DRIFTLINE_LLM_OFFLINE=true): watch an answer, ingest a new version of the document it
 * cites through the backend CLI, see the alert arrive live, then resolve it.
 *
 *   DRIFTLINE_E2E_API             the gateway URL, e.g. http://localhost:8010 (required;
 *                                 the spec skips without it). Start the frontend with
 *                                 NEXT_PUBLIC_DRIFTLINE_API set to the same URL.
 *   DRIFTLINE_E2E_TENANT          tenant (default "demo"); must be the first entry of
 *                                 NEXT_PUBLIC_DRIFTLINE_TENANTS, or the only one.
 *   DRIFTLINE_E2E_COMPOSE         compose file (default ../deploy/compose/docker-compose.yml).
 *   DRIFTLINE_E2E_DRIFT_QUESTION  a question the fixture document below answers.
 */
import { execFileSync } from "node:child_process";
import path from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const API = process.env.DRIFTLINE_E2E_API;
const TENANT = process.env.DRIFTLINE_E2E_TENANT ?? "demo";
const COMPOSE =
  process.env.DRIFTLINE_E2E_COMPOSE ??
  path.resolve(__dirname, "../../../deploy/compose/docker-compose.yml");
const QUESTION =
  process.env.DRIFTLINE_E2E_DRIFT_QUESTION ??
  "What is the maximum daily dose of Driftolol for adults?";
const TITLE = "Driftolol dosing (e2e)";

test.skip(
  !API,
  "DRIFTLINE_E2E_API is not set: this spec needs the real backend stack (Compose with " +
    "DRIFTLINE_LLM_OFFLINE=true, the agent, ingest and drift workers). See the header of " +
    "drift.spec.ts.",
);

function version(dose: string, frequency: string): string {
  return `# ${TITLE}\n\n## Adults\n\nThe maximum daily dose of Driftolol for adults is ${dose}, taken ${frequency}.\n`;
}

function compose(args: string[], input?: string): string {
  return execFileSync("docker", ["compose", "-f", COMPOSE, ...args], {
    input,
    encoding: "utf8",
    timeout: 60_000,
  });
}

/** Write the file into the shared uploads volume and queue it for ingestion. */
function ingest(externalId: string, content: string): void {
  compose(
    ["exec", "-T", "ingest-worker", "sh", "-c", `cat > "/data/uploads/${externalId}"`],
    content,
  );
  compose([
    "exec",
    "-T",
    "ingest-worker",
    "python",
    "-m",
    "driftline.ingest",
    "enqueue",
    "--tenant",
    TENANT,
    "--kind",
    "upload",
    "--external-id",
    externalId,
  ]);
}

/** Ask until the newly ingested document answers, and return the stored answer's id. */
async function answerId(request: APIRequestContext): Promise<string> {
  let last = "no answer yet";
  for (let attempt = 0; attempt < 20; attempt++) {
    const asked = await request.post(`${API}/v1/ask`, {
      data: { question: QUESTION, tenant: TENANT },
    });
    expect(asked.ok(), await asked.text()).toBe(true);
    const { job_id: jobId } = (await asked.json()) as { job_id: string };
    for (let poll = 0; poll < 60; poll++) {
      const job = (await (await request.get(`${API}/v1/jobs/${jobId}`)).json()) as {
        status: string;
        answer?: { status: string; answer_id?: string | null } | null;
      };
      if (job.answer?.status === "answered" && job.answer.answer_id) return job.answer.answer_id;
      if (job.answer || ["failed", "needs_review"].includes(job.status)) {
        last = `job ${job.status}, answer ${job.answer?.status ?? "none"}`;
        break;
      }
      await new Promise((r) => setTimeout(r, 1000));
    }
    // The document may still be embedding: ask again shortly.
    await new Promise((r) => setTimeout(r, 3000));
  }
  throw new Error(
    `the fixture question never got an answer (${last}); check DRIFTLINE_E2E_DRIFT_QUESTION`,
  );
}

async function expectAxeClean(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
}

test.describe("Drift inbox and review queue (real backend)", () => {
  test.beforeAll(async ({ request }) => {
    const health = await request.get(`${API}/healthz`);
    expect(health.ok(), `gateway at ${API} is not healthy`).toBe(true);
  });

  test("an alert arrives live after a new version lands, and can be resolved", async ({
    page,
    request,
  }) => {
    test.setTimeout(300_000);
    const externalId = `e2e-drift-${Date.now()}.md`;

    ingest(externalId, version("40 mg", "in two doses"));
    const answer = await answerId(request);
    const watched = await request.post(`${API}/v1/answers/${answer}/watch?tenant=${TENANT}`);
    expect(watched.ok(), await watched.text()).toBe(true);

    await page.goto("/drift");
    await expect(page.getByRole("status")).toHaveText("Live", { timeout: 30_000 });
    await expectAxeClean(page);

    ingest(externalId, version("20 mg", "once a day"));

    const alert = page
      .getByRole("list", { name: "Drift alerts" })
      .getByRole("article", { name: new RegExp(TITLE.replace(/[()]/g, "\\$&")) })
      .first();
    await expect(alert).toBeVisible({ timeout: 180_000 });
    await expect(alert.getByRole("group", { name: "Before and after" })).toContainText("20 mg");
    await expect(alert.getByText(/^(Broken|Changed|Still valid)$/)).toBeVisible();

    await alert.getByRole("button", { name: "Open answer" }).press("Enter");
    await expect(alert.getByRole("region", { name: "Answer details" })).toContainText(answer);
    await expectAxeClean(page);

    const sendToReview = alert.getByRole("link", { name: "Send to review" });
    if (!(await sendToReview.isVisible())) {
      test.info().annotations.push({
        type: "note",
        description: "the offline judge did not rule the answer broken; no review item to resolve",
      });
      return;
    }
    await sendToReview.click();
    await expect(page).toHaveURL(/\/review\?item=/);
    const item = page.locator("article:focus");
    await expect(item).toBeVisible();
    await expectAxeClean(page);
    await item.getByRole("button", { name: "Reject" }).click();
    await expect(page.getByRole("status")).toContainText("Rejected");
  });
});
