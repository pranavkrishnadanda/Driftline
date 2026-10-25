# Driftline bench results: `cd66852df1d8`

All LLM calls in these runs go to the **stub LLM** (`LatencyStubAdapter`: seeded log-normal latency, deterministic text), so the numbers measure Driftline, not a provider's quota. Embeddings and reranking are real (TEI on CPU).

## Ask load (k6, `bench/run.sh N`)

| workers | VUs | window (s) | completed | throughput (asks/s) | p50 ms | p95 ms | p99 ms | TTFT p50 ms | TTFT p95 ms | 429 rate | error rate | reranker | OOM |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 4 | 204 | 29 | 0.14 | 27751 | 31093 | 32400 | 24357 | 27251 | 0.0% | 0.0% | on | none |
| 4 | 16 | 210 | 91 | 0.43 | 35670 | 39398 | 40881 | 32397 | 34862 | 0.0% | 0.0% | on | none |
| 8 | 32 | 199 | 318 | 1.60 | 19526 | 21999 | 23011 | 15856 | 18017 | 0.0% | 0.0% | on, **OOM-killed: RRF fallback** | driftline-bench-reranker-1 |
| 1 | 4 | 197 | 40 | 0.20 | 19448 | 24177 | 25542 | 15812 | 19327 | 0.0% | 0.0% | off | none |
| 4 | 16 | 197 | 163 | 0.83 | 18885 | 22426 | 22701 | 15331 | 17704 | 0.0% | 0.0% | off | none |

## Latency percentiles

End-to-end ask latency in ms (POST sent -> `final` event), from every raw k6 sample. p99.9 needs at least 1000 samples and no run has that many; with n < 100, p99 is interpolated between the two largest samples.

| workers | reranker | n | min | p50 | p90 | p95 | p99 | p99.9 | max | mean | stddev |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | on | 29 | 6863 | 27751 | 30667 | 31093 | 32400 | n/a (n<1000) | 32876 | 26783 | 5280 |
| 4 | on | 91 | 7181 | 35670 | 38169 | 39398 | 40881 | n/a (n<1000) | 42018 | 33861 | 6787 |
| 8 | on, **OOM-killed: RRF fallback** | 318 | 3545 | 19526 | 21543 | 21999 | 23011 | n/a (n<1000) | 24732 | 19063 | 3003 |
| 1 | off | 40 | 3551 | 19448 | 23033 | 24177 | 25542 | n/a (n<1000) | 25865 | 19188 | 3833 |
| 4 | off | 163 | 4240 | 18885 | 21322 | 22426 | 22701 | n/a (n<1000) | 23337 | 18486 | 3090 |

## LLM-serving view

**Every LLM call here is the stub LLM** (800 ms median per call, log-normal), so TTFT and any per-token figure reflect the stub and Driftline's pipeline, not Claude. TTFT is measured by the client from POST to the first `token` event, so it includes queueing, planning and retrieval: tokens stream only in the `draft` stage.

| workers | reranker | TTFT p50 | TTFT p90 | TTFT p95 | TTFT p99 | E2E p50 | E2E p95 | first token -> final, mean | SSE events / ask p50 | SSE events/s | TPOT / ITL | output tokens/s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | on | 24357 | 27162 | 27251 | 27436 | 27751 | 31093 | 3735 | 67 | 9.5 | not captured | not captured |
| 4 | on | 32397 | 34172 | 34862 | 36072 | 35670 | 39398 | 3534 | 67 | 29.2 | not captured | not captured |
| 8 | on, **OOM-killed: RRF fallback** | 15856 | 17435 | 18017 | 19111 | 19526 | 21999 | 3660 | 62 | 103.0 | not captured | not captured |
| 1 | off | 15812 | 19080 | 19327 | 20925 | 19448 | 24177 | 3661 | 62 | 13.1 | not captured | not captured |
| 4 | off | 15331 | 17475 | 17704 | 19039 | 18885 | 22426 | 3575 | 61 | 53.2 | not captured | not captured |

All times in ms. `first token -> final, mean` is mean E2E minus mean TTFT (exact by linearity; per-ask pairs are not recoverable from the k6 output). It covers the rest of `draft` plus the `verify` stage, so it is **not** a decode time. `SSE events` count every event type (step, token, claim, final), not tokens.

