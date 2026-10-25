"""The answer graph (spec section 5) as a LangGraph StateGraph with a Postgres checkpointer.

classify -> cache -> plan -> subagent x N (Send) -> merge -> draft -> verify -> respond
                                                          ^              |
                                                          +- re_retrieve +  (at most 2)

`classify` goes straight to `respond` for a refused question, or when the tenant has no
document version that had started by now (an empty corpus): no model is called.

State holds only JSON-plain values (dicts, lists, strings), so every checkpoint is
portable and a crashed run resumes in another worker from the last finished node.
Nodes publish `step`, `token` and `claim` events through LangGraph's custom stream;
`run_ask` forwards them to the caller (the agent worker writes them to the event log).
"""

import operator
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Annotated, Any, TypedDict
from uuid import UUID

import asyncpg
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel

from driftline.agents.events import ASK_EVENT_ADAPTER, ClaimEvent, StepEvent, TokenEvent
from driftline.agents.guardrails import (
    clamp_as_of,
    evidence_index,
    extract_as_of_hint,
    screen_question,
    verify_claim,
)
from driftline.agents.llm import AgentLLM
from driftline.agents.prompts import build_draft_request, build_judge_request, build_plan_request
from driftline.agents.schemas import (
    AnswerSchema,
    AskJob,
    Citation,
    Claim,
    DraftOutput,
    JudgeOutput,
    NearestSource,
    PlanOutput,
)
from driftline.cache.semantic import SemanticCache
from driftline.clock import Clock, SystemClock
from driftline.config import Settings
from driftline.llm.jsonstream import JsonStringFieldStreamer
from driftline.llm.router import StructuredOutputError
from driftline.obs.tracing import NoopTracer, Tracer
from driftline.retrieval.hybrid import HybridRetriever
from driftline.retrieval.rerank import TEIReranker
from driftline.retrieval.types import Evidence, RetrievalQuery

REFUSAL = (
    "This question was not answered: it reads like an attempt to change the assistant's "
    "instructions rather than a question about the documents."
)
VERSION_START = (
    "SELECT min(v.valid_from) FROM doc_versions v JOIN documents d ON d.id = v.document_id "
    "JOIN sources s ON s.id = d.source_id WHERE s.tenant_id = $1 AND v.version_key = $2"
)
HAS_VERSIONS = (
    "SELECT EXISTS (SELECT 1 FROM doc_versions v JOIN documents d ON d.id = v.document_id "
    "JOIN sources s ON s.id = d.source_id WHERE s.tenant_id = $1 AND v.valid_from <= $2 "
    "AND ($3::text[] IS NULL OR s.kind = ANY($3::text[])))"
)


@dataclass(frozen=True)
class AgentConfig:
    top_k: int = 30
    rerank_top_n: int = 8
    max_subagents: int = 4
    max_verify_retries: int = 2
    re_retrieve_top_k: int = 10
    re_retrieve_top_n: int = 4
    nearest_sources: int = 3
    plan_tier: str = "extract"
    draft_tier: str = "answer"
    judge_tier: str = "judge"
    plan_max_tokens: int = 2048
    draft_max_tokens: int = 4096
    use_judge: bool = True

    @classmethod
    def from_settings(cls, settings: Settings) -> "AgentConfig":
        return cls(
            top_k=settings.retrieval_candidates,
            rerank_top_n=settings.rerank_top_n,
            max_subagents=settings.max_subagents,
            max_verify_retries=settings.max_verify_retries,
            plan_max_tokens=settings.default_max_output_tokens,
            draft_max_tokens=settings.answer_max_output_tokens,
        )


@dataclass
class AgentDeps:
    pool: asyncpg.Pool
    llm: AgentLLM
    retriever: HybridRetriever
    reranker: TEIReranker
    cache: SemanticCache | None = None
    tracer: Tracer = field(default_factory=NoopTracer)
    clock: Clock = field(default_factory=SystemClock)
    config: AgentConfig = field(default_factory=AgentConfig)


def merge_evidence(left: list[dict] | None, right: list[dict] | None) -> list[dict]:
    """Reducer: append new chunks, keeping the first copy of any chunk id."""
    out = list(left or [])
    seen = {e["chunk_id"] for e in out}
    for item in right or []:
        if item["chunk_id"] not in seen:
            seen.add(item["chunk_id"])
            out.append(item)
    return out


