"""Human-in-the-loop (spec section 5): a low-confidence or watched answer pauses the
answer graph with LangGraph `interrupt()`, opens a review item, and resumes the SAME
checkpointed thread with `Command(resume=...)` once a reviewer resolves it, even in a
new worker process. Real Postgres (+ checkpointer), Redis and TEI; no mocks."""

import asyncio
import json
from contextlib import AsyncExitStack
from datetime import UTC, datetime

import pytest
from agentkit import AgentKit, finals, half_supported_draft, review_steps
from dbseed import VersionSeed, embed_all, seed_history, seed_source, seed_watched_answer

from driftline.agents.events import StepEvent
from driftline.agents.schemas import AGENT_GROUP, AGENT_STREAM
from driftline.review.queue import AlreadyResolved, ReviewQueue

RULE = "Check ALT monthly during therapy."
WRONG = "Check ALT every day."
QUESTION = "How often should ALT be checked?"


@pytest.fixture
async def corpus(fresh_conn, embedder_url):
    tenant, source = await seed_source(fresh_conn, kind="openfda")
    _, versions, chunks = await seed_history(
        fresh_conn,
        source,
        external_id="lipitor",
        title="Lipitor label",
        versions=[VersionSeed(datetime(2024, 4, 15, tzinfo=UTC), [("Liver", RULE)])],
    )
    await embed_all(fresh_conn, embedder_url)
    return {"tenant": tenant, "version": versions[0], "chunk": chunks[0][0]}


@pytest.fixture
async def kit(fresh_pool, redis_client, fresh_dsn, embedder_url):
    async with AsyncExitStack() as stack:
        yield AgentKit(fresh_pool, redis_client, fresh_dsn, embedder_url, stack)


def low_confidence_script(corpus) -> list:
    # plan (responder), then a draft in which only one of two claims is supported.
    return [None, half_supported_draft(corpus["chunk"], corpus["version"], RULE, WRONG)]


async def pause_low_confidence_ask(kit, corpus):
    await kit.restart(low_confidence_script(corpus))
    job = await kit.enqueue(corpus["tenant"], QUESTION)
    assert await kit.drain() == 1
    return job


async def test_low_confidence_answer_interrupts_and_opens_a_review_item(
    kit, corpus, fresh_conn, redis_client
):
    job = await pause_low_confidence_ask(kit, corpus)

    assert await fresh_conn.fetchval("SELECT status FROM jobs WHERE id = $1", job.job_id) == (
        "needs_review"
    )
    [item] = await fresh_conn.fetch("SELECT * FROM review_items")
    assert (item["kind"], item["ref_id"], item["tenant_id"], item["status"]) == (
        "low_confidence_answer",
        job.job_id,
        corpus["tenant"],
        "open",
    )
    payload = json.loads(item["payload"])
    assert payload["reason"] == "low_confidence"
    assert payload["question"] == QUESTION
    assert payload["answer"]["confidence"] == 0.5
    assert await fresh_conn.fetchval("SELECT count(*) FROM answers") == 0  # not persisted yet

    events = await kit.job_events(job.job_id)
    assert review_steps(events) == ["waiting"]
    waiting = next(e for e in events if isinstance(e, StepEvent) and e.node == "review")
    assert waiting.detail["reason"] == "low_confidence"
    assert finals(events) == []
    assert (await redis_client.xpending(AGENT_STREAM, AGENT_GROUP))["pending"] == 0  # acked

    snapshot = await kit.graph.aget_state({"configurable": {"thread_id": str(job.job_id)}})
    assert snapshot.next == ("review",) and snapshot.interrupts


async def test_resume_after_worker_restart_applies_the_reviewers_edit(kit, corpus, fresh_conn):
    job = await pause_low_confidence_ask(kit, corpus)
    item_id = await fresh_conn.fetchval("SELECT id FROM review_items")

    await kit.restart()  # a new process: new checkpointer connection, graph and worker
    queue = ReviewQueue(kit.pool, kit.bus)
    resolved = await queue.resolve(
        item_id, "edit", {"answer": RULE}, by="alice", tenant_id=corpus["tenant"]
    )
    assert resolved.status == "resolved" and resolved.resolved_by == "alice"
    assert await kit.drain() == 1

    assert kit.det.calls == []  # resumed at the review node: nothing was re-drafted
    events = await kit.job_events(job.job_id)
    assert review_steps(events) == ["waiting", "completed"]
    [final] = finals(events)
    assert final.answer.answer == RULE and final.answer.answer_id is not None
    row = await fresh_conn.fetchrow(
        "SELECT a.body, j.status FROM answers a JOIN jobs j ON j.id = a.job_id WHERE a.job_id = $1",
        job.job_id,
    )
    assert row["status"] == "succeeded"
    assert json.loads(row["body"])["answer"] == RULE
    case = await fresh_conn.fetchrow("SELECT * FROM eval_cases")
    assert (case["tenant_id"], case["source_review_id"], case["question"]) == (
        corpus["tenant"],
        item_id,
        QUESTION,
    )
    assert json.loads(case["expected"])["edit"] == {"answer": RULE}


