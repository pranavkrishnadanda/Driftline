"""Skip recorded-HTTP tests whose cassette has not been recorded yet.

This is a skip, not a mock: as soon as the cassette file exists (or recording is
enabled with ``--record-mode``), the test runs the real adapter code.
"""

import re
from pathlib import Path
from typing import Any

import pytest

# Response headers that identify the recording account. They are not secrets, but they
# have no place in a public repo and replay never needs them.
_ACCOUNT_HEADER = re.compile(
    r"^(anthropic-organization-id|anthropic-workspace-id|request-id|cf-ray|x-goog-.*project.*)$",
    re.IGNORECASE,
)


def scrub_response_headers(response: dict[str, Any]) -> dict[str, Any]:
    """vcrpy ``before_record_response`` hook: drop account-identifying response headers."""
    headers = response.get("headers")
    if headers:
        response["headers"] = {k: v for k, v in headers.items() if not _ACCOUNT_HEADER.match(k)}
    return response


def _provider_name(module_name: str) -> str:
    # test_gemini_adapter -> gemini, test_anthropic_adapter -> anthropic
    return module_name.removeprefix("test_").removesuffix("_adapter")


@pytest.fixture
def require_cassette(request: pytest.FixtureRequest) -> None:
    record_mode = request.config.getoption("--record-mode") or "none"
    if record_mode != "none":
        return
    # Resolve the path through pytest-recording's own fixtures so overrides are honoured:
    # <test dir>/cassettes/<module name>/<test name>.yaml by default.
    cassette_dir = Path(request.getfixturevalue("vcr_cassette_dir"))
    cassette = cassette_dir / f"{request.getfixturevalue('default_cassette_name')}.yaml"
    if not cassette.exists():
        provider = _provider_name(request.module.__name__.rsplit(".", 1)[-1])
        pytest.skip(f"cassette not recorded: {provider} credentials/credits required")
