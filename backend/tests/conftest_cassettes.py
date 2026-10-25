"""Skip a recorded-HTTP test only when its cassette is missing and nothing may be recorded."""

import os

import pytest


def _provider(request: pytest.FixtureRequest) -> str:
    explicit = getattr(request.module, "CASSETTE_PROVIDER", None)
    if explicit:
        return explicit
    name = request.module.__name__.rsplit(".", 1)[-1]
    return name.removeprefix("test_").removesuffix("_adapter") or "provider"


@pytest.fixture
def require_cassette(
    request: pytest.FixtureRequest, vcr_cassette_dir: str, default_cassette_name: str
) -> str:
    """Resolve pytest-recording's cassette path; skip if absent while --record-mode is none."""
    path = os.path.join(vcr_cassette_dir, f"{default_cassette_name}.yaml")
    # pytest-recording leaves --record-mode as None when unset, which it treats as "none".
    record_mode = request.config.getoption("--record-mode") or "none"
    if record_mode == "none" and not os.path.exists(path):
        pytest.skip(f"cassette not recorded: {_provider(request)} credentials/credits required")
    return path
