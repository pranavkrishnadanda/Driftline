"""The review queue (P4 T5): idempotent open, exactly-once resolve, and the per-kind
effects of a resolution, against real Postgres, Redis and TEI."""

import asyncio
import json
from contextlib import AsyncExitStack
from datetime import UTC, datetime

import pytest
from agentkit import AgentKit, finals
from dbseed import (
    EMBED_MODEL,
    VersionSeed,
    embed_all,
    seed_history,
    seed_source,
    seed_watched_answer,
)

from driftline.agents.schemas import AGENT_STREAM, AskJob
from driftline.cache.semantic import SemanticCache
from driftline.clock import ManualClock
from driftline.drift.alerts import AlertLog
from driftline.ingest.outbox import OutboxRelay
from driftline.llm.adapters.deterministic import DeterministicAdapter
from driftline.llm.adapters.tei import TEIEmbeddingAdapter
from driftline.llm.router import LLMRouter, Route
from driftline.retrieval.hybrid import HybridRetriever
from driftline.retrieval.types import RetrievalQuery
from driftline.review.queue import (
    AlreadyResolved,
    InvalidResolution,
    ReviewNotFound,
    ReviewQueue,
)
from driftline.streams.bus import StreamBus

OLD_RULE = "Check ALT every 12 weeks during therapy."
NEW_RULE = "Check ALT monthly during therapy."
JUNE = datetime(2024, 6, 1, tzinfo=UTC)


@pytest.fixture
def queue(fresh_pool):
    return ReviewQueue(fresh_pool)


def relay(pool, redis_client) -> OutboxRelay:
    return OutboxRelay(pool, StreamBus(redis_client), alerts=AlertLog(redis_client))


async def agent_messages(redis_client, pool) -> list[AskJob]:
    """The follow-up asks on the `agent` stream, after the outbox relay has run."""
    await relay(pool, redis_client).relay_once()
    entries = await redis_client.xrange(AGENT_STREAM)
    return [AskJob.model_validate(json.loads(fields["data"])) for _, fields in entries]


async def pending_relation(conn, *, embedder_url=None):
    """Tenant with a Lipitor label and a hepatic guide whose version may supersede it;
    the relation is pending review, as supersession leaves an unsure one."""
    tenant, source = await seed_source(conn, kind="openfda")
    lipitor, _, _ = await seed_history(
        conn,
        source,
        external_id="lipitor",
        title="Lipitor label",
        versions=[VersionSeed(datetime(2023, 1, 1, tzinfo=UTC), [("Liver", OLD_RULE)])],
    )
    _, [guide_v], _ = await seed_history(
        conn,
        source,
        external_id="hepatic-guide",
        title="Hepatic monitoring guide",
        versions=[VersionSeed(datetime(2024, 1, 1, tzinfo=UTC), [("Liver", NEW_RULE)])],
    )
    if embedder_url:
        await embed_all(conn, embedder_url)
    relation = await conn.fetchval(
        "INSERT INTO relations (src_version_id, dst_document_id, kind, confidence, status) "
        "VALUES ($1, $2, 'supersedes', 0.7, 'pending_review') RETURNING id",
        guide_v,
        lipitor,
    )
    return tenant, relation


# --- open / list -----------------------------------------------------------------------


async def test_opening_the_same_item_twice_gives_one_row(queue, fresh_conn):
    tenant, relation = await pending_relation(fresh_conn)
    first = await queue.open("relation", relation, tenant, {"reason": "low_confidence"})
    again = await queue.open("relation", relation, tenant, {"reason": "low_confidence"})
    assert first is not None and again is None
    assert await fresh_conn.fetchval("SELECT count(*) FROM review_items") == 1
    [item] = await queue.list(tenant)
    assert (item.id, item.kind, item.ref_id, item.status) == (first, "relation", relation, "open")
    assert item.payload == {"reason": "low_confidence"}


async def test_list_is_tenant_scoped_and_filters_by_kind_and_status(queue, fresh_conn):
    tenant, relation = await pending_relation(fresh_conn)
    other, other_relation = await pending_relation(fresh_conn)
    rel_item = await queue.open("relation", relation, tenant, {})
    await queue.open("relation", other_relation, other, {})
    answer = await fresh_conn.fetchval("SELECT gen_random_uuid()")
    broken = await queue.open("broken_answer", answer, tenant, {"reason": "broken"})
    assert {i.id for i in await queue.list(tenant)} == {rel_item, broken}
    assert [i.id for i in await queue.list(tenant, kind="relation")] == [rel_item]
    await queue.resolve(rel_item, "reject", None, by="a", tenant_id=tenant)
    assert [i.id for i in await queue.list(tenant)] == [broken]
    assert [i.id for i in await queue.list(tenant, status="resolved")] == [rel_item]


