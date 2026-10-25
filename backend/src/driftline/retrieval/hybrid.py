"""Hybrid retrieval (spec section 5): pgvector cosine + Postgres full-text, fused with
reciprocal-rank fusion, restricted to what was in force at `as_of`.

The temporal filter is part of both searches, not a post-filter: only chunks of versions
with valid_from <= as_of < coalesce(valid_to, infinity), of the tenant's sources, whose
document has not been replaced (an applied `supersedes`/`deprecates` relation from a
version of the same tenant already in effect at as_of) are ever ranked. The one
exception is an explicit `RetrievalQuery(in_force_only=False)`, which the plain-RAG eval
baseline uses to search every version.
"""

from collections.abc import Sequence
from uuid import UUID

import asyncpg

from driftline.ingest.embed import to_pgvector
from driftline.llm.router import LLMRouter
from driftline.retrieval.types import Evidence, RetrievalQuery
from driftline.skills.pack import RetrievalParams, active_pack

IN_FORCE = """
WITH in_force AS (
  SELECT v.id AS version_id
  FROM doc_versions v
  JOIN documents d ON d.id = v.document_id
  JOIN sources s ON s.id = d.source_id
  WHERE s.tenant_id = $1
    AND v.valid_from <= $2 AND ($2 < v.valid_to OR v.valid_to IS NULL)
    AND ($3::text[] IS NULL OR s.kind = ANY($3::text[]))
    AND ($4::uuid[] IS NULL OR v.document_id = ANY($4::uuid[]))
    AND NOT EXISTS (
      SELECT 1 FROM relations r
      JOIN doc_versions sv ON sv.id = r.src_version_id
      JOIN documents sd ON sd.id = sv.document_id
      JOIN sources ss ON ss.id = sd.source_id
      WHERE r.dst_document_id = v.document_id
        AND ss.tenant_id = $1
        AND r.status = 'applied' AND r.kind IN ('supersedes', 'deprecates')
        AND sv.document_id <> v.document_id AND sv.valid_from <= $2
    )
)
"""

# Same parameters as IN_FORCE, without the temporal filter: every version of the
# tenant's documents (the plain-RAG eval baseline). $2 is referenced only so both
# variants take the same parameters.
ANY_VERSION = """
WITH in_force AS (
  SELECT v.id AS version_id
  FROM doc_versions v
  JOIN documents d ON d.id = v.document_id
  JOIN sources s ON s.id = d.source_id
  WHERE s.tenant_id = $1
    AND $2::timestamptz IS NOT NULL
    AND ($3::text[] IS NULL OR s.kind = ANY($3::text[]))
    AND ($4::uuid[] IS NULL OR v.document_id = ANY($4::uuid[]))
)
"""

_VECTOR_TAIL = """
SELECT c.id FROM chunks c JOIN in_force f ON f.version_id = c.version_id
WHERE c.embedding IS NOT NULL AND c.embed_model = $5 AND NOT (c.tags && $6::text[])
ORDER BY c.embedding <=> $7::vector, c.id
LIMIT $8
"""

# OR semantics: a question rarely contains every word of the passage that answers it.
_TEXT_TAIL = """
, q AS (
  SELECT regexp_replace(plainto_tsquery('english', $5)::text, '&|<->', '|', 'g')::tsquery AS q
)
SELECT c.id FROM chunks c JOIN in_force f ON f.version_id = c.version_id, q
WHERE c.tsv @@ q.q AND NOT (c.tags && $6::text[])
ORDER BY ts_rank_cd(c.tsv, q.q) DESC, c.id
LIMIT $7
"""

VECTOR_SQL = IN_FORCE + _VECTOR_TAIL
TEXT_SQL = IN_FORCE + _TEXT_TAIL
VECTOR_SQL_ANY_VERSION = ANY_VERSION + _VECTOR_TAIL
TEXT_SQL_ANY_VERSION = ANY_VERSION + _TEXT_TAIL

