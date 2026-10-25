from driftline.config import Settings


def test_defaults_without_env_file():
    s = Settings(_env_file=None)
    assert s.embed_dim == 768
    assert s.model_answer
    assert s.model_extract
    assert s.model_embed
    assert s.database_url.startswith("postgresql://")
    assert s.redis_url.startswith("redis://")


def test_explicit_values_override_defaults():
    s = Settings(_env_file=None, model_answer="custom-pro", embed_dim=768)
    assert s.model_answer == "custom-pro"
