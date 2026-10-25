import socket
from datetime import UTC, datetime
from uuid import uuid4

from driftline.retrieval.rerank import TEIReranker
from driftline.retrieval.types import Evidence

QUERY = "How often should liver enzymes (ALT) be checked?"
TEXTS = [
    "Run kubectl rollout undo deployment/web to roll back.",
    "Severe hepatotoxicity has been reported.",
    "Check ALT monthly during therapy.",
]


def items(texts=TEXTS) -> list[Evidence]:
    return [
        Evidence(
            chunk_id=uuid4(),
            version_id=uuid4(),
            document_id=uuid4(),
            external_id=f"d{i}",
            title="Doc",
            section_path="",
            text=t,
            version_no=1,
            valid_from=datetime(2024, 1, 1, tzinfo=UTC),
            retrieved_as_of=datetime(2024, 6, 1, tzinfo=UTC),
            score=1 / (61 + i),
        )
        for i, t in enumerate(texts)
    ]


async def test_cross_encoder_moves_the_answer_to_the_top(reranker_url):
    outcome = await TEIReranker(reranker_url).rerank(QUERY, items(), top_n=2)
    assert outcome.reranked and outcome.error is None
    assert outcome.items[0].text == "Check ALT monthly during therapy."
    assert len(outcome.items) == 2
    assert outcome.items[0].rerank_score > outcome.items[1].rerank_score
    assert outcome.items[0].score == 1 / 63  # the RRF score is kept


async def test_more_items_than_one_tei_batch(reranker_url):
    many = items([f"Filler passage number {i} about rollouts." for i in range(40)] + [TEXTS[2]])
    outcome = await TEIReranker(reranker_url).rerank(QUERY, many, top_n=3)
    assert outcome.reranked
    assert outcome.items[0].text == TEXTS[2]


def closed_port() -> int:
    """A port that was just bound and released, so nothing listens on it: connecting gets
    a real refusal from the OS, not a simulated one."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_unreachable_reranker_keeps_rrf_order():
    url = f"http://127.0.0.1:{closed_port()}"
    outcome = await TEIReranker(url, timeout_s=2).rerank(QUERY, items(), top_n=2)
    assert not outcome.reranked
    assert "ConnectError" in outcome.error
    assert [e.text for e in outcome.items] == TEXTS[:2]
    assert all(e.rerank_score is None for e in outcome.items)


async def test_server_without_rerank_endpoint_keeps_rrf_order(embedder_url):
    # A real TEI server running an embedding model answers /rerank with an HTTP error.
    outcome = await TEIReranker(embedder_url).rerank(QUERY, items(), top_n=8)
    assert not outcome.reranked and "HTTPStatusError" in outcome.error
    assert [e.text for e in outcome.items] == TEXTS


async def test_disabled_reranker_and_empty_input():
    outcome = await TEIReranker(None).rerank(QUERY, items(), top_n=1)
    assert not outcome.reranked and outcome.error == "reranker not configured"
    assert len(outcome.items) == 1
    empty = await TEIReranker(f"http://127.0.0.1:{closed_port()}").rerank(QUERY, [], top_n=8)
    assert empty.items == [] and empty.reranked is False and empty.error is None
