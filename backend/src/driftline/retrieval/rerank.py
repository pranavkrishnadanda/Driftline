"""Cross-encoder rerank (spec section 5: rerank down to the top 8) through TEI's /rerank.

The reranker is an optimisation, not a dependency: when it is not configured, cannot be
reached, or answers with an error or a malformed body, the RRF order is kept for the whole
call (never a half-applied set of scores), a warning is logged and the outcome says why.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import httpx

from driftline.retrieval.types import Evidence
from driftline.skills.pack import active_pack

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RerankOutcome:
    items: list[Evidence]
    reranked: bool
    error: str | None = None


class TEIReranker:
    def __init__(
        self, base_url: str | None, *, timeout_s: float = 10.0, batch_size: int = 32
    ) -> None:
        self._base_url = base_url.rstrip("/") if base_url else None
        self._timeout_s = timeout_s
        self._batch_size = batch_size  # TEI's default --max-client-batch-size

    async def _scores(self, client: httpx.AsyncClient, query: str, texts: list[str]):
        scores: list[float | None] = [None] * len(texts)
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            response = await client.post(
                f"{self._base_url}/rerank",
                json={"query": query, "texts": batch, "truncate": True},
            )
            response.raise_for_status()
            results = response.json()
            if not isinstance(results, list) or len(results) != len(batch):
                raise ValueError(f"expected {len(batch)} rerank results, got {results!r:.200}")
            for item in results:
                index = int(item["index"])
                if not 0 <= index < len(batch) or scores[start + index] is not None:
                    raise ValueError(f"bad or duplicate rerank index {index}")
                scores[start + index] = float(item["score"])
        return scores

    async def rerank(
        self, query: str, items: Sequence[Evidence], *, top_n: int = 8
    ) -> RerankOutcome:
        """The `top_n` items by cross-encoder score (ties keep the incoming order). The job's
        active skill pack caps `top_n` at its `rerank_top_n`."""
        if (pack := active_pack()) is not None:
            top_n = min(top_n, pack.retrieval.rerank_top_n)
        items = list(items)
        if not items:
            return RerankOutcome([], reranked=False)
        if self._base_url is None:
            return RerankOutcome(items[:top_n], reranked=False, error="reranker not configured")
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                scores = await self._scores(client, query, [e.text for e in items])
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            logger.warning("rerank failed, keeping RRF order: %s", error)
            return RerankOutcome(items[:top_n], reranked=False, error=error)
        order = sorted(range(len(items)), key=lambda i: (-scores[i], i))
        ranked = [items[i].model_copy(update={"rerank_score": scores[i]}) for i in order]
        return RerankOutcome(ranked[:top_n], reranked=True)
