import asyncio
import math
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from dbseed import EMBED_MODEL, VersionSeed, seed_history, seed_source

from driftline.cache.semantic import SemanticCache, bucket_key, cosine
from driftline.clock import ManualClock
from driftline.llm.adapters.deterministic import DeterministicAdapter
from driftline.llm.adapters.tei import TEIEmbeddingAdapter
from driftline.llm.router import LLMRouter, Route

JUNE = datetime(2024, 6, 1, 12, tzinfo=UTC)
ANSWER = {"status": "answered", "answer": "Check ALT monthly.", "claims": []}
QUESTION = "How often should ALT be checked?"


def det_cache(redis_client, **kw) -> SemanticCache:
    # Hash-based vectors: identical text -> identical vector, anything else ~ orthogonal.
    router = LLMRouter(
        providers={"det": DeterministicAdapter("det")},
        chains={"embed": [Route("det", "hash")]},
        clock=ManualClock(),
    )
    return SemanticCache(redis_client, router, **kw)


async def seed_cited(conn, external_id: str = "lipitor"):
    """A tenant with one in-force document version; returns (tenant_id, version_id)."""
    tenant, source = await seed_source(conn)
    _, [v1], _ = await seed_history(
        conn,
        source,
        external_id=external_id,
        title=external_id,
        versions=[VersionSeed(datetime(2024, 1, 1, tzinfo=UTC), [("Liver", "Check ALT.")])],
    )
    return tenant, v1


@pytest.fixture
async def cited(fresh_conn):
    return await seed_cited(fresh_conn)


def at_angle(cos: float) -> list[float]:
    """A unit vector whose cosine similarity to [1, 0] is exactly `cos` (up to rounding)."""
    return [cos, math.sqrt(1 - cos * cos)]


def test_cosine_and_bucket_keys():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0
    tenant = uuid4()
    morning, night = JUNE.replace(hour=1), JUNE.replace(hour=23)
    assert bucket_key(tenant, morning, None) == bucket_key(tenant, night, None)
    assert bucket_key(tenant, JUNE, ["upload", "openfda"]) == bucket_key(
        tenant, JUNE, ["openfda", "upload"]
    )
    assert bucket_key(tenant, JUNE, None) != bucket_key(tenant, JUNE, ["openfda"])
    assert bucket_key(tenant, JUNE, None) != bucket_key(uuid4(), JUNE, None)


