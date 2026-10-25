from driftline.config import Settings
from driftline.llm.types import CompletionRequest, Message, Role


def test_defaults_without_env_file():
    s = Settings(_env_file=None)
    assert s.embed_dim == 768
    assert s.database_url.startswith("postgresql://")
    assert s.redis_url.startswith("redis://")


def test_explicit_values_override_defaults():
    s = Settings(_env_file=None, model_answer="custom-pro", embed_dim=768)
    assert s.model_answer == "custom-pro"


def test_provider_defaults_are_claude_primary_with_open_source_embeddings():
    s = Settings(_env_file=None)
    assert s.model_extract == "claude-haiku-5-5"
    assert s.model_answer == "claude-sonnet-5-5"
    assert s.model_embed == "BAAI/bge-base-en-v1.5"
    assert s.model_fallback == []
    assert s.gemini_fallback_models == ["gemini-3.8-flash"]
    assert s.embed_url == "http://localhost:8080"


def test_api_keys_are_explicitly_settable():
    s = Settings(_env_file=None, anthropic_api_key="a-key", gemini_api_key="g-key")
    assert s.anthropic_api_key == "a-key"
    assert s.gemini_api_key == "g-key"


def test_default_model_ids_are_not_retired_2_5_models():
    s = Settings(_env_file=None)
    ids = [
        s.model_extract,
        s.model_answer,
        *s.model_fallback,
        *s.gemini_fallback_models,
        s.model_embed,
    ]
    assert all("2.5" not in model_id for model_id in ids), ids


def test_default_max_output_tokens_leaves_room_for_thinking():
    # Haiku 5.5 thinks by default and thinking tokens count against max_tokens.
    assert Settings(_env_file=None).default_max_output_tokens == 2048
    request = CompletionRequest(messages=[Message(role=Role.user, content="hi")])
    assert request.max_output_tokens == 2048
