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

| ingest workers | documents | chunks | seconds | documents/min |
|---|---|---|---|---|
| 1 | 60 | 310 | 23.7 | 152.1 |
| 2 | 60 | 310 | 22.9 | 157.4 |
| 4 | 60 | 310 | 24.5 | 146.8 |

## Chaos (`bench/chaos.sh`)

**PASS**: 86 asks, 8 worker kills, 0 lost, 0 stuck, dlq 0, pending 0.

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
