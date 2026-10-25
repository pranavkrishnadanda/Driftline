"""LatencyStubAdapter: the bench's real LLMProvider with seeded log-normal latency.

Every sleep goes through ManualClock, so these tests measure the requested delays
without real sleeping."""

import json
import statistics

import pytest

from driftline.agents.offline import ExtractiveResponder
from driftline.agents.prompts import JUDGE_SCHEMA
from driftline.clock import ManualClock
from driftline.config import Settings
from driftline.llm.adapters.latency import STUB_LABEL, LatencyStubAdapter
from driftline.llm.adapters.tei import TEIEmbeddingAdapter
from driftline.llm.router import LLMRouter, Route, build_router
from driftline.llm.types import CompletionRequest, Message, Role


def req(text: str = "hello world", schema_name: str | None = None) -> CompletionRequest:
    return CompletionRequest(
        messages=[Message(role=Role.user, content=text)], schema_name=schema_name
    )


async def delays(adapter: LatencyStubAdapter, clock: ManualClock, n: int) -> list[float]:
    """The delay (ms) each of `n` completions asked the clock for."""
    out = []
    for _ in range(n):
        before = clock.now()
        result = await adapter.complete("m", req())
        requested_ms = (clock.now() - before) * 1000
        assert result.latency_ms == pytest.approx(requested_ms)
        out.append(requested_ms)
    return out


async def test_same_seed_gives_the_same_latencies_and_text():
    c1, c2 = ManualClock(), ManualClock()
    a = LatencyStubAdapter(seed=7, median_ms=800, sigma=0.5, clock=c1)
    b = LatencyStubAdapter(seed=7, median_ms=800, sigma=0.5, clock=c2)
    assert await delays(a, c1, 50) == await delays(b, c2, 50)
    assert (await a.complete("m", req("q"))).text == (await b.complete("m", req("q"))).text


async def test_different_seeds_give_different_latencies():
    c1, c2 = ManualClock(), ManualClock()
    a = LatencyStubAdapter(seed=1, median_ms=800, sigma=0.5, clock=c1)
    b = LatencyStubAdapter(seed=2, median_ms=800, sigma=0.5, clock=c2)
    assert await delays(a, c1, 20) != await delays(b, c2, 20)


@pytest.mark.parametrize("median_ms,sigma", [(800, 0.5), (250, 0.8), (2000, 0.3)])
async def test_median_is_within_ten_percent_over_1000_draws(median_ms, sigma):
    clock = ManualClock()
    adapter = LatencyStubAdapter(seed=42, median_ms=median_ms, sigma=sigma, clock=clock)
    drawn = await delays(adapter, clock, 1000)
    assert abs(statistics.median(drawn) - median_ms) <= 0.10 * median_ms
    assert min(drawn) > 0
    assert len(set(drawn)) > 900  # a distribution, not a constant


async def test_zero_sigma_is_a_fixed_latency():
    clock = ManualClock()
    adapter = LatencyStubAdapter(seed=0, median_ms=300, sigma=0.0, clock=clock)
    assert await delays(adapter, clock, 10) == [pytest.approx(300.0)] * 10


def test_rejects_invalid_parameters():
    with pytest.raises(ValueError):
        LatencyStubAdapter(seed=0, median_ms=0, sigma=0.5, clock=ManualClock())
    with pytest.raises(ValueError):
        LatencyStubAdapter(seed=0, median_ms=100, sigma=-0.1, clock=ManualClock())


async def test_is_labelled_stub_llm_for_reports():
    adapter = LatencyStubAdapter(seed=0, median_ms=100, sigma=0.5, clock=ManualClock())
    assert adapter.label == STUB_LABEL == "stub LLM"
    result = await adapter.complete("bench-answer", req())
    assert result.provider == adapter.name == "bench"
    assert result.model == "bench-answer"


async def test_default_text_is_deterministic_echo():
    adapter = LatencyStubAdapter(seed=0, median_ms=100, sigma=0.5, clock=ManualClock())
    result = await adapter.complete("m", req("hello world"))
    assert result.text == "[m] hello world"
    assert result.usage.input_tokens == 2 and result.usage.output_tokens == 3


