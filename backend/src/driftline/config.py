from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DRIFTLINE_", env_file=".env", extra="ignore")

    # Host port 5433 matches deploy/compose (5432 is often a native Postgres).
    database_url: str = "postgresql://driftline:driftline@localhost:5433/driftline"
    redis_url: str = "redis://localhost:6379/0"
    # Browser origins allowed to call the gateway (the Next.js frontend, P5).
    cors_origins: list[str] = ["http://localhost:3000"]
    # P6: when true, every tenant-scoped route needs `Authorization: Bearer <tenant key>`.
    # When false (dev mode), a tenant name is enough; a key, if sent, must still be valid.
    auth_required: bool = False
    # Host headers the MCP endpoint (/mcp) accepts; anything else gets 421 (the SDK's DNS
    # rebinding protection). `name:*` allows any port. Browser Origins are allowed for the
    # same hosts over http and https. Add the name clients reach the gateway by, e.g.
    # DRIFTLINE_MCP_ALLOWED_HOSTS='["localhost:*","127.0.0.1:*","gateway:*"]' in Compose.
    mcp_allowed_hosts: list[str] = ["localhost:*", "127.0.0.1:*", "[::1]:*"]

    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    embed_url: str = "http://localhost:8080"

    model_extract: str = "claude-haiku-5-5"
    model_answer: str = "claude-sonnet-5-5"
    # Extra Anthropic models tried after the primary routes, before any Gemini fallback.
    model_fallback: list[str] = []
    # Used only when gemini_api_key is set.
    gemini_fallback_models: list[str] = ["gemini-3.8-flash"]
    model_embed: str = "BAAI/bge-base-en-v1.5"
    embed_dim: int = 768
    # Haiku 5.5 thinks by default and thinking tokens count against max_tokens.
    default_max_output_tokens: int = 2048
    # Per-request LLM timeout (seconds) instead of the Anthropic SDK's 600 s default.
    llm_timeout_s: float = 120.0

    # Ingestion (P2)
    github_token: str | None = None  # optional; raises GitHub's limit from 60 to 5,000/hour
    openfda_api_key: str | None = None  # optional; raises openFDA's limit to 120,000/day
    upload_root: str = "/data/uploads"
    # cl100k tokens; measured <= 320 bge WordPiece tokens, under TEI's 512 limit.
    chunk_tokens: int = 256
    chunk_overlap_tokens: int = 32
    embed_batch_size: int = 32  # TEI's default --max-client-batch-size
    relation_apply_threshold: float = 0.8  # spec section 5
    outbox_batch_size: int = 100
    http_timeout_s: float = 120.0  # raw.githubusercontent.com can take 45 s from here

    # Retrieval + agent (P3)
    rerank_url: str | None = "http://localhost:8081"  # TEI /rerank; None disables reranking
    rerank_model: str = "BAAI/bge-reranker-base"
    retrieval_candidates: int = 30  # spec section 5: hybrid search, top 30
    rerank_top_n: int = 8  # spec section 5: rerank down to the top 8
    rrf_k: int = 60  # spec section 5: reciprocal-rank fusion constant
    max_subagents: int = 4
    max_verify_retries: int = 2  # spec section 5: re_retrieve at most 2 loops
    model_judge: str = "claude-sonnet-5-5"
    answer_max_output_tokens: int = 4096  # thinking counts against it
    llm_offline: bool = False  # DeterministicAdapter + ExtractiveResponder; zero cost demos
    # P7 benchmarks: the "bench" chain (LatencyStubAdapter, a labelled stub LLM with
    # seeded log-normal latency) replaces every LLM tier; embeddings stay on TEI.
    llm_bench: bool = False
    llm_bench_seed: int = 0
    llm_bench_median_ms: float = 800.0
    llm_bench_sigma: float = 0.5
    semantic_cache_enabled: bool = True
    semantic_cache_threshold: float = 0.95  # spec section 4
    semantic_cache_ttl_s: int = 7 * 24 * 3600
    ask_max_pending: int = 200  # spec section 3: 429 above this agent-stream backlog
    ask_retry_after_s: int = 5
    # A queued ask whose agent-stream entry was never published is failed after this.
    ask_queue_timeout_s: int = 300
    sse_heartbeat_s: float = 15.0  # spec section 8
    sse_max_connections: int = 1000
    ask_events_maxlen: int = 10_000
    ask_events_ttl_s: int = 24 * 3600
    heartbeat_path: str = "/tmp/driftline-heartbeat"
    # Tracing is a no-op unless both keys are set (zero cost by default).
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    # Drift + review (P4)
    drift_enabled: bool = True
    drift_batch: int = 50  # watched answers re-checked per drift-worker pass
    review_confidence_threshold: float = 0.6  # below this an answer goes to human review
    # Per-tenant alert log (events:alerts:{tenant}); alerts outlive asks, so a longer TTL.
    alert_events_maxlen: int = 10_000
    alert_events_ttl_s: int = 30 * 24 * 3600
    # `python -m driftline.drift poll`: seconds between scheduler passes.
    poll_interval_s: float = 60.0
    # A scheduled source is marked `stale_source` after this many CONSECUTIVE scheduled
    # polls whose fetch (discovery) failed. One or two failures are usually a blip (a
    # rate limit, a 5xx, a network hiccup) that the next cycle recovers from; three in a
    # row means the source has been unreachable for ~3 of its own intervals, which is
    # worth surfacing. It also matches the stream bus's 3-delivery dead-letter rule.
    source_stale_after_failures: int = 3
