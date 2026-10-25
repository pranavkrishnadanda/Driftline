"""Where an ask's time goes, from the asks' own step events (run by bench/run.sh inside
the gateway container: `python - SINCE < bench/stages.py`).

For every ask that succeeded since SINCE (a Postgres timestamp), read its event log
(`events:ask:{id}`) and split its wall time (jobs.created_at -> finished_at) into:
  queue      waiting in the agent stream for a free worker (wall time - worker time)
  plan       planner LLM call
  retrieve   the subagent branch: query embedding (TEI), hybrid search, cross-encoder
             rerank (TEI) -- the slowest branch when the planner fans out
  draft      answer LLM call (streamed)
  verify     judge LLM calls, one per claim
Step events carry `t_ms` since the worker picked the ask up. Prints one JSON object with
p50/p95/mean ms per stage and the share of asks whose rerank actually ran.
"""

import asyncio
import json
import os
import statistics
import sys

import asyncpg
import redis.asyncio as aioredis

STAGES = ("plan", "subagent", "draft", "verify")


def pct(values, q):
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo), 1)


def summary(values):
    return {
        "p50": pct(values, 0.5),
        "p95": pct(values, 0.95),
        "mean": round(statistics.fmean(values), 1) if values else None,
        "n": len(values),
    }


async def main(since: str) -> None:
    pg = await asyncpg.connect(os.environ["DRIFTLINE_DATABASE_URL"])
    r = aioredis.from_url(os.environ["DRIFTLINE_REDIS_URL"], decode_responses=True)
    rows = await pg.fetch(
        "SELECT id, extract(epoch FROM finished_at - created_at) * 1000 AS wall_ms FROM jobs "
        "WHERE kind = 'ask' AND status = 'succeeded' AND created_at >= $1::text::timestamptz",
        since,
    )
    out: dict[str, list[float]] = {k: [] for k in ("wall", "queue", "worker", *STAGES)}
    reranked = rerank_total = 0
    for row in rows:
        events = [json.loads(f["data"]) for _, f in await r.xrange(f"events:ask:{row['id']}")]
        steps = [e for e in events if e.get("type") == "step"]
        if not steps:
            continue
        worker_ms = max(e["t_ms"] for e in steps)
        out["wall"].append(float(row["wall_ms"]))
        out["worker"].append(worker_ms)
        out["queue"].append(max(0.0, float(row["wall_ms"]) - worker_ms))
        for stage in STAGES:
            starts: dict = {}
            longest = 0.0
            total = 0.0
            for e in steps:
                if e["node"] != stage:
                    continue
                # Subagent branches overlap (keyed by branch); draft/verify attempts are sequential.
                key = e.get("detail", {}).get("branch") if stage == "subagent" else None
                if e["status"] == "started":
                    starts[key] = e["t_ms"]
                elif e["status"] == "completed" and key in starts:
                    d = e["t_ms"] - starts.pop(key)
                    longest = max(longest, d)
                    total += d
                    if stage == "subagent":
                        rerank_total += 1
                        reranked += bool(e.get("detail", {}).get("reranked"))
            # Branches run in parallel (slowest counts); draft/verify attempts add up.
            out[stage].append(longest if stage == "subagent" else total)
    result = {("retrieve" if k == "subagent" else k): summary(v) for k, v in out.items()}
    result["asks"] = len(out["wall"])
    result["rerank_ran_share"] = round(reranked / rerank_total, 3) if rerank_total else None
    print(json.dumps(result, sort_keys=True))
    await r.aclose()
    await pg.close()


asyncio.run(main(sys.argv[1]))
