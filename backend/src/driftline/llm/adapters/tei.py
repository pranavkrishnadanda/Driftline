import httpx

from driftline.llm.types import CompletionRequest, CompletionResult, ProviderError

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class TEIEmbeddingAdapter:
    """Embeddings from a Hugging Face text-embeddings-inference (TEI) server.

    The model is fixed by the server (`--model-id`), so the `model` argument is informational.
    """

    name = "tei"

    def __init__(self, base_url: str, *, timeout_s: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    async def complete(self, model: str, request: CompletionRequest) -> CompletionResult:
        raise ProviderError("tei provides embeddings only", retryable=False)

    async def embed(self, model: str, texts: list[str], dim: int) -> list[list[float]]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.post(
                    f"{self._base_url}/embed", json={"inputs": texts, "normalize": True}
                )
        except httpx.TransportError as exc:
            raise ProviderError(f"transport error: {exc}", retryable=True) from exc
        status = response.status_code
        if status >= 400:
            raise ProviderError(
                f"tei returned HTTP {status}: {response.text[:200]}",
                retryable=status in RETRYABLE_STATUS or status >= 500,
                status=status,
            )
        vectors: list[list[float]] = response.json()
        if len(vectors) != len(texts):
            raise ProviderError(
                f"tei returned {len(vectors)} vectors for {len(texts)} inputs", retryable=False
            )
        for vector in vectors:
            if len(vector) != dim:
                raise ProviderError(
                    f"tei returned {len(vector)}-dim vectors, expected {dim}", retryable=False
                )
        return vectors
