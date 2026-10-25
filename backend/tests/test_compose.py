from pathlib import Path

import yaml

COMPOSE = Path(__file__).resolve().parents[2] / "deploy" / "compose" / "docker-compose.yml"


def test_gateway_has_healthz_healthcheck():
    gateway = yaml.safe_load(COMPOSE.read_text())["services"]["gateway"]
    assert "/healthz" in " ".join(gateway["healthcheck"]["test"])


def _services():
    return yaml.safe_load(COMPOSE.read_text())["services"]


def test_workers_have_heartbeat_healthchecks_and_the_anthropic_key():
    services = _services()
    for name in ("ingest-worker", "outbox-relay", "agent-worker"):
        test = " ".join(services[name]["healthcheck"]["test"])
        assert "driftline.health" in test, name
        env = services[name]["environment"]
        assert env["DRIFTLINE_ANTHROPIC_API_KEY"] == "${DRIFTLINE_ANTHROPIC_API_KEY:-}", name
    assert services["gateway"]["environment"]["DRIFTLINE_ANTHROPIC_API_KEY"]


def test_reranker_and_agent_worker_services():
    services = _services()
    reranker = services["reranker"]
    assert reranker["command"] == ["--model-id", "BAAI/bge-reranker-base"]
    assert reranker["ports"] == ["${DRIFTLINE_RERANK_PORT:-8081}:80"]
    agent = services["agent-worker"]
    assert agent["command"] == ["python", "-m", "driftline.agents", "worker"]
    assert agent["environment"]["DRIFTLINE_RERANK_URL"] == "http://reranker:80"
    assert "ports" not in agent and "container_name" not in agent  # --scale agent-worker=N


def test_drift_worker_service():
    services = _services()
    drift = services["drift-worker"]
    assert drift["command"] == ["python", "-m", "driftline.drift", "worker"]
    assert "driftline.health" in " ".join(drift["healthcheck"]["test"])
    assert drift["environment"]["DRIFTLINE_ANTHROPIC_API_KEY"] == "${DRIFTLINE_ANTHROPIC_API_KEY:-}"
    assert "ports" not in drift and "container_name" not in drift  # --scale drift-worker=N


def test_drift_poll_service():
    """The source scheduler: one replica is enough (claims are compare-and-set), and it
    discovers sources through the same connectors as the ingest worker."""
    services = _services()
    poll = services["drift-poll"]
    assert poll["command"] == ["python", "-m", "driftline.drift", "poll"]
    assert "driftline.health" in " ".join(poll["healthcheck"]["test"])
    env = poll["environment"]
    drift_env = services["drift-worker"]["environment"]
    assert env["DRIFTLINE_DATABASE_URL"] == drift_env["DRIFTLINE_DATABASE_URL"]
    for key in ("DRIFTLINE_GITHUB_TOKEN", "DRIFTLINE_OPENFDA_API_KEY"):
        assert env[key] == "${" + key + ":-}", key
    ingest = services["ingest-worker"]
    assert env["DRIFTLINE_UPLOAD_ROOT"] == ingest["environment"]["DRIFTLINE_UPLOAD_ROOT"]
    assert poll["volumes"] == ingest["volumes"]  # it lists the same upload root
    assert "ports" not in poll and "container_name" not in poll
    assert poll["depends_on"]["gateway"] == {"condition": "service_healthy"}
