import os

import pytest
from google.genai import types as gtypes

from driftline.llm.adapters.gemini import GeminiAdapter, _result_text
from driftline.llm.types import CompletionRequest, Message, ProviderError, Role

API_KEY = os.environ.get("DRIFTLINE_GEMINI_API_KEY", "replay-only")
MODEL = os.environ.get("DRIFTLINE_MODEL_EXTRACT", "gemini-3.8-flash")
EMBED_MODEL = os.environ.get("DRIFTLINE_MODEL_EMBED", "gemini-embedding-001")


@pytest.fixture(scope="module")
def vcr_config():
    return {
        "filter_headers": ["x-goog-api-key", "authorization"],
        "filter_query_parameters": ["key"],
        "match_on": ["method", "scheme", "host", "path"],
    }


@pytest.mark.vcr
async def test_complete_returns_text_and_usage():
    adapter = GeminiAdapter(API_KEY)
    result = await adapter.complete(
        MODEL,
        CompletionRequest(
            messages=[
                Message(role=Role.system, content="You answer with one word."),
                Message(role=Role.user, content="Reply with exactly the word PONG."),
            ],
            max_output_tokens=512,
        ),
    )
    assert "PONG" in result.text.upper()
    assert result.provider == "gemini"
    assert result.model == MODEL
    assert result.usage.input_tokens > 0


@pytest.mark.vcr
async def test_embed_returns_vectors_of_requested_dim():
    vectors = await GeminiAdapter(API_KEY).embed(EMBED_MODEL, ["boxed warning", "kubectl"], 768)
    assert len(vectors) == 2
    assert all(len(v) == 768 for v in vectors)


@pytest.mark.vcr
async def test_unknown_model_is_non_retryable_provider_error():
    with pytest.raises(ProviderError) as exc_info:
        await GeminiAdapter(API_KEY).complete(
            "gemini-does-not-exist-xyz",
            CompletionRequest(messages=[Message(role=Role.user, content="hi")]),
        )
    assert exc_info.value.retryable is False
    assert exc_info.value.status == 404


def test_empty_response_raises_non_retryable():
    blocked = gtypes.GenerateContentResponse(
        candidates=[gtypes.Candidate(finish_reason=gtypes.FinishReason.SAFETY)]
    )
    with pytest.raises(ProviderError) as exc_info:
        _result_text(blocked)
    assert exc_info.value.retryable is False
    assert "SAFETY" in str(exc_info.value)