class AskState(TypedDict, total=False):
    job_id: str
    tenant_id: str
    question: str
    requested_as_of: str | None
    source_kinds: list[str] | None
    started_at: float
    as_of: str
    refused: str | None
    empty_corpus: bool
    cache_hit: dict | None
    sub_questions: list[dict]
    evidence: Annotated[list[dict], merge_evidence]
    draft: dict | None
    draft_error: str | None
    attempts: int
    verified: list[dict]
    failed: list[dict]
    degraded: Annotated[bool, operator.or_]
    answer: dict | None


class SubagentInput(TypedDict):
    job_id: str
    tenant_id: str
    started_at: float
    branch: int
    question: str
    as_of: str
    source_kinds: list[str] | None


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value.strip())
    except ValueError:
        return None


def _evidence(state: AskState) -> list[Evidence]:
    return [Evidence.model_validate(e) for e in state.get("evidence") or []]


def initial_state(job: AskJob, *, started_at: float) -> AskState:
    return {
        "job_id": str(job.job_id),
        "tenant_id": str(job.tenant_id),
        "question": job.question,
        "requested_as_of": job.as_of.isoformat() if job.as_of else None,
        "source_kinds": list(job.source_kinds) if job.source_kinds else None,
        "started_at": started_at,
        "attempts": 0,
        "degraded": False,
    }