# --- resolve: exactly once -------------------------------------------------------------


async def test_resolving_twice_raises_already_resolved(queue, fresh_conn):
    tenant, relation = await pending_relation(fresh_conn)
    item = await queue.open("relation", relation, tenant, {})
    done = await queue.resolve(item, "approve", None, by="alice", tenant_id=tenant)
    assert done.status == "resolved" and done.resolution["action"] == "approve"
    with pytest.raises(AlreadyResolved):
        await queue.resolve(item, "reject", None, by="bob", tenant_id=tenant)
    row = await fresh_conn.fetchrow(
        "SELECT r.status, i.resolved_by FROM relations r, review_items i "
        "WHERE r.id = $1 AND i.id = $2",
        relation,
        item,
    )
    assert (row["status"], row["resolved_by"]) == ("applied", "alice")  # first one won


async def test_concurrent_resolve_exactly_one_succeeds(queue, fresh_conn):
    tenant, relation = await pending_relation(fresh_conn)
    item = await queue.open("relation", relation, tenant, {})
    results = await asyncio.gather(
        queue.resolve(item, "approve", None, by="a", tenant_id=tenant),
        queue.resolve(item, "reject", None, by="b", tenant_id=tenant),
        return_exceptions=True,
    )
    winners = [r for r in results if not isinstance(r, Exception)]
    losers = [r for r in results if isinstance(r, Exception)]
    assert len(winners) == 1 and [type(e) for e in losers] == [AlreadyResolved]
    expected = "applied" if winners[0].resolution["action"] == "approve" else "rejected"
    assert await fresh_conn.fetchval("SELECT status FROM relations") == expected


async def test_another_tenants_item_is_not_found(queue, fresh_conn):
    tenant, relation = await pending_relation(fresh_conn)
    other, _ = await seed_source(fresh_conn)
    item = await queue.open("relation", relation, tenant, {})
    with pytest.raises(ReviewNotFound):
        await queue.resolve(item, "approve", None, by="x", tenant_id=other)
    assert await fresh_conn.fetchval("SELECT status FROM relations") == "pending_review"


async def test_invalid_edits_are_refused_and_leave_the_item_open(queue, fresh_conn):
    tenant, relation = await pending_relation(fresh_conn)
    item = await queue.open("relation", relation, tenant, {})
    for action, edit in (
        ("edit", None),
        ("edit", {"kind": "replaces"}),
        ("approve", {"kind": "amends"}),
    ):
        with pytest.raises(InvalidResolution):
            await queue.resolve(item, action, edit, by="x", tenant_id=tenant)
    assert await fresh_conn.fetchval("SELECT status FROM review_items") == "open"


# --- relations -------------------------------------------------------------------------


async def test_approving_a_relation_applies_it_and_retrieval_hides_the_superseded_document(
    queue, fresh_conn, fresh_pool, embedder_url
):
    tenant, relation = await pending_relation(fresh_conn, embedder_url=embedder_url)
    router = LLMRouter(
        providers={"tei": TEIEmbeddingAdapter(embedder_url)},
        chains={"embed": [Route("tei", EMBED_MODEL)]},
        clock=ManualClock(),
    )
    retriever = HybridRetriever(fresh_pool, router, embed_model=EMBED_MODEL)
    query = RetrievalQuery(tenant_id=tenant, text="How often should ALT be checked?", as_of=JUNE)
    before = await retriever.retrieve(query)
    assert {e.external_id for e in before} == {"lipitor", "hepatic-guide"}

    item = await queue.open("relation", relation, tenant, {"reason": "low_confidence"})
    await queue.resolve(item, "approve", None, by="alice", tenant_id=tenant)

    assert await fresh_conn.fetchval("SELECT status FROM relations") == "applied"
    after = await retriever.retrieve(query)
    assert {e.external_id for e in after} == {"hepatic-guide"}