async def test_rejected_answer_resumes_into_an_explained_non_answer(kit, corpus, fresh_conn):
    job = await pause_low_confidence_ask(kit, corpus)
    item_id = await fresh_conn.fetchval("SELECT id FROM review_items")
    await ReviewQueue(kit.pool, kit.bus).resolve(
        item_id, "reject", None, by="bob", tenant_id=corpus["tenant"]
    )
    await kit.drain()
    [final] = finals(await kit.job_events(job.job_id))
    assert final.answer.status == "insufficient_evidence" and final.answer.claims == []
    assert final.answer.confidence == 0.0
    assert await fresh_conn.fetchval("SELECT count(*) FROM eval_cases") == 0  # no edit


async def test_concurrent_resolves_resume_the_graph_exactly_once(kit, corpus, fresh_conn):
    job = await pause_low_confidence_ask(kit, corpus)
    item_id = await fresh_conn.fetchval("SELECT id FROM review_items")
    queue = ReviewQueue(kit.pool, kit.bus)
    results = await asyncio.gather(
        queue.resolve(item_id, "approve", None, by="a", tenant_id=corpus["tenant"]),
        queue.resolve(item_id, "approve", None, by="b", tenant_id=corpus["tenant"]),
        return_exceptions=True,
    )
    assert sorted(type(r).__name__ for r in results) == ["AlreadyResolved", "ReviewItem"]
    assert await kit.drain() == 1  # exactly one resume message was published
    events = await kit.job_events(job.job_id)
    assert review_steps(events) == ["waiting", "completed"]
    assert len(finals(events)) == 1
    with pytest.raises(AlreadyResolved):
        await queue.resolve(item_id, "approve", None, by="c", tenant_id=corpus["tenant"])


async def test_redelivered_messages_neither_reopen_review_nor_resume_twice(kit, corpus, fresh_conn):
    job = await pause_low_confidence_ask(kit, corpus)
    item_id = await fresh_conn.fetchval("SELECT id FROM review_items")
    # The original ask, delivered again while the item is still open: nothing happens.
    await kit.bus.publish(AGENT_STREAM, job.model_dump(mode="json"))
    await kit.drain()
    assert await fresh_conn.fetchval("SELECT count(*) FROM review_items") == 1
    assert review_steps(await kit.job_events(job.job_id)) == ["waiting"]

    await ReviewQueue(kit.pool, kit.bus).resolve(
        item_id, "approve", None, by="a", tenant_id=corpus["tenant"]
    )
    # ...and again after it was resolved but before the resume message ran: no new item.
    await kit.worker.handle_ask("0-1", job.model_dump(mode="json"))
    assert await fresh_conn.fetchval("SELECT count(*) FROM review_items") == 1
    await kit.drain()
    assert await fresh_conn.fetchval("SELECT count(*) FROM review_items") == 1
    resume = await fresh_conn.fetchval("SELECT resolution FROM review_items WHERE id = $1", item_id)
    assert json.loads(resume)["action"] == "approve"
    events = await kit.job_events(job.job_id)
    assert review_steps(events) == ["waiting", "completed"]
    assert len(finals(events)) == 1


async def test_confident_unwatched_answer_is_not_interrupted(kit, corpus, fresh_conn):
    await kit.restart()
    job = await kit.enqueue(corpus["tenant"], QUESTION)
    await kit.drain()
    events = await kit.job_events(job.job_id)
    assert review_steps(events) == []
    assert finals(events)[0].answer.confidence == 1.0
    assert await fresh_conn.fetchval("SELECT count(*) FROM review_items") == 0


async def test_regenerating_a_watched_answer_always_goes_to_review(kit, corpus, fresh_conn):
    answer_id = await seed_watched_answer(
        fresh_conn,
        corpus["tenant"],
        corpus["version"],
        [corpus["chunk"]],
        [("ALT is checked weekly.", RULE)],
        question=QUESTION,
    )
    await kit.restart()
    job = await kit.enqueue(corpus["tenant"], QUESTION, answer_id=answer_id)
    await kit.drain()
    item = await fresh_conn.fetchrow("SELECT id, payload FROM review_items")
    payload = json.loads(item["payload"])
    assert payload["reason"] == "watched_answer" and payload["answer"]["confidence"] == 1.0
    assert payload["answer_id"] == str(answer_id)

    await ReviewQueue(kit.pool, kit.bus).resolve(
        item["id"], "approve", None, by="a", tenant_id=corpus["tenant"]
    )
    await kit.drain()
    # The watched answer itself is updated in place: same id, still watched.
    row = await fresh_conn.fetchrow(
        "SELECT body, watched, confidence FROM answers WHERE id = $1", answer_id
    )
    assert row["watched"] is True and row["confidence"] == 1.0
    assert json.loads(row["body"])["answer"] == RULE
    assert await fresh_conn.fetchval("SELECT count(*) FROM answers") == 1
    cited = await fresh_conn.fetch(
        "SELECT chunk_id FROM answer_citations WHERE answer_id = $1", answer_id
    )
    assert [r["chunk_id"] for r in cited] == [corpus["chunk"]]
    assert await fresh_conn.fetchval("SELECT status FROM jobs WHERE id = $1", job.job_id) == (
        "succeeded"
    )
