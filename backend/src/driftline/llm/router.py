import json
import random
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis

from driftline.clock import Clock
from driftline.config import Settings
from driftline.llm.adapters.anthropic import AnthropicAdapter
from driftline.llm.adapters.gemini import GeminiAdapter
from driftline.llm.adapters.latency import LatencyStubAdapter, worker_seed
from driftline.llm.adapters.tei import TEIEmbeddingAdapter
from driftline.llm.breaker import CircuitBreaker
from driftline.llm.ratelimit import RateLimitTimeout, RedisTokenBucket
from driftline.llm.types import (
    CompletionRequest,
    CompletionResult,
    DeltaHandler,
    LLMProvider,
    Message,
    ProviderError,
    Role,
)

T = TypeVar("T")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


@dataclass(frozen=True)
class Route:
    provider: str
    model: str


class CircuitOpenError(Exception):
    pass


class StreamInterrupted(Exception):
    """A stream failed after deltas were already delivered, so it cannot be retried or
    fall back silently: the caller has shown those deltas to someone."""

    def __init__(self, cause: ProviderError, delivered: int) -> None:
        super().__init__(f"stream interrupted after {delivered} deltas: {cause}")
        self.cause = cause
        self.delivered = delivered


class StructuredOutputError(Exception):
    """The reply did not parse as the requested schema, even after repair attempts."""

    def __init__(self, schema_name: str, detail: str, raw: str) -> None:
        super().__init__(f"{schema_name}: {detail}")
        self.schema_name = schema_name
        self.detail = detail
        self.raw = raw


def parse_json_reply[M: BaseModel](text: str, output: type[M]) -> M:
    """Validate a reply as `output`: tolerate a ```json fence or prose around one object."""
    body = _FENCE.sub("", text.strip())
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object in reply")
    return output.model_validate(json.loads(body[start : end + 1]))


class AllRoutesFailed(Exception):
    def __init__(self, errors: list[tuple[Route, Exception]]) -> None:
        summary = "; ".join(f"{r.provider}/{r.model}: {e}" for r, e in errors)
        super().__init__(f"all routes failed: {summary}")
        self.errors = errors


class LLMRouter:
    def __init__(
        self,
        providers: dict[str, LLMProvider],
        chains: dict[str, list[Route]],
        *,
        clock: Clock,
        buckets: dict[str, RedisTokenBucket] | None = None,
        breaker_factory: Callable[[], CircuitBreaker] | None = None,
        max_attempts: int = 3,
        base_backoff_s: float = 0.5,
        bucket_timeout_s: float = 30.0,
    ) -> None:
        self.providers = providers
        self.chains = chains
        self._clock = clock
        self._buckets = buckets or {}
        self._breaker_factory = breaker_factory or (lambda: CircuitBreaker(clock=clock))
        self._breakers: dict[Route, CircuitBreaker] = {}
        self._max_attempts = max_attempts
        self._base_backoff_s = base_backoff_s
        self._bucket_timeout_s = bucket_timeout_s

    def breaker(self, route: Route) -> CircuitBreaker:
        if route not in self._breakers:
            self._breakers[route] = self._breaker_factory()
        return self._breakers[route]

    async def complete(self, tier: str, request: CompletionRequest) -> CompletionResult:
        result, index = await self._run(tier, lambda p, m: p.complete(m, request))
        return result.model_copy(update={"degraded": index > 0})

    async def embed(self, tier: str, texts: list[str], dim: int) -> list[list[float]]:
        vectors, _ = await self._run(tier, lambda p, m: p.embed(m, texts, dim))
        return vectors

    async def stream(
        self, tier: str, request: CompletionRequest, on_delta: DeltaHandler
    ) -> CompletionResult:
        """Like `complete`, delivering text deltas as they arrive.

        Retries and fallback apply only until the first delta is delivered; a failure
        after that raises `StreamInterrupted`. Providers without `stream` deliver their
        whole reply as one delta.
        """
        delivered = 0

        async def forward(text: str) -> None:
            nonlocal delivered
            delivered += 1
            await on_delta(text)

        async def call(provider: LLMProvider, model: str) -> CompletionResult:
            streamer = getattr(provider, "stream", None)
            if streamer is None:
                result = await provider.complete(model, request)
                await forward(result.text)
                return result
            try:
                return await streamer(model, request, forward)
            except ProviderError as exc:
                if delivered:
                    raise StreamInterrupted(exc, delivered) from exc
                raise

        result, index = await self._run(tier, call)
        return result.model_copy(update={"degraded": index > 0})

    async def structured[M: BaseModel](
        self,
        tier: str,
        request: CompletionRequest,
        output: type[M],
        *,
        on_delta: DeltaHandler | None = None,
        max_repairs: int = 1,
    ) -> tuple[M, CompletionResult]:
        """Complete with `output`'s JSON Schema and return the validated model.

        Providers that support it constrain decoding to the schema; every reply is
        validated here regardless. An invalid reply is shown back to the model with the
        validation error, at most `max_repairs` times, then `StructuredOutputError`.
        """
        name = request.schema_name or output.__name__
        current = request.model_copy(
            update={"response_schema": output.model_json_schema(), "schema_name": name}
        )
        for attempt in range(max_repairs + 1):
            if on_delta is None:
                result = await self.complete(tier, current)
            else:
                result = await self.stream(tier, current, on_delta)
            try:
                return parse_json_reply(result.text, output), result
            except (ValueError, ValidationError) as exc:
                detail = str(exc)
                if attempt == max_repairs:
                    raise StructuredOutputError(name, detail, result.text) from exc
                current = current.model_copy(
                    update={
                        "messages": [
                            *current.messages,
                            Message(role=Role.assistant, content=result.text),
                            Message(
                                role=Role.user,
                                content="That reply did not match the required JSON schema "
                                f"({detail[:500]}). Reply again with only the JSON object.",
                            ),
                        ]
                    }
                )
        raise AssertionError("unreachable")

    async def _run(
        self, tier: str, call: Callable[[LLMProvider, str], Awaitable[T]]
    ) -> tuple[T, int]:
        errors: list[tuple[Route, Exception]] = []
        for index, route in enumerate(self.chains[tier]):
            breaker = self.breaker(route)
            if not breaker.allow():
                errors.append((route, CircuitOpenError(f"{route.provider}/{route.model} open")))
                continue
            provider = self.providers[route.provider]
            for attempt in range(self._max_attempts):
                bucket = self._buckets.get(route.model)
                try:
                    if bucket is not None:
                        try:
                            await bucket.acquire(1.0, timeout=self._bucket_timeout_s)
                        except RateLimitTimeout as exc:
                            # The provider was never called: hand back any half-open probe
                            # so the breaker is not left waiting for an outcome forever.
                            breaker.release_probe()
                            errors.append((route, exc))
                            break
                    result = await call(provider, route.model)
                except ProviderError as exc:
                    breaker.record_failure()
                    errors.append((route, exc))
                    last = attempt == self._max_attempts - 1
                    if not exc.retryable or last or not breaker.allow():
                        break
                    await self._clock.sleep(self._backoff(attempt))
                    continue
                except StreamInterrupted:
                    # The provider failed mid-reply: a provider failure, but one that can
                    # be neither retried nor fallen back from, so record it and propagate.
                    breaker.record_failure()
                    raise
                except BaseException:
                    # Bugs, cancellation or infrastructure errors say nothing about the
                    # provider's health: release any probe, then propagate unchanged.
                    breaker.release_probe()
                    raise
                breaker.record_success()
                return result, index
        raise AllRoutesFailed(errors)

    def _backoff(self, attempt: int) -> float:
        return self._base_backoff_s * (2**attempt) * random.uniform(0.5, 1.5)