TPOT / ITL and output tokens per second: not captured in this run. k6's `sse_event` samples carry the stream URL but not the event name, so token events cannot be told apart from step, claim and final events, and no output-token count was recorded. Needed: in bench/k6/ask.js, timestamp every `token` event (a Trend of gaps between consecutive tokens = ITL; (last token - first token) / (tokens - 1) per ask = TPOT) and count tokens per ask (a Counter, for output tokens/s). With the stub LLM these would measure the stub's sleeps (800 ms median per call, 70% of it spread evenly over the words of the reply), not Claude.

## Errors, success rate and Apdex

Apdex T = 10 s on E2E latency (tolerating up to 40 s; failures and 429s count as frustrated). T is about 1.5x to 2x an unloaded ask's in-worker time (4.5 to 7 s p50 from the stage timings), chosen from the service time, not from these results. `interrupted` asks were accepted but still running when k6 ended the test (30 s graceful stop); they are not errors and not in `attempts`.

| workers | reranker | attempts | completed | success rate | 5xx | 429 | timeout/network | other 4xx | failed SSE | interrupted | http_req_failed | Apdex | satisfied / tolerating / frustrated |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | on | 29 | 29 | 100.0% | 0 | 0 | 0 | 0 | 0 | 0 | 0.0% | 0.517 | 1 / 28 / 0 |
| 4 | on | 91 | 91 | 100.0% | 0 | 0 | 0 | 0 | 0 | 2 | 0.0% | 0.495 | 2 / 86 / 3 |
| 8 | on, **OOM-killed: RRF fallback** | 318 | 318 | 100.0% | 0 | 0 | 0 | 0 | 0 | 0 | 0.0% | 0.516 | 10 / 308 / 0 |
| 1 | off | 40 | 40 | 100.0% | 0 | 0 | 0 | 0 | 0 | 0 | 0.0% | 0.525 | 2 / 38 / 0 |
| 4 | off | 163 | 163 | 100.0% | 0 | 0 | 0 | 0 | 0 | 0 | 0.0% | 0.518 | 6 / 157 / 0 |

## Throughput and concurrency

| workers | reranker | VUs (max) | asks in flight, mean | HTTP requests/s | asks attempted/s | goodput (successful asks/s) |
|---|---|---|---|---|---|---|
| 1 | on | 4 | 3.8 | 0.28 | 0.14 | 0.14 |
| 4 | on | 16 | 14.7 | 0.88 | 0.43 | 0.43 |
| 8 | on, **OOM-killed: RRF fallback** | 32 | 30.4 | 3.19 | 1.60 | 1.60 |
| 1 | off | 4 | 3.9 | 0.41 | 0.20 | 0.20 |
| 4 | off | 16 | 15.3 | 1.65 | 0.83 | 0.83 |

## Scaling efficiency

throughput(N) / (N x throughput(1)), against the 1-worker run with the same reranker setting. 1.0 is linear scaling.

| workers | reranker | asks/s | speedup | efficiency | comparable |
|---|---|---|---|---|---|
| 1 | on | 0.14 | 1.00 | 1.00 | yes |
| 4 | on | 0.43 | 3.05 | 0.76 | yes |
| 8 | on, **OOM-killed: RRF fallback** | 1.60 | 11.22 | 1.40 | **no**: reranker OOM-killed, RRF fallback |
| 1 | off | 0.20 | 1.00 | 1.00 | yes |
| 4 | off | 0.83 | 4.08 | 1.02 | yes |

## Saturation

From one `docker stats --no-stream` snapshot taken half-way through each run (a point sample, not a time series). VM CPU is the sum of container CPU% over 100% x the VM's vCPUs.

