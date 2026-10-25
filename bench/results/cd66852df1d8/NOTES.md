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