async def test_rejecting_a_relation_marks_it_rejected(queue, fresh_conn):
    tenant, relation = await pending_relation(fresh_conn)
    item = await queue.open("relation", relation, tenant, {})
    await queue.resolve(item, "reject", None, by="alice", tenant_id=tenant)
    assert await fresh_conn.fetchval("SELECT status FROM relations") == "rejected"
    assert await fresh_conn.fetchval("SELECT count(*) FROM eval_cases") == 0
    assert await fresh_conn.fetchval("SELECT count(*) FROM outbox") == 0  # cache untouched


async def test_approving_a_relation_invalidates_cached_answers_citing_the_superseded_document(
    queue, fresh_conn, fresh_pool, redis_client
):
    tenant, relation = await pending_relation(fresh_conn)
    versions = {
        r["external_id"]: r["id"]
        for r in await fresh_conn.fetch(
            "SELECT v.id, d.external_id FROM doc_versions v JOIN documents d ON d.id = v.document_id"
        )
    }
    router = LLMRouter(
        providers={"det": DeterministicAdapter("det")},
        chains={"embed": [Route("det", "hash")]},
        clock=ManualClock(),
    )
    cache = SemanticCache(redis_client, router)
    stale = await cache.store(
        tenant_id=tenant,
        question="How often should ALT be checked?",
        as_of=JUNE,
        answer={"answer": OLD_RULE},
        version_ids=[versions["lipitor"]],
    )
    kept = await cache.store(
        tenant_id=tenant,
        question="What does the hepatic guide say?",
        as_of=JUNE,
        answer={"answer": NEW_RULE},
        version_ids=[versions["hepatic-guide"]],
    )
    item = await queue.open("relation", relation, tenant, {"reason": "low_confidence"})
    await queue.resolve(item, "approve", None, by="alice", tenant_id=tenant)
    assert await redis_client.exists(f"semcache:entry:{stale}") == 1  # until the relay runs
    await relay(fresh_pool, redis_client).relay_once()

    assert await redis_client.exists(f"semcache:entry:{stale}") == 0
    assert await redis_client.exists(f"semcache:entry:{kept}") == 1
    # The replaced label's answer is no longer served: its version is still inside its
    # validity window, so the lookup's in-force re-check alone would have served it.
    async with fresh_pool.acquire() as conn:
        gone = await cache.lookup(
            conn, tenant_id=tenant, question="How often should ALT be checked?", as_of=JUNE
        )
        hit = await cache.lookup(
            conn, tenant_id=tenant, question="What does the hepatic guide say?", as_of=JUNE
        )
    assert gone is None
    assert hit is not None and hit.entry_id == kept


async def test_an_edit_applies_the_corrected_relation_and_creates_an_eval_case(queue, fresh_conn):
    tenant, relation = await pending_relation(fresh_conn)
    item = await queue.open("relation", relation, tenant, {})
    await queue.resolve(item, "edit", {"kind": "amends"}, by="alice", tenant_id=tenant)
    rel = await fresh_conn.fetchrow("SELECT kind, status FROM relations")
    assert (rel["kind"], rel["status"]) == ("amends", "applied")
    case = await fresh_conn.fetchrow("SELECT * FROM eval_cases")
    assert (case["tenant_id"], case["source_review_id"]) == (tenant, item)
    expected = json.loads(case["expected"])
    assert expected["review_kind"] == "relation" and expected["edit"] == {"kind": "amends"}
    assert "Hepatic monitoring guide" in case["question"] and "Lipitor label" in case["question"]


async def test_malformed_extraction_items_resolve_without_a_relation(queue, fresh_conn):
    tenant, source = await seed_source(fresh_conn)
    _, [version], _ = await seed_history(
        fresh_conn,
        source,
        external_id="d",
        title="D",
        versions=[VersionSeed(JUNE, [("A", "alpha")])],
    )
    item = await queue.open("relation", version, tenant, {"error": "malformed_extraction"})
    done = await queue.resolve(item, "approve", None, by="a", tenant_id=tenant)
    assert done.status == "resolved"


# --- broken answers --------------------------------------------------------------------


@pytest.fixture
async def kit(fresh_pool, redis_client, fresh_dsn, embedder_url):
    async with AsyncExitStack() as stack:
        yield AgentKit(fresh_pool, redis_client, fresh_dsn, embedder_url, stack)


