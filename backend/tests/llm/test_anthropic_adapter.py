import os

import pytest
from anthropic.types import Message as SdkMessage
from anthropic.types import TextBlock, ThinkingBlock
from anthropic.types import Usage as SdkUsage

from driftline.llm.adapters.anthropic import AnthropicAdapter, _result_text
from driftline.llm.types import CompletionRequest, Message, ProviderError, Role

CASSETTE_PROVIDER = "anthropic"
API_KEY = os.environ.get("DRIFTLINE_ANTHROPIC_API_KEY", "replay-only")
MODEL = "claude-haiku-5-5"


@pytest.fixture(scope="module")
def vcr_config():
    return {
        "filter_headers": ["x-api-key", "authorization"],
        "match_on": ["method", "scheme", "host", "path"],
    }


def _sdk_message(content, stop_reason="end_turn") -> SdkMessage:
    return SdkMessage(
        id="msg_offline",
        type="message",
        role="assistant",
        model=MODEL,
        content=content,
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=SdkUsage(input_tokens=7, output_tokens=0),
    )


@pytest.mark.vcr
async def test_complete_returns_text_and_usage(require_cassette):
    adapter = AnthropicAdapter(API_KEY)
    result = await adapter.complete(
        MODEL,
        CompletionRequest(
            messages=[
                Message(role=Role.system, content="You answer with one word."),
                Message(role=Role.user, content="Reply with exactly the word PONG."),
            ],
            max_output_tokens=1024,
        ),
    )
    assert "PONG" in result.text.upper()
    assert result.provider == "anthropic"
    assert result.model == MODEL
    assert result.usage.input_tokens > 0


@pytest.mark.vcr
async def test_unknown_model_is_non_retryable_provider_error(require_cassette):
    with pytest.raises(ProviderError) as exc_info:
        await AnthropicAdapter(API_KEY).complete(
            "claude-does-not-exist-xyz",
            CompletionRequest(messages=[Message(role=Role.user, content="hi")]),
        )
    assert exc_info.value.retryable is False
    assert exc_info.value.status == 404


def test_empty_response_raises_non_retryable():
    with pytest.raises(ProviderError) as exc_info:
        _result_text(_sdk_message([], stop_reason="max_tokens"))
    assert exc_info.value.retryable is False
    assert "max_tokens" in str(exc_info.value)


def test_result_text_joins_text_blocks_and_skips_thinking():
    message = _sdk_message(
        [
            ThinkingBlock(type="thinking", thinking="", signature="sig"),
            TextBlock(type="text", text="PO"),
            TextBlock(type="text", text="NG"),
        ]
    )
    assert _result_text(message) == "PONG"


async def test_embed_is_unsupported():
    with pytest.raises(ProviderError) as exc_info:
        await AnthropicAdapter("unused").embed("any-model", ["text"], 768)
    assert exc_info.value.retryable is False
    assert "does not provide embeddings" in str(exc_info.value)
