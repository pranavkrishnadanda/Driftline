import math

import pytest

from driftline.clock import ManualClock
from driftline.llm.adapters.deterministic import DeterministicAdapter, FailMidStream
from driftline.llm.types import CompletionRequest, Message, ProviderError, Role


def req(text):
    return CompletionRequest(messages=[Message(role=Role.user, content=text)])


async def test_completion_is_deterministic():
    a = DeterministicAdapter("p")
    r1 = await a.complete("m1", req("hello world"))
    r2 = await a.complete("m1", req("hello world"))
    assert r1.text == r2.text == "[m1] hello world"
    assert r1.provider == "p"
    assert r1.usage.input_tokens == 2
    assert a.calls == ["m1", "m1"]


async def test_script_raises_in_order_then_succeeds():
    err = ProviderError("rate limited", retryable=True, status=429)
    a = DeterministicAdapter("p", script=[err, None])
    with pytest.raises(ProviderError):
        await a.complete("m", req("x"))
    assert (await a.complete("m", req("x"))).text == "[m] x"
    assert (await a.complete("m", req("x"))).text == "[m] x"


async def test_latency_uses_clock():
    clock = ManualClock(0.0)
    a = DeterministicAdapter("p", latency_ms=250, clock=clock)
    r = await a.complete("m", req("x"))
    assert clock.now() == pytest.approx(0.25)
    assert r.latency_ms == pytest.approx(250)


async def test_embed_is_stable_and_unit_norm():
    a = DeterministicAdapter("p")
    v1, v2 = await a.embed("e", ["alpha", "beta"], 768)
    assert len(v1) == 768
    assert math.isclose(math.sqrt(sum(x * x for x in v1)), 1.0, rel_tol=1e-9)
    assert v1 != v2
    assert (await a.embed("e", ["alpha"], 768))[0] == v1


async def test_script_strings_are_replies_and_responder_sets_default():
    seen = []

    def responder(model, request):
        seen.append(request.schema_name)
        return '{"ok": true}'

    a = DeterministicAdapter("p", script=["not json", None], responder=responder)
    assert (await a.complete("m", req("x"))).text == "not json"
    assert (await a.complete("m", req("x"))).text == '{"ok": true}'
    assert seen == [None]
    assert [r.messages[-1].content for r in a.requests] == ["x", "x"]


async def test_stream_delivers_words_that_join_to_the_reply():
    a = DeterministicAdapter("p")
    deltas = []

    async def on_delta(text):
        deltas.append(text)

    result = await a.stream("m", req("hello  big world"), on_delta)
    assert "".join(deltas) == result.text == "[m] hello  big world"
    assert deltas == ["[m] ", "hello  ", "big ", "world"]


async def test_fail_mid_stream_raises_after_some_deltas():
    err = ProviderError("overloaded", retryable=True, status=529)
    a = DeterministicAdapter("p", script=[FailMidStream(after_deltas=2, error=err)])
    deltas = []

    async def on_delta(text):
        deltas.append(text)

    with pytest.raises(ProviderError):
        await a.stream("m", req("one two three"), on_delta)
    assert deltas == ["[m] ", "one "]


async def test_fail_mid_stream_raises_even_when_reply_is_shorter_than_after_deltas():
    err = ProviderError("overloaded", retryable=True, status=529)
    a = DeterministicAdapter("p", script=[FailMidStream(after_deltas=10, error=err)])
    deltas = []

    async def on_delta(text):
        deltas.append(text)

    with pytest.raises(ProviderError):
        await a.stream("m", req("one"), on_delta)
    assert deltas == ["[m] ", "one"]


async def test_fail_mid_stream_fails_a_plain_complete():
    err = ProviderError("overloaded", retryable=True, status=529)
    a = DeterministicAdapter("p", script=[FailMidStream(after_deltas=1, error=err)])
    with pytest.raises(ProviderError):
        await a.complete("m", req("one two"))
