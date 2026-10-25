import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from redis.asyncio import Redis

from driftline.clock import Clock
from driftline.config import Settings
from driftline.llm.adapters.gemini import GeminiAdapter
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
                if bucket is not None:
                    try:
                        await bucket.acquire(1.0, timeout=self._bucket_timeout_s)
                    except RateLimitTimeout as exc:
                        # The provider was never called: hand back any half-open probe
                        # so the breaker is not left waiting for an outcome forever.
                        breaker.release_probe()
                        errors.append((route, exc))
                        break
                try:
                    result = await call(provider, route.model)
                except ProviderError as exc:
                    breaker.record_failure()
                    errors.append((route, exc))
                    last = attempt == self._max_attempts - 1
                    if not exc.retryable or last or not breaker.allow():
                        break
                    await self._clock.sleep(self._backoff(attempt))
                    continue
                breaker.record_success()
                return result, index
        raise AllRoutesFailed(errors)

    def _backoff(self, attempt: int) -> float:
        return self._base_backoff_s * (2**attempt) * random.uniform(0.5, 1.5)


def build_router(settings: Settings, redis: Redis, *, clock: Clock) -> LLMRouter:
    if not settings.gemini_api_key:
        raise ValueError("DRIFTLINE_GEMINI_API_KEY is required to build the LLM router")
    fallbacks = [Route("gemini", m) for m in settings.model_fallback]
    chains = {
        "extract": [Route("gemini", settings.model_extract), *fallbacks],
        "answer": [Route("gemini", settings.model_answer), *fallbacks],
        "embed": [Route("gemini", settings.model_embed)],
    }
    return LLMRouter(
        providers={"gemini": GeminiAdapter(settings.gemini_api_key, clock=clock)},
        chains=chains,
        clock=clock,
    )
