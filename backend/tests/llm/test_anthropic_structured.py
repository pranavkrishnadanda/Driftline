"""Structured output and streaming through the real Anthropic adapter.

Recorded tests replay real Claude responses (pytest-recording). Record once with
`--record-mode=once` and DRIFTLINE_ANTHROPIC_API_KEY loaded from backend/.env; without
the cassette they skip.
"""

import json
import os

import pytest
from conftest_cassettes import scrub_response_headers
from pydantic import BaseModel

from driftline.llm.adapters.anthropic import AnthropicAdapter, request_kwargs
from driftline.llm.types import CompletionRequest, Message, ProviderError, Role

API_KEY = os.environ.get("DRIFTLINE_ANTHROPIC_API_KEY", "replay-only")
MODEL = "claude-haiku-5-5"


class Verdict(BaseModel):
    entailed: bool
    reason: str


@pytest.fixture(scope="module")
def vcr_config():
    return {
        "filter_headers": ["x-api-key", "authorization"],
        "before_record_response": scrub_response_headers,
        "match_on": ["method", "scheme", "host", "path"],
    }


def judge_request(**overrides) -> CompletionRequest:
    values = {
        "messages": [
            Message(role=Role.system, content="You check a claim against a quote."),
            Message(
                role=Role.user,
                content="Claim: ALT is checked monthly.\nQuote: Check ALT monthly during "
                "therapy.\nIs the claim entailed by the quote?",
            ),
        ],
        "max_output_tokens": 2048,
    }
    return CompletionRequest(**(values | overrides))


def test_request_kwargs_add_output_config_only_for_structured_requests():
    plain = request_kwargs(MODEL, judge_request())
    assert "output_config" not in plain
    assert plain["system"] == "You check a claim against a quote."
    assert [m["role"] for m in plain["messages"]] == ["user"]
    structured = request_kwargs(
        MODEL, judge_request(response_schema=Verdict.model_json_schema(), schema_name="v")
    )
    fmt = structured["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["additionalProperties"] is False
    assert set(fmt["schema"]["required"]) == {"entailed", "reason"}
    for kwargs in (plain, structured):
        assert "temperature" not in kwargs and "tool_choice" not in kwargs and "tools" not in kwargs


@pytest.mark.vcr
async def test_structured_reply_is_schema_valid_json(require_cassette):
    request = judge_request(response_schema=Verdict.model_json_schema(), schema_name="verdict")
    result = await AnthropicAdapter(API_KEY).complete(MODEL, request)
    verdict = Verdict.model_validate(json.loads(result.text))
    assert verdict.entailed is True
    assert result.usage.output_tokens > 0


@pytest.mark.vcr
async def test_stream_delivers_text_deltas_and_final_usage(require_cassette):
    deltas: list[str] = []

    async def on_delta(text: str) -> None:
        deltas.append(text)

    request = CompletionRequest(
        messages=[Message(role=Role.user, content="Count from 1 to 20, separated by spaces.")],
        max_output_tokens=2048,
    )
    result = await AnthropicAdapter(API_KEY).stream(MODEL, request, on_delta)
    assert len(deltas) > 1
    assert "".join(deltas) == result.text
    assert "20" in result.text
    assert result.usage.input_tokens > 0 and result.provider == "anthropic"


@pytest.mark.vcr
async def test_stream_unknown_model_is_non_retryable_provider_error(require_cassette):
    async def on_delta(text: str) -> None:
        raise AssertionError("no delta expected")

    with pytest.raises(ProviderError) as exc_info:
        await AnthropicAdapter(API_KEY).stream(
            "claude-does-not-exist-xyz", judge_request(), on_delta
        )
    assert exc_info.value.retryable is False
    assert exc_info.value.status == 404
