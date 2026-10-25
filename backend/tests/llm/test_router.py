import pytest

from driftline.clock import ManualClock
from driftline.config import Settings
from driftline.llm.adapters.anthropic import AnthropicAdapter
from driftline.llm.adapters.deterministic import DeterministicAdapter
from driftline.llm.adapters.gemini import GeminiAdapter
from driftline.llm.adapters.tei import TEIEmbeddingAdapter
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


def _settings(**overrides):
    # Fake key strings are fine: constructing the adapters makes no network calls.
    base = {
        "_env_file": None,
        "anthropic_api_key": None,
        "gemini_api_key": None,
        "model_extract": "claude-haiku-5-5",
        "model_answer": "claude-sonnet-5-5",
        "model_fallback": [],
        "gemini_fallback_models": ["gemini-3.8-flash"],
        "model_embed": "BAAI/bge-base-en-v1.5",
        "embed_url": "http://localhost:8080",
    }
    return Settings(**{**base, **overrides})


def _chain(r, tier):
    return [(x.provider, x.model) for x in r.chains[tier]]


def test_build_router_claude_primary_with_gemini_fallback(redis_client):
    settings = _settings(anthropic_api_key="fake-anthropic", gemini_api_key="fake-gemini")
    r = build_router(settings, redis_client, clock=ManualClock())
    assert _chain(r, "extract") == [
        ("anthropic", "claude-haiku-5-5"),
        ("gemini", "gemini-3.8-flash"),
    ]
    assert _chain(r, "answer") == [
        ("anthropic", "claude-sonnet-5-5"),
        ("anthropic", "claude-haiku-5-5"),
        ("gemini", "gemini-3.8-flash"),
    ]
    assert isinstance(r.providers["anthropic"], AnthropicAdapter)
    assert isinstance(r.providers["gemini"], GeminiAdapter)


def test_build_router_without_gemini_has_no_gemini_routes(redis_client):
    r = build_router(
        _settings(anthropic_api_key="fake-anthropic"), redis_client, clock=ManualClock()
    )
    assert "gemini" not in r.providers
    assert all(x.provider != "gemini" for chain in r.chains.values() for x in chain)
    assert _chain(r, "extract") == [("anthropic", "claude-haiku-5-5")]
    assert _chain(r, "answer") == [
        ("anthropic", "claude-sonnet-5-5"),
        ("anthropic", "claude-haiku-5-5"),
    ]


def test_model_fallback_adds_anthropic_routes_before_gemini(redis_client):
    settings = _settings(
        anthropic_api_key="fake-anthropic",
        gemini_api_key="fake-gemini",
        model_fallback=["claude-extra"],
    )
    r = build_router(settings, redis_client, clock=ManualClock())
    assert _chain(r, "extract") == [
        ("anthropic", "claude-haiku-5-5"),
        ("anthropic", "claude-extra"),
        ("gemini", "gemini-3.8-flash"),
    ]


def test_build_router_requires_some_llm_key(redis_client):
    with pytest.raises(ValueError, match="no LLM provider configured"):
        build_router(_settings(), redis_client, clock=ManualClock())


def test_embed_tier_uses_tei(redis_client):
    settings = _settings(anthropic_api_key="fake-anthropic", embed_url="http://embedder:80")
    r = build_router(settings, redis_client, clock=ManualClock())
    assert _chain(r, "embed") == [("tei", "BAAI/bge-base-en-v1.5")]
    tei = r.providers["tei"]
    assert isinstance(tei, TEIEmbeddingAdapter)
    assert tei._base_url == "http://embedder:80"


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


async def test_unexpected_error_during_half_open_probe_releases_probe():
    clock = ManualClock()
    p = DeterministicAdapter("p", script=[ValueError("bug in adapter"), None])
    s = DeterministicAdapter("s")
    r = router(
        p,
        s,
        clock,
        breaker_factory=lambda: CircuitBreaker(
            clock=clock, failure_threshold=1, cooldown_seconds=5
        ),
    )
    r.breaker(Route("p", "pro")).record_failure()  # open the primary breaker
    clock.advance(5)  # half-open

    with pytest.raises(ValueError):
        await r.complete("answer", req())  # the probe raises a bug-type error
    assert p.calls == ["pro"]
    assert s.calls == []  # Review Focus #2: no fallback

    result = await r.complete("answer", req())
    assert p.calls == ["pro", "pro"]
    assert result.provider == "p"
    assert s.calls == []
