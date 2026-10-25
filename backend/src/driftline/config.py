from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DRIFTLINE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql://driftline:driftline@localhost:5432/driftline"
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
