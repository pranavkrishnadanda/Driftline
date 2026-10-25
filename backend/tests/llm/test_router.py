import pytest

from driftline.clock import ManualClock
from driftline.config import Settings
from driftline.llm.adapters.deterministic import DeterministicAdapter
from driftline.llm.breaker import CircuitBreaker
from driftline.llm.ratelimit import RedisTokenBucket
from driftline.llm.router import AllRoutesFailed, LLMRouter, Route, build_router
from driftline.llm.types import CompletionRequest, Message, ProviderError, Role


def req(text="hello"):
    return CompletionRequest(messages=[Message(role=Role.user, content=text)])


def retryable():
    return ProviderError("rate limited", retryable=True, status=429)


def fatal():
    return ProviderError("bad request", retryable=False, status=400)


def router(primary, secondary, clock, **kw):
    return LLMRouter(
        providers={"p": primary, "s": secondary},
        chains={"answer": [Route("p", "pro"), Route("s", "flash")]},
        clock=clock,
        **kw,
    )


async def test_primary_success_is_not_degraded():
    clock = ManualClock()
    p, s = DeterministicAdapter("p"), DeterministicAdapter("s")
    result = await router(p, s, clock).complete("answer", req())
    assert result.provider == "p"
    assert result.degraded is False
    assert s.calls == []


async def test_retryable_errors_are_retried_with_backoff_on_same_route():
    clock = ManualClock()
    p = DeterministicAdapter("p", script=[retryable(), retryable(), None])
    s = DeterministicAdapter("s")
    result = await router(p, s, clock).complete("answer", req())
    assert result.provider == "p"
    assert p.calls == ["pro", "pro", "pro"]
    assert s.calls == []
    assert clock.now() > 0


async def test_non_retryable_error_falls_back_immediately_and_marks_degraded():
    clock = ManualClock()
    p = DeterministicAdapter("p", script=[fatal()])
    s = DeterministicAdapter("s")
    result = await router(p, s, clock).complete("answer", req())
    assert result.provider == "s"
    assert result.model == "flash"
    assert result.degraded is True
    assert p.calls == ["pro"]


async def test_all_routes_failing_raises_with_every_error():
    clock = ManualClock()
    p = DeterministicAdapter("p", script=[fatal()])
    s = DeterministicAdapter("s", script=[fatal()])
    with pytest.raises(AllRoutesFailed) as exc_info:
        await router(p, s, clock).complete("answer", req())
    assert [r.provider for r, _ in exc_info.value.errors] == ["p", "s"]


async def test_open_breaker_skips_provider_without_calling_it():
    clock = ManualClock()
    p = DeterministicAdapter("p", script=[fatal(), fatal()])
    s = DeterministicAdapter("s")
    r = router(
        p, s, clock, breaker_factory=lambda: CircuitBreaker(clock=clock, failure_threshold=2)
    )
    await r.complete("answer", req())
    await r.complete("answer", req())
    third = await r.complete("answer", req())
    assert third.provider == "s"
    assert p.calls == ["pro", "pro"]


async def test_quota_bucket_makes_caller_wait(redis_client):
    clock = ManualClock(1000.0)
    bucket = RedisTokenBucket(redis_client, "rl:pro", capacity=1, refill_per_sec=1.0, clock=clock)
    p, s = DeterministicAdapter("p"), DeterministicAdapter("s")
    r = router(p, s, clock, buckets={"pro": bucket})
    await r.complete("answer", req())
    await r.complete("answer", req())
    assert clock.now() == pytest.approx(1001.0)
    assert p.calls == ["pro", "pro"]


async def test_quota_timeout_falls_back_to_next_route(redis_client):
    clock = ManualClock(1000.0)
    bucket = RedisTokenBucket(redis_client, "rl:pro", capacity=1, refill_per_sec=0.01, clock=clock)
    p, s = DeterministicAdapter("p"), DeterministicAdapter("s")
    r = router(p, s, clock, buckets={"pro": bucket}, bucket_timeout_s=5)
    await r.complete("answer", req())
    second = await r.complete("answer", req())
    assert second.provider == "s"
    assert second.degraded is True


async def test_non_provider_errors_propagate_without_fallback():
    clock = ManualClock()
    p = DeterministicAdapter("p", script=[ValueError("bug in adapter")])
    s = DeterministicAdapter("s")
    with pytest.raises(ValueError):
        await router(p, s, clock).complete("answer", req())
    assert s.calls == []


async def test_embed_uses_tier_chain_with_fallback():
    clock = ManualClock()
    p = DeterministicAdapter("p", script=[fatal()])
    s = DeterministicAdapter("s")
    r = LLMRouter(
        providers={"p": p, "s": s},
        chains={"embed": [Route("p", "e1"), Route("s", "e2")]},
        clock=clock,
    )
    vectors = await r.embed("embed", ["a", "b"], 768)
    assert len(vectors) == 2 and len(vectors[0]) == 768
    assert s.calls == ["e2"]


async def test_build_router_tiers_follow_settings(redis_client):
    settings = Settings(
        _env_file=None,
        gemini_api_key="unused-in-this-test",
        model_extract="fx",
        model_answer="px",
        model_fallback=["f1", "f2"],
        model_embed="ex",
    )
    r = build_router(settings, redis_client, clock=ManualClock())
    assert [x.model for x in r.chains["answer"]] == ["px", "f1", "f2"]
    assert [x.model for x in r.chains["extract"]] == ["fx", "f1", "f2"]
    assert [x.model for x in r.chains["embed"]] == ["ex"]
    assert {x.provider for c in r.chains.values() for x in c} == {"gemini"}


def test_build_router_requires_gemini_key(redis_client):
    with pytest.raises(ValueError):
        build_router(
            Settings(_env_file=None, gemini_api_key=None), redis_client, clock=ManualClock()
        )


async def test_rate_limit_timeout_during_half_open_probe_does_not_wedge_breaker(redis_client):
    clock = ManualClock(1000.0)
    bucket = RedisTokenBucket(redis_client, "rl:pro", capacity=1, refill_per_sec=0.1, clock=clock)
    p = DeterministicAdapter("p", script=[fatal()])
    s = DeterministicAdapter("s")
    r = router(
        p,
        s,
        clock,
        buckets={"pro": bucket},
        bucket_timeout_s=1,
        breaker_factory=lambda: CircuitBreaker(
            clock=clock, failure_threshold=1, cooldown_seconds=5
        ),
    )

    first = await r.complete("answer", req())  # spends the only token, fails, opens the breaker
    assert first.provider == "s"

    clock.advance(5)  # breaker is half-open; bucket holds only 0.5 tokens
    second = await r.complete("answer", req())  # probe is granted, then hits RateLimitTimeout
    assert second.provider == "s"
    assert p.calls == ["pro"]

    clock.advance(20)  # bucket refilled
    third = await r.complete("answer", req())
    assert p.calls == ["pro", "pro"]
    assert third.provider == "p"
    assert third.degraded is False
