import math

import pytest
from dbseed import seed_source, seed_version

from driftline.clock import ManualClock
from driftline.ingest.embed import EmbedStage, to_pgvector
from driftline.llm.adapters.deterministic import DeterministicAdapter
from driftline.llm.adapters.tei import TEIEmbeddingAdapter
from driftline.llm.router import AllRoutesFailed, LLMRouter, Route
from driftline.llm.types import ProviderError

EMBED_MODEL = "BAAI/bge-base-en-v1.5"


def embed_router(provider, model: str) -> LLMRouter:
    return LLMRouter(
        providers={provider.name: provider},
        chains={"embed": [Route(provider.name, model)]},
        clock=ManualClock(),
    )


async def seeded_version(conn, n: int):
    _, source = await seed_source(conn)
    texts = [("A", f"chunk number {i} about hepatotoxicity") for i in range(n)]
    _, version = await seed_version(conn, source, texts=texts)
    return version


def test_to_pgvector_format():
    assert to_pgvector([0.5, -1, 2.25]) == "[0.5,-1.0,2.25]"


def test_invalid_batch_size_is_rejected():
    with pytest.raises(ValueError):
        EmbedStage(embed_router(DeterministicAdapter(), "m"), model_name="m", batch_size=0)


@pytest.mark.slow
async def test_embeds_all_null_chunks_with_real_tei(fresh_conn, embedder_url):
    version = await seeded_version(fresh_conn, 5)
    stage = EmbedStage(
        embed_router(TEIEmbeddingAdapter(embedder_url), EMBED_MODEL),
        model_name=EMBED_MODEL,
        batch_size=2,
    )
    assert await stage.embed_version(fresh_conn, version) == 5
    rows = await fresh_conn.fetch(
        "SELECT embedding::text AS e, embed_model, vector_dims(embedding) AS d "
        "FROM chunks WHERE version_id = $1",
        version,
    )
    assert {r["embed_model"] for r in rows} == {EMBED_MODEL}
    assert {r["d"] for r in rows} == {768}
    first = [float(x) for x in rows[0]["e"].strip("[]").split(",")]
    assert math.isclose(math.sqrt(sum(x * x for x in first)), 1.0, abs_tol=1e-3)


@pytest.mark.slow
async def test_second_run_embeds_nothing(fresh_conn, embedder_url):
    version = await seeded_version(fresh_conn, 3)
    stage = EmbedStage(
        embed_router(TEIEmbeddingAdapter(embedder_url), EMBED_MODEL), model_name=EMBED_MODEL
    )
    assert await stage.embed_version(fresh_conn, version) == 3
    assert await stage.embed_version(fresh_conn, version) == 0


async def test_batches_respect_batch_size(fresh_conn):
    version = await seeded_version(fresh_conn, 5)
    adapter = DeterministicAdapter("det")
    stage = EmbedStage(embed_router(adapter, "det-embed"), model_name="det-embed", batch_size=2)
    assert await stage.embed_version(fresh_conn, version) == 5
    assert adapter.calls == ["det-embed"] * 3


async def test_provider_failure_keeps_completed_batches(fresh_conn):
    version = await seeded_version(fresh_conn, 4)
    adapter = DeterministicAdapter("det", script=[None, ProviderError("bad", retryable=False)])
    stage = EmbedStage(embed_router(adapter, "det-embed"), model_name="det-embed", batch_size=2)
    with pytest.raises(AllRoutesFailed):
        await stage.embed_version(fresh_conn, version)
    embedded = await fresh_conn.fetchval(
        "SELECT count(*) FROM chunks WHERE version_id = $1 AND embedding IS NOT NULL", version
    )
    assert embedded == 2
    assert await stage.embed_version(fresh_conn, version) == 2  # a redelivery finishes the rest