| workers | reranker | VM CPU | memory, all containers (MiB) | top CPU | top memory |
|---|---|---|---|---|---|
| 1 | on | 1.0% | 3752 | reranker-1 1.53%, redis-1 0.78%, embedder-1 0.41% | reranker-1 2223 MiB (72.4% of 3072), embedder-1 800 MiB (39.1% of 2048), gateway-1 242 MiB (4.1% of 5911) |
| 4 | on | 76.9% | 4382 | reranker-1 280.44%, embedder-1 18.68%, agent-worker-3 2.36% | reranker-1 2220 MiB (72.3% of 3072), embedder-1 806 MiB (39.3% of 2048), gateway-1 220 MiB (3.7% of 5911) |
| 8 | on, **OOM-killed: RRF fallback** | 6.9% | 3160 | embedder-1 7.66%, agent-worker-6 5.29%, agent-worker-7 4.44% | embedder-1 825 MiB (40.3% of 2048), gateway-1 229 MiB (3.9% of 5911), agent-worker-3 222 MiB (3.8% of 5911) |
| 1 | off | 1.0% | 1478 | agent-worker-1 3.04%, redis-1 0.31%, gateway-1 0.24% | embedder-1 805 MiB (39.3% of 2048), gateway-1 221 MiB (3.8% of 5911), agent-worker-1 210 MiB (3.6% of 5911) |
| 4 | off | 3.6% | 2190 | agent-worker-2 3.94%, agent-worker-3 2.81%, gateway-1 2.31% | embedder-1 810 MiB (39.6% of 2048), gateway-1 238 MiB (4.0% of 5911), agent-worker-2 220 MiB (3.7% of 5911) |

## Queueing vs work

Server side, from each succeeded ask's step events (`bench/stages.py`), in ms.

| workers | reranker | asks | queue p50 | queue p95 | worker p50 | worker p95 | queue share of wall time (mean) |
|---|---|---|---|---|---|---|---|
| 1 | on | 29 | 20946 | 24150 | 6921 | 9043 | 73.8% |
| 4 | on | 91 | 26830 | 29438 | 8773 | 11240 | 73.4% |
| 8 | on, **OOM-killed: RRF fallback** | 318 | 14662 | 16542 | 4840 | 6689 | 74.1% |
| 1 | off | 40 | 14764 | 18267 | 4526 | 6964 | 74.4% |
| 4 | off | 163 | 14168 | 16647 | 4595 | 6595 | 74.2% |

## Where the time goes

p50 ms per stage over each run's succeeded asks, from the asks' own step events (`bench/stages.py`). `queue` is time waiting for a free worker (wall - worker); `retrieve` is query embedding + hybrid search + cross-encoder rerank on TEI (CPU); `plan`, `draft` and `verify` are stub-LLM calls.

| workers | asks | reranker | wall | queue | worker | plan | retrieve | draft | verify | rerank ran | busiest containers (CPU) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 29 | on | 27746 | 20946 | 6921 | 750 | 2126 | 1253 | 2460 | 100.0% | reranker-1 1.53%, redis-1 0.78%, embedder-1 0.41% |
| 4 | 91 | on | 35666 | 26830 | 8773 | 779 | 4351 | 948 | 2565 | 100.0% | reranker-1 280.44%, embedder-1 18.68%, agent-worker-3 2.36% |
| 8 | 318 | on, **OOM-killed: RRF fallback** | 19524 | 14662 | 4840 | 823 | 40 | 1052 | 2617 | 0.0% | embedder-1 7.66%, agent-worker-6 5.29%, agent-worker-7 4.44% |
| 1 | 40 | off | 19442 | 14764 | 4526 | 860 | 60 | 1086 | 2644 | 0.0% | agent-worker-1 3.04%, redis-1 0.31%, gateway-1 0.24% |
| 4 | 163 | off | 18882 | 14168 | 4595 | 790 | 35 | 1075 | 2594 | 0.0% | agent-worker-2 3.94%, agent-worker-3 2.81%, gateway-1 2.31% |

## Ingest throughput (`bench/ingest.sh`)

Corpus: 10 copies of the 6 bench/corpus Markdown documents (headings suffixed per copy), upload connector.

| ingest workers | documents | chunks | seconds | documents/min | chunks/s |
|---|---|---|---|---|---|
| 1 | 60 | 310 | 23.7 | 152.1 | 13.1 |
| 2 | 60 | 310 | 22.9 | 157.4 | 13.6 |
| 4 | 60 | 310 | 24.5 | 146.8 | 12.6 |

Per-document ingest time (p50/p95): not captured in this run. `ingest.sh` times the whole batch; per-document figures need each ingest job's `started_at` / `finished_at` exported from the jobs table.

## Chaos (`bench/chaos.sh`)

