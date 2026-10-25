import json

import pytest
from pydantic import BaseModel

from driftline.clock import ManualClock
from driftline.config import Settings
from driftline.llm.adapters.deterministic import DeterministicAdapter, FailMidStream
from driftline.llm.adapters.tei import TEIEmbeddingAdapter
from driftline.llm.breaker import CircuitBreaker
from driftline.llm.router import (
    AllRoutesFailed,
    LLMRouter,
    Route,
    StreamInterrupted,
    StructuredOutputError,
    build_router,
    parse_json_reply,
)
from driftline.llm.types import CompletionRequest, Message, ProviderError, Role


class Verdict(BaseModel):
    entailed: bool
    reason: str


GOOD = json.dumps({"entailed": True, "reason": "quoted"})


def req(text="judge this"):
    return CompletionRequest(messages=[Message(role=Role.user, content=text)])


def router(primary, secondary=None):
    providers = {"p": primary, "s": secondary or DeterministicAdapter("s")}
    return LLMRouter(
        providers=providers,
        chains={"judge": [Route("p", "big"), Route("s", "small")]},
        clock=ManualClock(),
    )


def collector():
    deltas: list[str] = []

    async def on_delta(text: str) -> None:
        deltas.append(text)

    return deltas, on_delta


def test_parse_json_reply_tolerates_fences_and_prose():
    assert parse_json_reply(f"```json\n{GOOD}\n```", Verdict).entailed is True
    assert parse_json_reply(f"Sure! {GOOD} Hope that helps.", Verdict).reason == "quoted"
    with pytest.raises(ValueError):
        parse_json_reply("no object here", Verdict)


async def test_structured_sends_schema_and_returns_the_model():
    p = DeterministicAdapter("p", script=[GOOD])
    verdict, result = await router(p).structured("judge", req(), Verdict)
    assert verdict == Verdict(entailed=True, reason="quoted")
    assert result.provider == "p" and result.degraded is False
    sent = p.requests[0]
    assert sent.response_schema == Verdict.model_json_schema()
    assert sent.schema_name == "Verdict"


async def test_structured_repairs_malformed_json_once():
    p = DeterministicAdapter("p", script=["I think it is entailed.", GOOD])
    verdict, _ = await router(p).structured("judge", req(), Verdict)
    assert verdict.entailed is True
    repair = p.requests[1].messages
    assert [m.role for m in repair] == [Role.user, Role.assistant, Role.user]
    assert repair[1].content == "I think it is entailed."
    assert "did not match the required JSON schema" in repair[2].content


async def test_structured_raises_after_repairs_without_falling_back():
    p = DeterministicAdapter("p", script=["nope", '{"entailed": "maybe"}'])
    s = DeterministicAdapter("s")
    r = router(p, s)
    with pytest.raises(StructuredOutputError) as exc_info:
        await r.structured("judge", req(), Verdict)
    assert exc_info.value.raw == '{"entailed": "maybe"}'
    assert exc_info.value.schema_name == "Verdict"
    assert s.calls == []  # a bad reply is not a provider outage: no fallback
    assert r.breaker(Route("p", "big")).state.value == "closed"


async def test_stream_delivers_deltas_and_falls_back_before_first_delta():
    err = ProviderError("overloaded", retryable=False, status=529)
    p = DeterministicAdapter("p", script=[err])
    deltas, on_delta = collector()
    result = await router(p).stream("judge", req("hi there"), on_delta)
    assert result.provider == "s" and result.degraded is True
    assert "".join(deltas) == result.text == "[small] hi there"


async def test_stream_failure_after_deltas_raises_stream_interrupted():
    err = ProviderError("overloaded", retryable=True, status=529)
    p = DeterministicAdapter("p", script=[FailMidStream(after_deltas=1, error=err)])
    s = DeterministicAdapter("s")
    deltas, on_delta = collector()
    with pytest.raises(StreamInterrupted) as exc_info:
        await router(p, s).stream("judge", req("one two"), on_delta)
    assert exc_info.value.delivered == 1 and exc_info.value.cause is err
    assert deltas == ["[big] "] and s.calls == []


async def test_stream_interrupted_counts_as_a_breaker_failure():
    # The provider failed mid-reply: the breaker must learn about it, not just let it pass.
    err = ProviderError("overloaded", retryable=True, status=529)
    p = DeterministicAdapter("p", script=[FailMidStream(after_deltas=1, error=err)])
    clock = ManualClock()
    r = LLMRouter(
        providers={"p": p},
        chains={"judge": [Route("p", "big")]},
        clock=clock,
        breaker_factory=lambda: CircuitBreaker(clock=clock, failure_threshold=1),
    )
    _, on_delta = collector()
    with pytest.raises(StreamInterrupted):
        await r.stream("judge", req("one two"), on_delta)
    assert r.breaker(Route("p", "big")).state.value == "open"


async def test_stream_uses_complete_for_providers_without_stream(embedder_url):
    # TEI has no `stream` (and cannot complete): the error is a normal routing failure.
    r = LLMRouter(
        providers={"tei": TEIEmbeddingAdapter(embedder_url)},
        chains={"judge": [Route("tei", "bge")]},
        clock=ManualClock(),
    )
    deltas, on_delta = collector()
    with pytest.raises(AllRoutesFailed):
        await r.stream("judge", req(), on_delta)
    assert deltas == []


async def test_structured_streams_json_deltas():
    p = DeterministicAdapter("p", script=[GOOD])
    deltas, on_delta = collector()
    verdict, _ = await router(p).structured("judge", req(), Verdict, on_delta=on_delta)
    assert verdict.entailed and "".join(deltas) == GOOD and len(deltas) > 1


def test_build_router_has_judge_chain(redis_client):
    settings = Settings(_env_file=None, anthropic_api_key="fake", gemini_api_key=None)
    r = build_router(settings, redis_client, clock=ManualClock())
    assert [(x.provider, x.model) for x in r.chains["judge"]] == [
        ("anthropic", "claude-sonnet-5-5"),
        ("anthropic", "claude-haiku-5-5"),
    ]
