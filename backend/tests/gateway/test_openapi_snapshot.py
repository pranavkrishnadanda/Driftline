"""The checked-in OpenAPI document (`contracts/openapi.json`) matches the gateway.

The frontend generates its typed API client from that file, so any change to the
gateway's routes or models must regenerate it. Set DRIFTLINE_UPDATE_SNAPSHOTS=1 to
rewrite it; otherwise any difference fails this test.
"""

import json
import os
from pathlib import Path

from driftline.config import Settings
from driftline.gateway.app import create_app

SNAPSHOT = Path(__file__).resolve().parents[3] / "contracts" / "openapi.json"
UPDATE_HINT = (
    "contracts/openapi.json is out of date. Regenerate it with:\n"
    "  cd backend && DRIFTLINE_UPDATE_SNAPSHOTS=1 uv run pytest "
    "tests/gateway/test_openapi_snapshot.py\n"
    "then run `npm run gen:api:file` in frontend/ and commit both files."
)


def render_openapi() -> str:
    document = create_app(Settings(_env_file=None)).openapi()
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def test_openapi_snapshot_matches_the_gateway():
    current = render_openapi()
    if os.environ.get("DRIFTLINE_UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(current, encoding="utf-8")
    assert SNAPSHOT.exists(), f"{SNAPSHOT} is missing.\n{UPDATE_HINT}"
    assert SNAPSHOT.read_text(encoding="utf-8") == current, UPDATE_HINT


def test_snapshot_documents_the_health_routes():
    paths = json.loads(render_openapi())["paths"]
    assert {"/healthz", "/readyz"} <= paths.keys()