**PASS**: 86 asks, 8 worker kills, 0 lost, 0 stuck, dlq 0, pending 0.

Availability under chaos (succeeded / asks): **100.0%** (86 / 86). Recovery: no ask was lost, stuck or left pending after the drain, so every ask a killed worker held was reclaimed and finished. Time to recover per kill: not captured in this run (needs the kill timestamps and each reclaimed job's reclaim and finish times).

```json
{
  "asks": 86,
  "dlq": 0,
  "duration_s": 180,
  "exit_code": 0,
  "failed": 0,
  "kill_every_s": 20,
  "kills": 8,
  "llm": "stub LLM",
  "no_answer": 0,
  "pending": 0,
  "stuck": 0,
  "succeeded": 86,
  "workers": 4
}
```

## Notes

**Read the 8-worker row carefully.** The kernel OOM-killed the reranker during the
8-worker run (`docker inspect` reported `OOMKilled=true` for `driftline-bench-reranker-1`;
it was already gone at the mid-run `docker stats` snapshot, and 0% of that run's asks
were reranked). Every ask in that row used the documented RRF fallback, which is faster
but lower quality, so it is **not** comparable with the 1- and 4-worker reranker rows.
**4 workers is the last row with the reranker fully on.** Memory at 8 workers, from the
snapshots: 8 agent workers at about 220 MiB each (about 1.75 GiB), the reranker at about
2.17 GiB, the embedder at about 0.8 GiB, and gateway, relay and Postgres at about
0.55 GiB. That is about 5.3 GiB of the 5.77 GiB the Colima VM reports, before the kernel
and any other containers.

**Reranker off (`-rrf` rows).** These rows ran with `BENCH_RERANKER=off` (the RRF
fallback, labelled `off`) at 1 and 4 workers, to give a like-for-like comparison without
the reranker. The 8-worker reranker-off run was stopped before it finished, to free the VM,
so it has no row. These runs were made at commit `7cb62e6`, which differs from
`cd66852` only in the bench scripts and the summariser. Each `workers-*.json` records its
own commit.

**Where the time goes (evidence: per-stage `t_ms` from each ask's step events, plus
mid-run `docker stats`).**
- **Most of the wall time is queueing, and this is by design of the load.** The closed
  model keeps 4 asks in flight per worker, and a worker runs one ask at a time, so each
  ask waits for about 3 others. At 1 worker, `queue` p50 is 20.9 s and `worker` p50 is
  6.9 s.
- **Inside a worker, reranking is the cost that grows with load.** The `retrieve` stage
  (query embedding, hybrid search and cross-encoder rerank of 30 candidates on TEI/CPU)
  rises from 2.1 s p50 at 1 worker to 4.4 s at 4 workers. Meanwhile the reranker container
  is at 280% CPU of the VM's 4 vCPUs, and the agent workers are at 1 to 2% CPU, because
  they are waiting on the stub LLM and on TEI.
- **With the reranker off, `retrieve` is 35 to 60 ms**, and worker time drops to about
  4.5 s. That remaining time is the stub LLM's sleeps (plan 0.8 s, draft 1.1 s, verify
  2.6 s, with an 800 ms median per call), so it does not depend on load.
- **Throughput scales with workers only while the reranker has CPU headroom.** With the
  reranker on, 1 to 4 workers gives 0.14 to 0.43 asks/s (3.0x). With it off, 1 to 4
  workers gives 0.20 to 0.83 asks/s (4.1x).
- **TTFT is close to total latency** because tokens stream only in the `draft` stage, after
  queueing, planning and retrieval.

**429s.** None at any worker count. The closed model keeps the agent backlog at no more
than the VU count (at most 32), well under `ask_max_pending` (200), so backpressure never
triggered. They are counted, not filtered.

**Run settings.** Every row: 20 s warm-up (discarded), then 180 s of k6 with 4 VUs per
agent worker. The window column is longer than 180 s because k6 lets in-flight iterations
finish during its 30 s graceful stop. Other settings: semantic cache off, so every ask runs
the full graph; stub LLM median 800 ms and sigma 0.5, seeded per worker; fixture corpus of
6 documents and 31 chunks. Other agents' test containers may have shared the VM during the
runs.