def build_answer_graph(deps: AgentDeps) -> StateGraph:
    cfg = deps.config

    def emit(state: dict, event: BaseModel) -> None:
        get_stream_writer()(event.model_dump(mode="json"))

    def step(state: dict, node: str, status: str, /, **detail: Any) -> None:
        t_ms = round((deps.clock.now() - state["started_at"]) * 1000, 1)
        emit(state, StepEvent(node=node, status=status, detail=detail, t_ms=t_ms))

    def ids(state: dict) -> dict[str, UUID]:
        return {"job_id": UUID(state["job_id"]), "tenant_id": UUID(state["tenant_id"])}

    async def classify(state: AskState) -> dict:
        step(state, "classify", "started")
        now = datetime.fromtimestamp(deps.clock.now(), UTC)
        reason = screen_question(state["question"])
        source = "request"
        if state.get("requested_as_of"):
            as_of = clamp_as_of(_dt(state["requested_as_of"]), now)
        else:
            hint = extract_as_of_hint(state["question"])
            source, as_of = hint.source, now
            if hint.as_of is not None:
                as_of = clamp_as_of(hint.as_of, now)
            elif hint.version_key is not None:
                async with deps.pool.acquire() as conn:
                    start = await conn.fetchval(
                        VERSION_START, UUID(state["tenant_id"]), hint.version_key
                    )
                source = "version" if start else "unknown_version"
                as_of = clamp_as_of(start, now) if start else now
        empty = False
        if reason is None:
            # Sub-questions may move as_of up to now, so "nothing to search" means no
            # version had started by now (not by as_of): then no model is ever called.
            kinds = state.get("source_kinds")
            async with deps.pool.acquire() as conn:
                empty = not await conn.fetchval(
                    HAS_VERSIONS, UUID(state["tenant_id"]), now, list(kinds) if kinds else None
                )
        step(
            state,
            "classify",
            "completed",
            as_of=as_of.isoformat(),
            source=source,
            refused=reason,
            empty_corpus=empty,
        )
        return {"as_of": as_of.isoformat(), "refused": reason, "empty_corpus": empty}

    async def cache_lookup(state: AskState) -> dict:
        if deps.cache is None:
            step(state, "cache", "skipped")
            return {"cache_hit": None}
        async with deps.pool.acquire() as conn:
            hit = await deps.cache.lookup(
                conn,
                tenant_id=UUID(state["tenant_id"]),
                question=state["question"],
                as_of=_dt(state["as_of"]),
                source_kinds=state.get("source_kinds"),
            )
        if hit is None:
            step(state, "cache", "miss")
            return {"cache_hit": None}
        step(state, "cache", "hit", similarity=round(hit.similarity, 4))
        return {"cache_hit": hit.answer}

    async def plan(state: AskState) -> dict:
        step(state, "plan", "started")
        as_of = _dt(state["as_of"])
        request = build_plan_request(
            state["question"], as_of, max_output_tokens=cfg.plan_max_tokens
        )
        degraded, error = False, None
        try:
            output, result = await deps.llm.structured(
                request, PlanOutput, node="plan", tier=cfg.plan_tier, **ids(state)
            )
            degraded = result.degraded
            parts = output.sub_questions[: cfg.max_subagents]
            mode = output.mode if len(parts) > 1 else "single"
        except StructuredOutputError:
            # A plan is an optimisation: answer the question as asked instead.
            parts, mode, error = [], "single", "malformed_plan"
        now = datetime.fromtimestamp(deps.clock.now(), UTC)
        subs = []
        for part in parts or []:
            sub_as_of = as_of
            if part.as_of:
                try:
                    day = date.fromisoformat(part.as_of)
                    sub_as_of = clamp_as_of(
                        datetime(day.year, day.month, day.day, 23, 59, 59, 999999, UTC), now
                    )
                except ValueError:
                    pass
            if part.question.strip():
                subs.append({"question": part.question.strip(), "as_of": sub_as_of.isoformat()})
        if not subs:
            subs, mode = [{"question": state["question"], "as_of": as_of.isoformat()}], "single"
        subs = subs[: cfg.max_subagents]
        step(state, "plan", "completed", mode=mode, sub_questions=subs, error=error)
        return {"sub_questions": subs, "degraded": degraded}

    def fan_out(state: AskState) -> list[Send]:
        return [
            Send(
                "subagent",
                SubagentInput(
                    job_id=state["job_id"],
                    tenant_id=state["tenant_id"],
                    started_at=state["started_at"],
                    branch=n,
                    question=sub["question"],
                    as_of=sub["as_of"],
                    source_kinds=state.get("source_kinds"),
                ),
            )
            for n, sub in enumerate(state["sub_questions"][: cfg.max_subagents])
        ]

    async def subagent(payload: SubagentInput) -> dict:
        branch, question = payload["branch"], payload["question"]
        step(
            payload,
            "subagent",
            "started",
            branch=branch,
            sub_question=question,
            as_of=payload["as_of"],
        )
        kinds = payload.get("source_kinds")
        query = RetrievalQuery(
            tenant_id=UUID(payload["tenant_id"]),
            text=question,
            as_of=_dt(payload["as_of"]),
            source_kinds=tuple(kinds) if kinds else None,
        )
        found = await deps.retriever.retrieve(query, top_k=cfg.top_k)
        outcome = await deps.reranker.rerank(question, found, top_n=cfg.rerank_top_n)
        kept = [e.model_copy(update={"sub_question": question}) for e in outcome.items]
        step(
            payload,
            "subagent",
            "completed",
            branch=branch,
            retrieved=len(found),
            kept=len(kept),
            reranked=outcome.reranked,
            rerank_error=outcome.error,
        )
        return {"evidence": [e.model_dump(mode="json") for e in kept]}

    async def merge(state: AskState) -> dict:
        step(state, "merge", "completed", evidence=len(state.get("evidence") or []))
        return {}

    async def draft(state: AskState) -> dict:
        attempt = state.get("attempts", 0)
        step(state, "draft", "started" if attempt == 0 else "retry", attempt=attempt)
        streamer = JsonStringFieldStreamer("answer")
        shown: list[str] = []

        async def on_delta(delta: str) -> None:
            text = streamer.feed(delta)
            if text:
                shown.append(text)
                emit(state, TokenEvent(text=text))

        feedback = [
            f"{c['text']} ({c.get('reason') or 'unsupported'})" for c in state.get("failed") or []
        ]
        request = build_draft_request(
            state["question"],
            _dt(state["as_of"]),
            _evidence(state),
            feedback=feedback if attempt else (),
            max_output_tokens=cfg.draft_max_tokens,
        )
        try:
            output, result = await deps.llm.structured(
                request,
                DraftOutput,
                node="draft",
                tier=cfg.draft_tier,
                on_delta=on_delta,
                **ids(state),
            )
        except StructuredOutputError as exc:
            step(
                state,
                "draft",
                "failed",
                attempt=attempt,
                error="malformed_draft",
                detail=exc.detail[:200],
            )
            return {"draft": None, "draft_error": "malformed_draft"}
        # The router repairs a reply that breaks the schema by asking again; the deltas
        # of both replies reach `on_delta`, and the streamer stops after the first
        # complete `answer`. Whenever what was shown is not the parsed answer, a `retry`
        # step tells the UI to clear it, then the answer is sent whole.
        if "".join(shown) != output.answer:
            if shown:
                step(state, "draft", "retry", attempt=attempt, reason="repair")
            if output.answer:
                emit(state, TokenEvent(text=output.answer))
        step(state, "draft", "completed", attempt=attempt, claims=len(output.claims))
        return {"draft": output.model_dump(), "draft_error": None, "degraded": result.degraded}

    async def verify(state: AskState) -> dict:
        step(state, "verify", "started", attempt=state.get("attempts", 0))
        output = DraftOutput.model_validate(state["draft"])
        index = evidence_index(_evidence(state))
        degraded = False

        async def judge(claim: str, quote: str) -> bool:
            nonlocal degraded
            try:
                verdict, result = await deps.llm.structured(
                    build_judge_request(claim, quote),
                    JudgeOutput,
                    node="judge",
                    tier=cfg.judge_tier,
                    **ids(state),
                )
            except StructuredOutputError:
                return False
            degraded = degraded or result.degraded
            return verdict.entailed

        verified, failed = [], []
        for idx, claim in enumerate(output.claims):
            check = await verify_claim(claim, index, judge=judge if cfg.use_judge else None)
            if check.supported:
                verified.append(
                    Claim(idx=idx, text=claim.text, citations=check.citations, verified=True)
                )
            else:
                cited = [
                    Citation(chunk_id=c, version_id=v, quote=d.quote)
                    for d in claim.citations
                    if (c := _uuid(d.chunk_id)) and (v := _uuid(d.version_id))
                ]
                failed.append(Claim(idx=idx, text=claim.text, citations=cited, reason=check.reason))
            first = check.citations[0] if check.citations else None
            emit(
                state,
                ClaimEvent(idx=idx, verified=check.supported, citation=first, reason=check.reason),
            )
        step(state, "verify", "completed", supported=len(verified), unsupported=len(failed))
        return {
            "verified": [c.model_dump(mode="json") for c in verified],
            "failed": [c.model_dump(mode="json") for c in failed],
            "degraded": degraded,
        }

    async def re_retrieve(state: AskState) -> dict:
        attempt = state.get("attempts", 0) + 1
        failed = state.get("failed") or []
        step(state, "re_retrieve", "started", attempt=attempt, claims=len(failed))
        kinds = state.get("source_kinds")
        found: list[dict] = []
        for claim in failed:
            query = RetrievalQuery(
                tenant_id=UUID(state["tenant_id"]),
                text=claim["text"],
                as_of=_dt(state["as_of"]),
                source_kinds=tuple(kinds) if kinds else None,
            )
            items = await deps.retriever.retrieve(query, top_k=cfg.re_retrieve_top_k)
            outcome = await deps.reranker.rerank(claim["text"], items, top_n=cfg.re_retrieve_top_n)
            found.extend(e.model_dump(mode="json") for e in outcome.items)
        step(state, "re_retrieve", "completed", attempt=attempt, found=len(found))
        return {"evidence": found, "attempts": attempt}

    async def respond(state: AskState) -> dict:
        as_of = _dt(state["as_of"])
        degraded = bool(state.get("degraded"))
        if state.get("refused"):
            answer = AnswerSchema(status="refused", answer=REFUSAL, as_of=as_of, confidence=0.0)
        elif state.get("cache_hit"):
            answer = AnswerSchema.model_validate(state["cache_hit"]).model_copy(
                update={"cached": True, "answer_id": None, "cost_usd": 0.0}
            )
        else:
            verified = [Claim.model_validate(c) for c in state.get("verified") or []]
            failed = [Claim.model_validate(c) for c in state.get("failed") or []]
            if verified:
                draft_answer = (state.get("draft") or {}).get("answer", "")
                text = (
                    draft_answer
                    if not failed and draft_answer
                    else " ".join(c.text for c in verified)
                )
                citations, seen = [], set()
                for claim in verified:
                    for c in claim.citations:
                        if (c.chunk_id, c.quote) not in seen:
                            seen.add((c.chunk_id, c.quote))
                            citations.append(c)
                confidence = len(verified) / (len(verified) + len(failed))
                answer = AnswerSchema(
                    status="answered",
                    answer=text,
                    claims=verified,
                    citations=citations,
                    dropped_claims=failed,
                    as_of=as_of,
                    confidence=round(confidence * (0.9 if degraded else 1.0), 3),
                    degraded=degraded,
                )
            else:
                answer = AnswerSchema(
                    status="insufficient_evidence",
                    answer=(
                        "There is not enough in-force evidence to answer this as of "
                        f"{as_of.date().isoformat()}."
                    ),
                    dropped_claims=failed,
                    nearest_sources=nearest_sources(_evidence(state), cfg.nearest_sources),
                    as_of=as_of,
                    confidence=0.0,
                    degraded=degraded,
                )
            # Only cited answers are cached: an uncited one (insufficient evidence) could
            # never be invalidated by drift, so new documents would go unseen until TTL.
            if deps.cache is not None and answer.status == "answered" and answer.citations:
                await deps.cache.store(
                    tenant_id=UUID(state["tenant_id"]),
                    question=state["question"],
                    as_of=as_of,
                    answer=answer.model_dump(mode="json"),
                    version_ids=[c.version_id for c in answer.citations],
                    source_kinds=state.get("source_kinds"),
                )
        step(state, "respond", "completed", outcome=answer.status, error=state.get("draft_error"))
        return {"answer": answer.model_dump(mode="json")}

    def after_classify(state: AskState) -> str:
        return "respond" if state.get("refused") or state.get("empty_corpus") else "cache"

    def after_cache(state: AskState) -> str:
        return "respond" if state.get("cache_hit") else "plan"

    def after_merge(state: AskState) -> str:
        return "draft" if state.get("evidence") else "respond"

    def after_draft(state: AskState) -> str:
        return "verify" if state.get("draft") is not None else "respond"

    def after_verify(state: AskState) -> str:
        if state.get("failed") and state.get("attempts", 0) < cfg.max_verify_retries:
            return "re_retrieve"
        return "respond"

    def traced(name: str, fn: Callable[[Any], Awaitable[dict]]):
        async def node(state):
            with deps.tracer.span(f"node.{name}", node=name, job_id=state.get("job_id")):
                return await fn(state)

        return node

    graph = StateGraph(AskState)
    for name, fn in (
        ("classify", classify),
        ("cache", cache_lookup),
        ("plan", plan),
        ("subagent", subagent),
        ("merge", merge),
        ("draft", draft),
        ("verify", verify),
        ("re_retrieve", re_retrieve),
        ("respond", respond),
    ):
        graph.add_node(name, traced(name, fn))
    graph.add_edge(START, "classify")
    graph.add_conditional_edges("classify", after_classify, ["cache", "respond"])
    graph.add_conditional_edges("cache", after_cache, ["plan", "respond"])
    graph.add_conditional_edges("plan", fan_out, ["subagent"])
    graph.add_edge("subagent", "merge")
    graph.add_conditional_edges("merge", after_merge, ["draft", "respond"])
    graph.add_conditional_edges("draft", after_draft, ["verify", "respond"])
    graph.add_conditional_edges("verify", after_verify, ["re_retrieve", "respond"])
    graph.add_edge("re_retrieve", "draft")
    graph.add_edge("respond", END)
    return graph


