import math

import pytest

from driftline.llm.adapters.tei import TEIEmbeddingAdapter
from driftline.llm.types import CompletionRequest, Message, ProviderError, Role

MODEL = "BAAI/bge-base-en-v1.5"


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


@pytest.mark.slow
async def test_embed_returns_768_dim_unit_vectors(embedder_url):
    adapter = TEIEmbeddingAdapter(embedder_url)
    vectors = await adapter.embed(MODEL, ["first text", "second text"], 768)
    assert len(vectors) == 2
    for vector in vectors:
        assert len(vector) == 768
        assert math.isclose(math.sqrt(sum(x * x for x in vector)), 1.0, abs_tol=1e-3)


@pytest.mark.slow
async def test_similar_texts_score_higher_than_unrelated(embedder_url):
    adapter = TEIEmbeddingAdapter(embedder_url)
    anchor, similar, unrelated = await adapter.embed(
        MODEL,
        ["boxed warning: liver toxicity", "hepatotoxicity warning", "kubectl rollout restart"],
        768,
    )
    assert _cosine(anchor, similar) > _cosine(anchor, unrelated)


@pytest.mark.slow
async def test_dimension_mismatch_raises_non_retryable(embedder_url):
    adapter = TEIEmbeddingAdapter(embedder_url)
    with pytest.raises(ProviderError) as info:
        await adapter.embed(MODEL, ["some text"], 384)
    assert info.value.retryable is False


@pytest.mark.slow
async def test_unreachable_embedder_is_retryable_provider_error():
    adapter = TEIEmbeddingAdapter("http://127.0.0.1:1", timeout_s=2.0)
    with pytest.raises(ProviderError) as info:
        await adapter.embed(MODEL, ["some text"], 768)
    assert info.value.retryable is True


@pytest.mark.slow
async def test_complete_is_unsupported():
    adapter = TEIEmbeddingAdapter("http://127.0.0.1:1")
    assert adapter.name == "tei"
    with pytest.raises(ProviderError) as info:
        await adapter.complete(
            MODEL, CompletionRequest(messages=[Message(role=Role.user, content="hi")])
        )
    assert info.value.retryable is False
    assert "embeddings only" in str(info.value)