def test_bucket_day_is_the_utc_day_and_naive_as_of_is_rejected():
    tenant = uuid4()
    # 2024-06-02 01:00 at +05:30 is 2024-06-01 19:30 UTC: the same instant, the same bucket.
    ist = datetime(2024, 6, 2, 1, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert bucket_key(tenant, ist, None) == bucket_key(tenant, JUNE, None)
    with pytest.raises(ValueError, match="timezone"):
        bucket_key(tenant, datetime(2024, 6, 1, 12), None)


async def test_repeat_question_hits_only_in_its_own_bucket(redis_client, fresh_conn, cited):
    tenant, version = cited
    cache = det_cache(redis_client)
    await cache.store(
        tenant_id=tenant, question=QUESTION, as_of=JUNE, answer=ANSWER, version_ids=[version]
    )
    hit = await cache.lookup(fresh_conn, tenant_id=tenant, question=QUESTION, as_of=JUNE)
    assert hit is not None and hit.answer == ANSWER and hit.version_ids == [version]
    assert hit.similarity == pytest.approx(1.0)
    misses = [
        {"tenant_id": uuid4(), "question": QUESTION, "as_of": JUNE},
        {"tenant_id": tenant, "question": QUESTION, "as_of": datetime(2024, 6, 2, tzinfo=UTC)},
        {"tenant_id": tenant, "question": QUESTION, "as_of": JUNE, "source_kinds": ["openfda"]},
        {"tenant_id": tenant, "question": "What is the boxed warning?", "as_of": JUNE},
    ]
    for kwargs in misses:
        assert await cache.lookup(fresh_conn, **kwargs) is None, kwargs


async def test_two_tenants_asking_the_same_question_never_see_each_others_answer(
    redis_client, fresh_conn
):
    cache = det_cache(redis_client)
    tenant_a, version_a = await seed_cited(fresh_conn, "a-label")
    tenant_b, version_b = await seed_cited(fresh_conn, "b-label")
    answer_a, answer_b = {**ANSWER, "answer": "A"}, {**ANSWER, "answer": "B"}
    await cache.store(
        tenant_id=tenant_a, question=QUESTION, as_of=JUNE, answer=answer_a, version_ids=[version_a]
    )
    await cache.store(
        tenant_id=tenant_b, question=QUESTION, as_of=JUNE, answer=answer_b, version_ids=[version_b]
    )
    hit_a = await cache.lookup(fresh_conn, tenant_id=tenant_a, question=QUESTION, as_of=JUNE)
    hit_b = await cache.lookup(fresh_conn, tenant_id=tenant_b, question=QUESTION, as_of=JUNE)
    assert hit_a is not None and hit_a.answer == answer_a and hit_a.version_ids == [version_a]
    assert hit_b is not None and hit_b.answer == answer_b and hit_b.version_ids == [version_b]


async def test_entry_citing_another_tenants_version_is_never_served(redis_client, fresh_conn):
    # The in-force check is tenant-scoped: a version id from another tenant's corpus
    # does not count as in force for this tenant, even though it is in force for its owner.
    cache = det_cache(redis_client)
    tenant_a, _ = await seed_cited(fresh_conn, "a-label")
    _, version_b = await seed_cited(fresh_conn, "b-label")
    await cache.store(
        tenant_id=tenant_a, question=QUESTION, as_of=JUNE, answer=ANSWER, version_ids=[version_b]
    )
    assert await cache.lookup(fresh_conn, tenant_id=tenant_a, question=QUESTION, as_of=JUNE) is None


async def test_similarity_threshold_is_inclusive_at_0_95(redis_client, fresh_conn, cited):
    tenant, version = cited
    cache = det_cache(redis_client)  # default threshold, spec section 4
    await cache.store(
        tenant_id=tenant,
        question=QUESTION,
        as_of=JUNE,
        answer=ANSWER,
        version_ids=[version],
        vector=[1.0, 0.0],
    )

    async def lookup(cos: float):
        return await cache.lookup(
            fresh_conn, tenant_id=tenant, question="q", as_of=JUNE, vector=at_angle(cos)
        )

    hit = await lookup(0.951)
    assert hit is not None and hit.similarity == pytest.approx(0.951)
    assert await lookup(0.949) is None


async def test_paraphrase_hits_and_unrelated_question_misses(
    redis_client, fresh_conn, cited, embedder_url
):
    tenant, version = cited
    router = LLMRouter(
        providers={"tei": TEIEmbeddingAdapter(embedder_url)},
        chains={"embed": [Route("tei", EMBED_MODEL)]},
        clock=ManualClock(),
    )
    cache = SemanticCache(redis_client, router, threshold=0.95)
    await cache.store(
        tenant_id=tenant, question=QUESTION, as_of=JUNE, answer=ANSWER, version_ids=[version]
    )
    paraphrase = await cache.lookup(
        fresh_conn, tenant_id=tenant, question="How frequently should ALT be checked?", as_of=JUNE
    )
    assert paraphrase is not None and paraphrase.similarity >= 0.95
    unrelated = await cache.lookup(
        fresh_conn, tenant_id=tenant, question="How do I roll back a deployment?", as_of=JUNE
    )
    assert unrelated is None


async def test_answer_citing_a_superseded_version_is_a_miss_and_is_evicted(
    redis_client, fresh_conn, cited
):
    tenant, version = cited
    cache = det_cache(redis_client)
    entry_id = await cache.store(
        tenant_id=tenant, question=QUESTION, as_of=JUNE, answer=ANSWER, version_ids=[version]
    )
    # A new version takes effect on May 1: the cited version is no longer in force in June.
    await fresh_conn.execute(
        "UPDATE doc_versions SET valid_to = $2 WHERE id = $1",
        version,
        datetime(2024, 5, 1, tzinfo=UTC),
    )
    assert await cache.lookup(fresh_conn, tenant_id=tenant, question=QUESTION, as_of=JUNE) is None
    assert await redis_client.get(f"semcache:entry:{entry_id}") is None
    assert await redis_client.lrange(bucket_key(tenant, JUNE, None), 0, -1) == []


async def test_new_version_later_the_same_day_is_a_miss_after_it_takes_effect(
    redis_client, fresh_conn, cited
):
    # The bucket is a whole day but validity is checked at the exact as_of: an answer
    # cached in the morning is not served in the evening once a new version took effect.
    tenant, version = cited
    cache = det_cache(redis_client)
    morning, noon, evening = JUNE.replace(hour=8), JUNE.replace(hour=12), JUNE.replace(hour=20)
    await cache.store(
        tenant_id=tenant, question=QUESTION, as_of=morning, answer=ANSWER, version_ids=[version]
    )
    await fresh_conn.execute("UPDATE doc_versions SET valid_to = $2 WHERE id = $1", version, noon)
    assert (
        await cache.lookup(fresh_conn, tenant_id=tenant, question=QUESTION, as_of=evening) is None
    )


async def test_stale_best_match_falls_back_to_the_next_valid_one(redis_client, fresh_conn, cited):
    tenant, stale_version = cited
    _, [fresh_version], _ = await seed_history(
        fresh_conn,
        await fresh_conn.fetchval("SELECT id FROM sources WHERE tenant_id = $1", tenant),
        external_id="crestor",
        title="Crestor",
        versions=[VersionSeed(datetime(2024, 1, 1, tzinfo=UTC), [("Liver", "Check ALT.")])],
    )
    cache = det_cache(redis_client)
    stale, fresh = {**ANSWER, "answer": "stale"}, {**ANSWER, "answer": "fresh"}
    for answer, version, vector in (
        (stale, stale_version, [1.0, 0.0]),
        (fresh, fresh_version, at_angle(0.97)),
    ):
        await cache.store(
            tenant_id=tenant,
            question=QUESTION,
            as_of=JUNE,
            answer=answer,
            version_ids=[version],
            vector=vector,
        )
    await fresh_conn.execute(
        "UPDATE doc_versions SET valid_to = $2 WHERE id = $1",
        stale_version,
        datetime(2024, 5, 1, tzinfo=UTC),
    )
    hit = await cache.lookup(
        fresh_conn, tenant_id=tenant, question=QUESTION, as_of=JUNE, vector=[1.0, 0.0]
    )
    assert hit is not None and hit.answer == fresh
    assert len(await redis_client.lrange(bucket_key(tenant, JUNE, None), 0, -1)) == 1


async def test_invalidate_versions_drops_every_answer_citing_them(redis_client, fresh_conn, cited):
    tenant, version = cited
    cache = det_cache(redis_client)
    other_version = uuid4()
    for question, versions in ((QUESTION, [version]), ("Boxed warning?", [version, other_version])):
        await cache.store(
            tenant_id=tenant, question=question, as_of=JUNE, answer=ANSWER, version_ids=versions
        )
    await cache.store(
        tenant_id=tenant, question="Unrelated?", as_of=JUNE, answer=ANSWER, version_ids=[]
    )
    assert await cache.invalidate_versions([version]) == 2
    assert await cache.lookup(fresh_conn, tenant_id=tenant, question=QUESTION, as_of=JUNE) is None
    kept = await cache.lookup(fresh_conn, tenant_id=tenant, question="Unrelated?", as_of=JUNE)
    assert kept is not None
    assert await cache.invalidate_versions([version]) == 0


async def test_every_key_carries_the_ttl(redis_client, cited):
    tenant, version = cited
    cache = det_cache(redis_client, ttl_s=600)
    entry_id = await cache.store(
        tenant_id=tenant, question=QUESTION, as_of=JUNE, answer=ANSWER, version_ids=[version]
    )
    for key in (
        f"semcache:entry:{entry_id}",
        bucket_key(tenant, JUNE, None),
        f"semcache:version:{version}",
    ):
        assert 0 < await redis_client.ttl(key) <= 600, key


async def test_expired_entry_is_a_miss_and_is_pruned_from_its_bucket(
    redis_client, fresh_conn, cited
):
    tenant, version = cited
    long_lived = det_cache(redis_client)
    short_lived = det_cache(redis_client, ttl_s=1)
    await short_lived.store(
        tenant_id=tenant, question=QUESTION, as_of=JUNE, answer=ANSWER, version_ids=[version]
    )
    # A later, long-lived entry keeps the bucket alive past the first entry's expiry.
    await long_lived.store(
        tenant_id=tenant, question="Other?", as_of=JUNE, answer=ANSWER, version_ids=[version]
    )
    await asyncio.sleep(1.5)  # real Redis expiry; no clock to fake here
    assert (
        await long_lived.lookup(fresh_conn, tenant_id=tenant, question=QUESTION, as_of=JUNE) is None
    )
    assert len(await redis_client.lrange(bucket_key(tenant, JUNE, None), 0, -1)) == 1


async def test_bucket_keeps_only_the_newest_entries(redis_client, fresh_conn, cited):
    tenant, version = cited
    cache = det_cache(redis_client, max_entries_per_bucket=2)
    for n in range(3):
        await cache.store(
            tenant_id=tenant, question=f"q{n}", as_of=JUNE, answer=ANSWER, version_ids=[version]
        )
    assert len(await redis_client.lrange(bucket_key(tenant, JUNE, None), 0, -1)) == 2
    assert await cache.lookup(fresh_conn, tenant_id=tenant, question="q0", as_of=JUNE) is None
    assert await cache.lookup(fresh_conn, tenant_id=tenant, question="q2", as_of=JUNE)