def build_bench_router(
    settings: Settings, *, clock: Clock, consumer: str | None = None
) -> LLMRouter:
    """The `bench` chain: LatencyStubAdapter (replies from the in-repo ExtractiveResponder,
    so structured outputs stay valid) on every LLM tier; embeddings stay on TEI. The stub
    is seeded per worker (`worker_seed(llm_bench_seed, consumer)`)."""
    # Imported here: driftline.agents builds on the router, not the other way round.
    from driftline.agents.offline import ExtractiveResponder

    stub = LatencyStubAdapter(
        seed=worker_seed(settings.llm_bench_seed, consumer),
        median_ms=settings.llm_bench_median_ms,
        sigma=settings.llm_bench_sigma,
        clock=clock,
        responder=ExtractiveResponder(),
    )
    tiers = {t: [Route(stub.name, f"bench-{t}")] for t in ("extract", "answer", "judge")}
    return LLMRouter(
        providers={stub.name: stub, "tei": TEIEmbeddingAdapter(settings.embed_url)},
        chains={**tiers, "embed": [Route("tei", settings.model_embed)]},
        clock=clock,
    )


def build_router(settings: Settings, redis: Redis, *, clock: Clock) -> LLMRouter:
    if settings.llm_bench:
        return build_bench_router(settings, clock=clock)
    if not settings.anthropic_api_key and not settings.gemini_api_key:
        raise ValueError(
            "no LLM provider configured: set DRIFTLINE_ANTHROPIC_API_KEY or DRIFTLINE_GEMINI_API_KEY"
        )
    providers: dict[str, LLMProvider] = {"tei": TEIEmbeddingAdapter(settings.embed_url)}
    extract: list[Route] = []
    answer: list[Route] = []
    judge: list[Route] = []
    if settings.anthropic_api_key:
        providers["anthropic"] = AnthropicAdapter(
            settings.anthropic_api_key, clock=clock, timeout_s=settings.llm_timeout_s
        )
        claude_fallbacks = [Route("anthropic", m) for m in settings.model_fallback]
        extract += [Route("anthropic", settings.model_extract), *claude_fallbacks]
        answer += [
            Route("anthropic", settings.model_answer),
            Route("anthropic", settings.model_extract),
            *claude_fallbacks,
        ]
        judge += [
            Route("anthropic", settings.model_judge),
            Route("anthropic", settings.model_extract),
            *claude_fallbacks,
        ]
    if settings.gemini_api_key:
        providers["gemini"] = GeminiAdapter(settings.gemini_api_key, clock=clock)
        gemini_fallbacks = [Route("gemini", m) for m in settings.gemini_fallback_models]
        extract += gemini_fallbacks
        answer += gemini_fallbacks
        judge += gemini_fallbacks
    chains = {
        "extract": extract,
        "answer": answer,
        "judge": judge,
        "embed": [Route("tei", settings.model_embed)],
    }
    return LLMRouter(providers=providers, chains=chains, clock=clock)
