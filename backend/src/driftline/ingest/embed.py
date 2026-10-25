"""Embed stage: fill `chunks.embedding` for one version through the router's embed tier."""

from uuid import UUID

import asyncpg

from driftline.llm.router import LLMRouter


def to_pgvector(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


class EmbedStage:
    def __init__(
        self,
        router: LLMRouter,
        *,
        model_name: str,
        dim: int = 768,
        batch_size: int = 32,
        tier: str = "embed",
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self._router = router
        self._model_name = model_name
        self._dim = dim
        self._batch_size = batch_size
        self._tier = tier

    async def embed_version(self, conn: asyncpg.Connection, version_id: UUID) -> int:
        """Embed every chunk of the version that has no embedding yet; returns how many.

        Idempotent: a redelivered event only embeds what an earlier attempt left NULL,
        and each batch commits on its own, so a crash loses at most one batch of work.
        """
        rows = await conn.fetch(
            "SELECT id, text FROM chunks WHERE version_id = $1 AND embedding IS NULL ORDER BY ord",
            version_id,
        )
        done = 0
        for start in range(0, len(rows), self._batch_size):
            batch = rows[start : start + self._batch_size]
            vectors = await self._router.embed(self._tier, [r["text"] for r in batch], self._dim)
            if len(vectors) != len(batch):
                raise RuntimeError(f"embed returned {len(vectors)} vectors for {len(batch)} texts")
            async with conn.transaction():
                await conn.executemany(
                    "UPDATE chunks SET embedding = $2::vector, embed_model = $3 WHERE id = $1",
                    [
                        (r["id"], to_pgvector(v), self._model_name)
                        for r, v in zip(batch, vectors, strict=True)
                    ],
                )
            done += len(batch)
        return done
