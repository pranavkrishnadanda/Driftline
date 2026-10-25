from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DRIFTLINE_", env_file=".env", extra="ignore")

    # Host port 5433 matches deploy/compose (5432 is often a native Postgres).
    database_url: str = "postgresql://driftline:driftline@localhost:5433/driftline"
    redis_url: str = "redis://localhost:6379/0"

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