async def broken_watched_answer(conn, embedder_url):
    """A watched answer citing v1 of a label whose cited section v2 removed."""
    tenant, source = await seed_source(conn, kind="openfda")
    _, versions, chunks = await seed_history(
        conn,
        source,
        external_id="lipitor",
        title="Lipitor label",
        versions=[
            VersionSeed(datetime(2023, 1, 1, tzinfo=UTC), [("Liver", OLD_RULE)]),
            VersionSeed(datetime(2024, 4, 15, tzinfo=UTC), [("Hepatic", NEW_RULE)]),
        ],
    )
    await embed_all(conn, embedder_url)
    answer = await seed_watched_answer(
        conn,
        tenant,
        versions[0],
        [chunks[0][0]],
        [(OLD_RULE, OLD_RULE)],
        question="How often should ALT be checked?",
    )
    return tenant, answer, versions, chunks


async def test_approved_broken_answer_regenerates_through_run_ask(
    queue, kit, fresh_conn, fresh_pool, redis_client, embedder_url
):
    tenant, answer, _, chunks = await broken_watched_answer(fresh_conn, embedder_url)
    item = await queue.open("broken_answer", answer, tenant, {"reason": "broken"})
    done = await queue.resolve(item, "approve", None, by="alice", tenant_id=tenant)

    [job] = await agent_messages(redis_client, fresh_pool)
    assert job.answer_id == answer and job.tenant_id == tenant and job.as_of is None
    assert job.question == "How often should ALT be checked?"
    assert done.resolution["job_id"] == str(job.job_id)
    assert await fresh_conn.fetchval("SELECT status FROM jobs WHERE id = $1", job.job_id) == (
        "queued"
    )

    # The worker regenerates it; a watched answer always pauses for review first.
    await kit.restart()
    await kit.drain()
    regen = await fresh_conn.fetchrow(
        "SELECT id, payload FROM review_items WHERE kind = 'low_confidence_answer'"
    )
    assert json.loads(regen["payload"])["reason"] == "watched_answer"
    await queue.resolve(regen["id"], "approve", None, by="alice", tenant_id=tenant)
    await kit.drain()

    [final] = finals(await kit.job_events(job.job_id))
    assert final.answer.answer == NEW_RULE and final.answer.answer_id == answer
    # The answer now belongs to its latest job (still one answer per job).
    assert await fresh_conn.fetchval("SELECT job_id FROM answers WHERE id = $1", answer) == (
        job.job_id
    )
    cited = await fresh_conn.fetch(
        "SELECT chunk_id FROM answer_citations WHERE answer_id = $1", answer
    )
    assert [r["chunk_id"] for r in cited] == [chunks[1][0]]  # now cites v2


async def test_rejected_broken_answer_is_not_regenerated(
    queue, fresh_conn, fresh_pool, redis_client
):
    tenant, _ = await seed_source(fresh_conn)
    answer = await fresh_conn.fetchval(
        "INSERT INTO answers (tenant_id, question, as_of, body) "
        "VALUES ($1, 'q', now(), '{}') RETURNING id",
        tenant,
    )
    item = await queue.open("broken_answer", answer, tenant, {"reason": "broken"})
    await queue.resolve(item, "reject", None, by="a", tenant_id=tenant)
    assert await agent_messages(redis_client, fresh_pool) == []


async def test_legacy_answer_kind_items_resolve_like_broken_answers(
    queue, fresh_conn, fresh_pool, redis_client
):
    tenant, _ = await seed_source(fresh_conn)
    answer = await fresh_conn.fetchval(
        "INSERT INTO answers (tenant_id, question, as_of, body) "
        "VALUES ($1, 'What changed?', now(), '{}') RETURNING id",
        tenant,
    )
    item = await fresh_conn.fetchval(
        "INSERT INTO review_items (kind, ref_id, tenant_id, payload) "
        "VALUES ('answer', $1, $2, '{\"reason\": \"broken\"}') RETURNING id",
        answer,
        tenant,
    )
    assert [i.id for i in await queue.list(tenant, kind="broken_answer")] == [item]
    await queue.resolve(item, "edit", {"answer": "It is monthly now."}, by="a", tenant_id=tenant)
    [job] = await agent_messages(redis_client, fresh_pool)
    assert job.answer_id == answer and job.question == "What changed?"
    case = await fresh_conn.fetchrow("SELECT question, expected FROM eval_cases")
    assert case["question"] == "What changed?"
    assert json.loads(case["expected"])["edit"] == {"answer": "It is monthly now."}
