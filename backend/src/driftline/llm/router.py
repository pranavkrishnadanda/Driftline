import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from redis.asyncio import Redis

from driftline.clock import Clock
from driftline.config import Settings
from driftline.llm.adapters.anthropic import AnthropicAdapter
from driftline.llm.adapters.gemini import GeminiAdapter
from driftline.llm.adapters.tei import TEIEmbeddingAdapter
from driftline.llm.breaker import CircuitBreaker
from driftline.llm.ratelimit import RateLimitTimeout, RedisTokenBucket
from driftline.llm.types import CompletionRequest, CompletionResult, LLMProvider, ProviderError

T = TypeVar("T")


@dataclass(frozen=True)
class Route:
    provider: str
    model: str


class CircuitOpenError(Exception):
    pass


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


def build_router(settings: Settings, redis: Redis, *, clock: Clock) -> LLMRouter:
    if not settings.anthropic_api_key and not settings.gemini_api_key:
        raise ValueError(
            "no LLM provider configured: set DRIFTLINE_ANTHROPIC_API_KEY or DRIFTLINE_GEMINI_API_KEY"
        )
    providers: dict[str, LLMProvider] = {"tei": TEIEmbeddingAdapter(settings.embed_url)}
    extract: list[Route] = []
    answer: list[Route] = []
    if settings.anthropic_api_key:
        providers["anthropic"] = AnthropicAdapter(settings.anthropic_api_key, clock=clock)
        claude_fallbacks = [Route("anthropic", m) for m in settings.model_fallback]
        extract += [Route("anthropic", settings.model_extract), *claude_fallbacks]
        answer += [
            Route("anthropic", settings.model_answer),
            Route("anthropic", settings.model_extract),
            *claude_fallbacks,
        ]
    if settings.gemini_api_key:
        providers["gemini"] = GeminiAdapter(settings.gemini_api_key, clock=clock)
        gemini_fallbacks = [Route("gemini", m) for m in settings.gemini_fallback_models]
        extract += gemini_fallbacks
        answer += gemini_fallbacks
    chains = {
        "extract": extract,
        "answer": answer,
        "embed": [Route("tei", settings.model_embed)],
    }
    return LLMRouter(providers=providers, chains=chains, clock=clock)
