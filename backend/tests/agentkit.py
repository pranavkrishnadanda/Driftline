"""A real agent stack for review / human-in-the-loop tests: the answer graph on a real
Postgres checkpointer, the DeterministicAdapter running the in-repo ExtractiveResponder
(or scripted replies), the TEI embedder, and an AgentWorker on the real `agent` stream.

`AgentKit.restart()` builds a brand-new checkpointer, graph and worker on the same
database, which is what a worker process restart looks like to a paused thread.
"""

import json
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from dbseed import EMBED_MODEL
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from driftline.agents.eventlog import AskEventLog
from driftline.agents.events import FinalEvent, StepEvent
from driftline.agents.graph import AgentConfig, AgentDeps, build_answer_graph
from driftline.agents.llm import AgentLLM
from driftline.agents.offline import ExtractiveResponder
from driftline.agents.schemas import AGENT_STREAM, AskJob
from driftline.agents.worker import AgentWorker
from driftline.clock import ManualClock
from driftline.llm.adapters.deterministic import DeterministicAdapter
from driftline.llm.adapters.tei import TEIEmbeddingAdapter
from driftline.llm.router import LLMRouter, Route
from driftline.obs.cost import CostLedger
from driftline.retrieval.hybrid import HybridRetriever
from driftline.retrieval.rerank import TEIReranker
from driftline.streams.bus import StreamBus

NOW = datetime(2026, 10, 25, tzinfo=UTC)


def half_supported_draft(chunk_id: UUID, version_id: UUID, good: str, bad: str) -> str:
    """A draft with one claim quoting `chunk_id` and one citing a chunk that was never
    retrieved: after verification the answer has confidence 0.5."""
    claims = [
        {
            "text": good,
            "citations": [
                {"chunk_id": str(chunk_id), "version_id": str(version_id), "quote": good}
            ],
        },
        {
            "text": bad,
            "citations": [{"chunk_id": str(uuid4()), "version_id": str(version_id), "quote": bad}],
        },
    ]
    return json.dumps({"answer": f"{good} {bad}", "claims": claims})


@dataclass
class AgentKit:
    pool: object
    redis: object
    dsn: str
    embedder_url: str
    stack: AsyncExitStack
    config: AgentConfig = field(default_factory=lambda: AgentConfig(max_verify_retries=0))
    det: DeterministicAdapter | None = None
    worker: AgentWorker | None = None
    graph: object = None

    @property
    def bus(self) -> StreamBus:
        return StreamBus(self.redis)

    @property
    def events(self) -> AskEventLog:
        return AskEventLog(self.redis)

    async def restart(self, script=None) -> AgentWorker:
        """A new checkpointer connection, graph and worker (a simulated process restart)."""
        saver = await self.stack.enter_async_context(AsyncPostgresSaver.from_conn_string(self.dsn))
        await saver.setup()
        self.det = DeterministicAdapter("det", script=script, responder=ExtractiveResponder())
        tiers = {t: [Route("det", f"det-{t}")] for t in ("extract", "answer", "judge")}
        router = LLMRouter(
            providers={"det": self.det, "tei": TEIEmbeddingAdapter(self.embedder_url)},
            chains={**tiers, "embed": [Route("tei", EMBED_MODEL)]},
            clock=ManualClock(),
        )
        deps = AgentDeps(
            pool=self.pool,
            llm=AgentLLM(router, ledger=CostLedger(self.pool)),
            retriever=HybridRetriever(self.pool, router, embed_model=EMBED_MODEL),
            reranker=TEIReranker(None),
            clock=ManualClock(NOW.timestamp()),
            config=self.config,
        )
        self.graph = build_answer_graph(deps).compile(checkpointer=saver)
        self.worker = AgentWorker(
            pool=self.pool,
            redis=self.redis,
            bus=self.bus,
            events=self.events,
            graph=self.graph,
            consumer=f"w-{uuid4()}",
            clock=ManualClock(NOW.timestamp()),
        )
        await self.worker.setup()
        return self.worker

    async def enqueue(self, tenant_id: UUID, question: str, **job_fields) -> AskJob:
        async with self.pool.acquire() as conn:
            job_id = await conn.fetchval(
                "INSERT INTO jobs (tenant_id, kind) VALUES ($1, 'ask') RETURNING id", tenant_id
            )
        job = AskJob(job_id=job_id, tenant_id=tenant_id, question=question, **job_fields)
        await self.bus.publish(AGENT_STREAM, job.model_dump(mode="json"))
        return job

    async def drain(self, limit: int = 10) -> int:
        """Process agent-stream messages until none is left; returns how many ran."""
        done = 0
        for _ in range(limit):
            n = await self.worker.run_once(block_ms=50)
            if n == 0:
                break
            done += n
        return done

    async def job_events(self, job_id: UUID) -> list:
        return [e for _, e in await self.events.read(job_id, count=1000)]


def review_steps(events: list) -> list[str]:
    return [e.status for e in events if isinstance(e, StepEvent) and e.node == "review"]


def finals(events: list) -> list[FinalEvent]:
    return [e for e in events if isinstance(e, FinalEvent)]
