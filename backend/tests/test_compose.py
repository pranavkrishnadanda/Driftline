from pathlib import Path

import yaml

COMPOSE = Path(__file__).resolve().parents[2] / "deploy" / "compose" / "docker-compose.yml"


def test_gateway_has_healthz_healthcheck():
    gateway = yaml.safe_load(COMPOSE.read_text())["services"]["gateway"]
    assert "/healthz" in " ".join(gateway["healthcheck"]["test"])