async def test_streaming_yields_the_full_text_and_spends_the_drawn_delay():
    clock = ManualClock()
    streamer = LatencyStubAdapter(seed=3, median_ms=500, sigma=0.5, clock=clock)
    twin_clock = ManualClock()
    twin = LatencyStubAdapter(seed=3, median_ms=500, sigma=0.5, clock=twin_clock)
    expected = await twin.complete("m", req("the quick brown fox jumps"))

    deltas: list[str] = []
    times: list[float] = []

    async def on_delta(text: str) -> None:
        deltas.append(text)
        times.append(clock.now())

    result = await streamer.stream("m", req("the quick brown fox jumps"), on_delta)
    assert "".join(deltas) == result.text == expected.text
    assert len(deltas) > 1
    assert times[0] > 0  # time to first token is part of the latency
    assert times == sorted(times)
    assert clock.now() == pytest.approx(twin_clock.now())  # same total delay per seed
    assert result.latency_ms == pytest.approx(expected.latency_ms)


async def test_structured_output_goes_through_the_extractive_responder():
    adapter = LatencyStubAdapter(
        seed=0, median_ms=100, sigma=0.5, clock=ManualClock(), responder=ExtractiveResponder()
    )
    claim = "the label warns of falls"
    prompt = f"<claim>\n{claim}\n</claim>\n<quote>\n{claim}\n</quote>"
    result = await adapter.complete("m", req(prompt, schema_name=JUDGE_SCHEMA))
    assert json.loads(result.text)["entailed"] is True


async def test_embed_is_deterministic_and_normalised():
    adapter = LatencyStubAdapter(seed=0, median_ms=100, sigma=0.5, clock=ManualClock())
    [v1], [v2] = await adapter.embed("e", ["x"], 8), await adapter.embed("e", ["x"], 8)
    assert v1 == v2 and len(v1) == 8
    assert sum(x * x for x in v1) == pytest.approx(1.0)


def test_build_router_in_bench_mode_uses_the_stub_for_llm_tiers(redis_client):
    settings = Settings(
        _env_file=None,
        anthropic_api_key=None,
        gemini_api_key=None,
        llm_bench=True,
        llm_bench_seed=11,
        llm_bench_median_ms=650.0,
        llm_bench_sigma=0.4,
    )
    router = build_router(settings, redis_client, clock=ManualClock())
    assert isinstance(router, LLMRouter)
    stub = router.providers["bench"]
    assert isinstance(stub, LatencyStubAdapter)
    assert (stub.seed, stub.median_ms, stub.sigma) == (11, 650.0, 0.4)
    assert isinstance(stub.responder, ExtractiveResponder)
    for tier in ("extract", "answer", "judge"):
        assert router.chains[tier] == [Route("bench", f"bench-{tier}")]
    assert router.chains["embed"] == [Route("tei", settings.model_embed)]
    assert isinstance(router.providers["tei"], TEIEmbeddingAdapter)
    assert set(router.providers) == {"bench", "tei"}


def test_bench_mode_replaces_real_providers_even_with_keys_set(redis_client):
    settings = Settings(
        _env_file=None, anthropic_api_key="fake", gemini_api_key="fake", llm_bench=True
    )
    router = build_router(settings, redis_client, clock=ManualClock())
    assert set(router.providers) == {"bench", "tei"}


async def test_bench_router_streams_through_the_stub(redis_client):
    clock = ManualClock()
    settings = Settings(_env_file=None, llm_bench=True, llm_bench_median_ms=400.0)
    router = build_router(settings, redis_client, clock=clock)
    deltas: list[str] = []

    async def on_delta(text: str) -> None:
        deltas.append(text)

    result = await router.stream("answer", req("hello there"), on_delta)
    assert "".join(deltas) == result.text == "[bench-answer] hello there"
    assert result.provider == "bench" and clock.now() > 0