**Ingest.** About 150 documents/min whether there are 1, 2 or 4 ingest workers. The single
CPU TEI embedder is the shared bottleneck, so more ingest workers do not help on this VM.

## Metric definitions

- **Latency percentiles (p50, p90, p95, p99, p99.9), min, mean, max, stddev.** Linear interpolation between closest ranks over every raw k6 sample. p90 and p95 are k6's default summary stats (`avg,min,med,max,p(90),p(95)`); p99 is the tail vLLM reports by default. p99.9 is shown only with at least 1000 samples; with fewer than 100 samples p99 is an interpolation between the two largest. stddev is the sample standard deviation. Source: <https://grafana.com/docs/k6/latest/using-k6/k6-options/reference/#summary-trend-stats>
- **Golden signals: latency, traffic, errors, saturation.** Latency of successful and failed requests kept apart; traffic as requests per second; errors as the rate of failed requests; saturation as how full the service is (here CPU and memory per container). Source: <https://sre.google/sre-book/monitoring-distributed-systems/>
- **Throughput, requests/s, goodput.** Asks/s = completed asks / window (first to last k6 sample), as GenAI-Perf/AIPerf define RPS. HTTP requests/s counts k6's `http_reqs` (POST plus the SSE GET). Goodput here is successful asks/s; vLLM defines goodput against per-request SLOs (`--goodput ttft:..,e2el:..`), and no SLO was set for these runs. Source: <https://docs.nvidia.com/nim/benchmarking/llm/latest/metrics.html>
- **Error and success rate.** error rate = failed / attempts, 429 rate = rejected / attempts, success rate = completed / attempts; broken down by HTTP 5xx, 429, other 4xx, status 0 (timeout or network) and failed SSE streams. `http_req_failed` is k6's built-in rate over the POSTs. Asks still running when k6 stopped are reported apart, not as errors. Source: <https://grafana.com/docs/k6/latest/using-k6/metrics/reference/>
- **TTFT, E2E latency, TPOT/ITL, output tokens/s.** TTFT: request sent to first token. E2E: request sent to the full response. TPOT/ITL: (E2E - TTFT) / (output tokens - 1). Output tokens/s: output tokens / duration (aggregate) or per request. MLPerf Inference bounds TTFT and TPOT in its LLM Server scenario. Source: <https://raw.githubusercontent.com/vllm-project/vllm/main/vllm/benchmarks/serve.py>
- **Apdex.** (satisfied + tolerating / 2) / samples; satisfied <= T, tolerating <= 4T, frustrated > 4T or an error. T = 10 s on E2E ask latency (see above). Source: <https://docs.newrelic.com/docs/apm/new-relic-apm/apdex/apdex-measure-user-satisfaction/>
- **Scaling efficiency.** throughput(N) / (N x throughput(1)): speedup divided by the number of workers (parallel efficiency), per reranker mode. Source: <https://en.wikipedia.org/wiki/Speedup>
- **Concurrency.** VUs: k6's `vus` gauge (closed model, one ask in flight per VU). Mean asks in flight: sum of E2E latencies / window (Little's law, completed asks). No peak is reported: E2E is timed with 1 ms `Date.now()` steps, so one VU's back-to-back asks can appear to overlap and a sweep would overcount. Source: <https://grafana.com/docs/k6/latest/using-k6/metrics/reference/>
- **MLPerf Inference LLM latency bounds (context).** The datacenter Server scenario for Llama 2 70B constrains TTFT/TPOT (2000 ms/200 ms conversational, 450 ms/40 ms interactive). Shown for context only: these runs use a stub LLM. Source: <https://github.com/mlcommons/inference_policies/blob/master/inference_rules.adoc>

## Machine

- **colima_vm**: {"arch": "aarch64", "cpus": 4, "disk_gib": 100.0, "memory_gib": 6.0, "runtime": "docker"}
- **cpu**: Apple M4
- **docker_client**: 29.9.2
- **docker_compose**: 5.6.1
- **docker_server**: 29.5.2
- **docker_vm_visible**: {"cpus": 4, "kernel": "6.8.0-117-generic", "mem_gib": 5.77}
- **host_cpus**: 10
- **host_ram_gib**: 16.0
- **k6**: k6 v2.3.0 (go1.27.1, darwin/arm64)
- **os**: macOS 26.6.2 (arm64)