DETAILS_SQL = """
SELECT c.id AS chunk_id, c.version_id, v.document_id, d.external_id,
       coalesce(d.title, d.external_id) AS title, c.section_path, c.text, c.tags,
       v.version_no, v.valid_from, v.valid_to
FROM chunks c
JOIN doc_versions v ON v.id = c.version_id
JOIN documents d ON d.id = v.document_id
JOIN sources s ON s.id = d.source_id
WHERE c.id = ANY($1::uuid[]) AND s.tenant_id = $2
"""


def rrf_fuse(rankings: Sequence[Sequence[UUID]], *, k: int = 60) -> list[tuple[UUID, float]]:
    """Reciprocal-rank fusion: score(d) = sum over rankings of 1 / (k + rank), rank from 1.

    Ties keep the order of first appearance, so the result is deterministic.
    """
    scores: dict[UUID, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    order = {item: i for i, item in enumerate(scores)}
    return sorted(scores.items(), key=lambda kv: (-kv[1], order[kv[0]]))


class HybridRetriever:
    def __init__(
        self,
        pool: asyncpg.Pool,
        router: LLMRouter,
        *,
        embed_model: str,
        dim: int = 768,
        candidates: int = 30,
        rrf_k: int = 60,
        tier: str = "embed",
    ) -> None:
        self._pool = pool
        self._router = router
        self._embed_model = embed_model
        self._dim = dim
        self._candidates = candidates
        self._rrf_k = rrf_k
        self._tier = tier

    async def embed_query(self, text: str) -> list[float]:
        [vector] = await self._router.embed(self._tier, [text], self._dim)
        return vector

    async def retrieve(
        self,
        query: RetrievalQuery,
        *,
        top_k: int = 30,
        vector: list[float] | None = None,
        params: RetrievalParams | None = None,
    ) -> list[Evidence]:
        """Up to `top_k` in-force chunks, best first (RRF over vector and text ranks).

        `params` (default: the job's active skill pack, else the constructor's values)
        sets the candidates per search and the RRF constant."""
        if params is None and (pack := active_pack()) is not None:
            params = pack.retrieval
        candidates = params.candidates if params else self._candidates
        rrf_k = params.rrf_k if params else self._rrf_k
        vector = vector if vector is not None else await self.embed_query(query.text)
        base = (
            query.tenant_id,
            query.as_of,
            list(query.source_kinds) if query.source_kinds is not None else None,
            list(query.document_ids) if query.document_ids is not None else None,
        )
        tags = list(query.exclude_tags)
        vector_sql, text_sql = (
            (VECTOR_SQL, TEXT_SQL)
            if query.in_force_only
            else (VECTOR_SQL_ANY_VERSION, TEXT_SQL_ANY_VERSION)
        )
        # One snapshot for all three queries, so a chunk ranked by the searches cannot
        # vanish (or change version) before its details are read.
        async with (
            self._pool.acquire() as conn,
            conn.transaction(isolation="repeatable_read", readonly=True),
        ):
            by_vector = await conn.fetch(
                vector_sql,
                *base,
                self._embed_model,
                tags,
                to_pgvector(vector),
                candidates,
            )
            by_text = await conn.fetch(text_sql, *base, query.text, tags, candidates)
            fused = rrf_fuse([[r["id"] for r in by_vector], [r["id"] for r in by_text]], k=rrf_k)[
                :top_k
            ]
            if not fused:
                return []
            rows = await conn.fetch(
                DETAILS_SQL, [chunk_id for chunk_id, _ in fused], query.tenant_id
            )
        details = {r["chunk_id"]: r for r in rows}
        return [
            Evidence(
                **{k: v for k, v in details[chunk_id].items() if k != "tags"},
                tags=list(details[chunk_id]["tags"]),
                retrieved_as_of=query.as_of,
                score=score,
            )
            for chunk_id, score in fused
        ]
