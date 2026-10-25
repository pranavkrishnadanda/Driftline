import httpx
from google import genai
from google.genai import errors
from google.genai import types as gtypes

from driftline.clock import Clock, SystemClock
from driftline.llm.types import CompletionRequest, CompletionResult, ProviderError, Role, Usage

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


def _result_text(response: gtypes.GenerateContentResponse) -> str:
    text = response.text
    if not text:
        reason = response.candidates[0].finish_reason if response.candidates else None
        reason_name = getattr(reason, "name", reason)
        raise ProviderError(
            f"empty response from gemini (finish_reason={reason_name})", retryable=False
        )
    return text


class GeminiAdapter:
    name = "gemini"

    def __init__(self, api_key: str, *, clock: Clock | None = None) -> None:
        # google-genai switches to aiohttp whenever it is importable (llama-index pulls it
        # in). Passing an httpx transport keeps the async path on httpx, as recorded.
        self._client = genai.Client(
            api_key=api_key,
            http_options=gtypes.HttpOptions(
                async_client_args={"transport": httpx.AsyncHTTPTransport()}
            ),
        )
        self._clock = clock or SystemClock()

    async def complete(self, model: str, request: CompletionRequest) -> CompletionResult:
        system = "\n".join(m.content for m in request.messages if m.role is Role.system) or None
        contents = [
            gtypes.Content(
                role="user" if m.role is Role.user else "model",
                parts=[gtypes.Part(text=m.content)],
            )
            for m in request.messages
            if m.role is not Role.system
        ]
        config = gtypes.GenerateContentConfig(
            system_instruction=system,
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens,
        )
        start = self._clock.now()
        try:
            response = await self._client.aio.models.generate_content(
                model=model, contents=contents, config=config
            )
        except errors.APIError as exc:
            raise ProviderError(
                str(exc), retryable=exc.code in RETRYABLE_STATUS, status=exc.code
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderError(f"transport error: {exc}", retryable=True) from exc
        usage = response.usage_metadata
        return CompletionResult(
            text=_result_text(response),
            model=model,
            provider=self.name,
            usage=Usage(
                input_tokens=(usage.prompt_token_count or 0) if usage else 0,
                output_tokens=(usage.candidates_token_count or 0) if usage else 0,
            ),
            latency_ms=(self._clock.now() - start) * 1000,
        )

    async def embed(self, model: str, texts: list[str], dim: int) -> list[list[float]]:
        try:
            response = await self._client.aio.models.embed_content(
                model=model,
                contents=texts,
                config=gtypes.EmbedContentConfig(output_dimensionality=dim),
            )
        except errors.APIError as exc:
            raise ProviderError(
                str(exc), retryable=exc.code in RETRYABLE_STATUS, status=exc.code
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderError(f"transport error: {exc}", retryable=True) from exc
        return [list(e.values) for e in response.embeddings]
