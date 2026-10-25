// Driftline ask load test: POST /v1/ask, then follow /v1/jobs/{id}/events (SSE) to the
// `final` event. Closed model: VUS virtual users each run ask -> final back to back, so
// the agent-stream backlog stays near VUS (429 backpressure starts above
// DRIFTLINE_ASK_MAX_PENDING, 200 by default).
//
// Needs the k6 binary from bench/k6/build.sh (k6 + xk6-sse): stock k6 only returns a
// response once it has ended, so it cannot time the first token.
//
// Metrics (all recorded, none filtered out):
//   ask_latency   POST sent -> `final` received (ms), completed asks only
//   ask_ttft      POST sent -> first `token` event (ms)
//   ask_completed asks that reached `final`
//   ask_rejected  POST answered 429 (backpressure); the VU then waits Retry-After
//   ask_failed    any other outcome: non-202 POST, `error` event, stream ended early
//
// Env: BASE_URL (http://localhost:8010), TENANT (demo), DURATION (180s),
//      VUS (32; bench/run.sh passes 4 per agent worker).
import http from "k6/http";
import { sleep } from "k6";
import { Counter, Trend } from "k6/metrics";
import sse from "k6/x/sse";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8010";
const TENANT = __ENV.TENANT || "demo";

// Each question is answerable from one document in bench/corpus.
const QUESTIONS = [
  "How often should ALT be checked during atorvastatin therapy?",
  "When should atorvastatin be stopped because of liver enzymes?",
  "What is the target INR range for atrial fibrillation on warfarin?",
  "How often should INR be checked once a warfarin patient is stable?",
  "At what eGFR is metformin contraindicated?",
  "What should happen to metformin around an iodinated contrast procedure?",
  "Which Pod Security level requires containers to run as non-root?",
  "Which Ingress API version should manifests migrate to after v1.22?",
  "What happens to a container that exceeds its memory limit?",
  "When is a pod in the Guaranteed quality of service class?",
];

const latency = new Trend("ask_latency", true);
const ttft = new Trend("ask_ttft", true);
const completed = new Counter("ask_completed");
const rejected = new Counter("ask_rejected");
const failed = new Counter("ask_failed");

export const options = {
  vus: Number(__ENV.VUS || 32),
  duration: __ENV.DURATION || "180s",
  summaryTrendStats: ["avg", "min", "med", "p(95)", "p(99)", "max"],
};

export default function () {
  const question = QUESTIONS[(__VU * 7 + __ITER) % QUESTIONS.length];
  const t0 = Date.now();
  const res = http.post(`${BASE_URL}/v1/ask`, JSON.stringify({ tenant: TENANT, question }), {
    headers: { "Content-Type": "application/json" },
    tags: { name: "POST /v1/ask" },
    responseCallback: http.expectedStatuses(202, 429),
  });
  if (res.status === 429) {
    rejected.add(1);
    sleep(Number(res.headers["Retry-After"] || 5));
    return;
  }
  if (res.status !== 202) {
    failed.add(1, { stage: "post", status: String(res.status) });
    sleep(1);
    return;
  }

  const job = res.json();
  let firstToken = null;
  let outcome = "stream_ended"; // until a terminal event says otherwise
  const stream = sse.open(
    `${BASE_URL}${job.events_url}`,
    { method: "GET", tags: { name: "GET /v1/jobs/{id}/events" } },
    (client) => {
      client.on("event", (event) => {
        if (event.name === "token" && firstToken === null) {
          firstToken = Date.now();
        } else if (event.name === "final") {
          outcome = "final";
          client.close();
        } else if (event.name === "error") {
          const data = JSON.parse(event.data);
          if (!data.retryable) {
            outcome = `error:${data.code}`;
            client.close();
          }
        }
      });
      client.on("error", (e) => {
        outcome = `sse_error:${e.error()}`;
      });
    },
  );

  if (outcome === "final") {
    const now = Date.now();
    completed.add(1);
    latency.add(now - t0);
    if (firstToken !== null) ttft.add(firstToken - t0);
  } else {
    failed.add(1, { stage: "events", status: String(stream && stream.status), outcome });
  }
}
