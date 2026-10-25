from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DRIFTLINE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql://driftline:driftline@localhost:5432/driftline"
    redis_url: str = "redis://localhost:6379/0"

    gemini_api_key: str | None = None
    model_extract: str = "gemini-3.8-flash"
    model_answer: str = "gemini-3.1-pro-preview"
    model_fallback: list[str] = ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
    model_embed: str = "gemini-embedding-001"
    embed_dim: int = 768
