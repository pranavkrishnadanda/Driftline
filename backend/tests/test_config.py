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


def test_ingest_settings_defaults_and_local_postgres_port():
    s = Settings(_env_file=None)
    assert s.database_url == "postgresql://driftline:driftline@localhost:5433/driftline"
    assert s.github_token is None and s.openfda_api_key is None
    assert s.upload_root == "/data/uploads"
    assert (s.chunk_tokens, s.chunk_overlap_tokens) == (256, 32)
    assert s.embed_batch_size == 32
    assert s.relation_apply_threshold == 0.8
    assert s.outbox_batch_size == 100
    assert s.http_timeout_s == 120.0


def test_retrieval_and_agent_settings_defaults():
    s = Settings(_env_file=None)
    assert s.rerank_url == "http://localhost:8081"
    assert s.rerank_model == "BAAI/bge-reranker-base"
    assert (s.retrieval_candidates, s.rerank_top_n, s.rrf_k) == (30, 8, 60)
    assert (s.max_subagents, s.max_verify_retries) == (4, 2)
    assert s.model_judge == "claude-sonnet-5-5"
    assert s.answer_max_output_tokens == 4096
    assert s.llm_offline is False
    assert s.semantic_cache_enabled is True and s.semantic_cache_threshold == 0.95
    assert (s.ask_max_pending, s.ask_retry_after_s) == (200, 5)
    assert s.ask_queue_timeout_s == 300  # queued asks with no stream entry are reaped after
    assert s.sse_heartbeat_s == 15.0
    assert s.langfuse_public_key is None and s.langfuse_secret_key is None


def test_drift_and_review_defaults():
    s = Settings(_env_file=None)
    assert s.drift_enabled is True
    assert s.drift_batch == 50
    assert s.review_confidence_threshold == 0.6


def test_drift_worker_and_scheduler_settings():
    s = Settings(_env_file=None)
    assert s.source_stale_after_failures == 3
    assert s.poll_interval_s == 60.0
    assert s.alert_events_maxlen == 10_000
    assert s.alert_events_ttl_s == 30 * 24 * 3600


def test_bench_llm_settings_default_off():
    s = Settings(_env_file=None)
    assert s.llm_bench is False
    assert (s.llm_bench_seed, s.llm_bench_median_ms, s.llm_bench_sigma) == (0, 800.0, 0.5)
    s = Settings(_env_file=None, llm_bench=True, llm_bench_median_ms=1200.0)
    assert s.llm_bench is True and s.llm_bench_median_ms == 1200.0