def nearest_sources(evidence: list[Evidence], limit: int) -> list[NearestSource]:
    out, seen = [], set()
    for e in evidence:
        if e.version_id in seen:
            continue
        seen.add(e.version_id)
        out.append(
            NearestSource(
                document_id=e.document_id,
                external_id=e.external_id,
                title=e.title,
                version_id=e.version_id,
                version_no=e.version_no,
                section_path=e.section_path,
                valid_from=e.valid_from,
                valid_to=e.valid_to,
            )
        )
        if len(out) == limit:
            break
    return out


EventSink = Callable[[BaseModel], Awaitable[Any]]


async def run_ask(
    graph, job: AskJob, *, emit: EventSink, clock: Clock | None = None
) -> AnswerSchema:
    """Run (or resume) the graph for one job; forwards node events to `emit`.

    The checkpointer thread is the job id: when a checkpoint with pending nodes exists
    (a worker died mid-run), the run resumes from it instead of starting over.
    """
    clock = clock or SystemClock()
    config = {"configurable": {"thread_id": str(job.job_id)}}
    snapshot = await graph.aget_state(config)
    if snapshot.values.get("answer") and not snapshot.next:
        return AnswerSchema.model_validate(snapshot.values["answer"])
    inputs = None if snapshot.next else initial_state(job, started_at=clock.now())
    final: dict = {}
    async for mode, chunk in graph.astream(inputs, config, stream_mode=["custom", "values"]):
        if mode == "custom":
            await emit(ASK_EVENT_ADAPTER.validate_python(chunk))
        else:
            final = chunk
    return AnswerSchema.model_validate(final["answer"])
