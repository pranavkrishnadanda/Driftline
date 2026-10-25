"""The nightly drift-watch workflow and its pinned sources (checked-in config)."""

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "drift-watch.yml"
SOURCES = ROOT / "deploy" / "drift-watch" / "sources.json"
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def run_lines(job: dict) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_workflow_triggers_permissions_and_services():
    wf = load_workflow()
    triggers = wf[True]  # YAML 1.1 reads the `on` key as True
    assert triggers["schedule"] == [{"cron": "30 2 * * *"}]
    assert "workflow_dispatch" in triggers
    assert wf["permissions"] == {"contents": "write"}
    job = wf["jobs"]["drift-watch"]
    assert set(job["services"]) == {"postgres", "redis", "embedder"}
    assert job["env"]["DRIFTLINE_LLM_OFFLINE"] == "true"
    assert "ANTHROPIC" not in json.dumps(job["env"])


def test_workflow_runs_the_pipeline_in_order_and_commits_only_on_change():
    script = run_lines(load_workflow()["jobs"]["drift-watch"])
    order = [
        "driftline.db.migrate",
        "driftline.ingest relay",
        "driftline.ingest enqueue",
        "driftline.ingest worker --drain",
        "driftline.drift worker --drain",
        "driftline.drift report",
        "git diff --cached --quiet",
        "git commit",
    ]
    positions = [script.index(cmd) for cmd in order]
    assert positions == sorted(positions)
    assert "git log -1 --format=%an" in script and "git log -1 --format=%ae" in script
    lowered = script.lower()
    assert "co-authored" not in lowered and "claude" not in lowered


def test_workflow_actions_match_ci_pins():
    def uses(path: Path) -> set[str]:
        wf = yaml.safe_load(path.read_text())
        return {s["uses"] for job in wf["jobs"].values() for s in job["steps"] if "uses" in s}

    ci = uses(WORKFLOW.parent / "ci.yml")
    drift = uses(WORKFLOW)
    assert drift == {"actions/checkout@v7", "astral-sh/setup-uv@v10.3.2"}
    assert drift <= ci


def test_pinned_sources_are_five_labels_and_two_kubernetes_releases():
    config = json.loads(SOURCES.read_text())
    by_kind = {s["kind"]: s for s in config["sources"]}
    assert set(by_kind) == {"openfda", "git_docs"}

    labels = by_kind["openfda"]
    set_ids = [p["set_id"] for p in labels["pinned"]]
    assert len(set_ids) == len(set(set_ids)) == 5
    assert all(UUID.match(s) for s in set_ids)
    assert all(p["dailymed_versions_2026_10_25"] >= 3 for p in labels["pinned"])
    # Discovery (enqueue --discover) finds exactly the pinned labels.
    assert sorted(re.findall(r'"([0-9a-f-]{36})"', labels["config"]["search"])) == sorted(set_ids)
    assert labels["config"]["limit"] == 5

    k8s = by_kind["git_docs"]["config"]
    assert len(k8s["branches"]) == 2
    assert all(re.fullmatch(r"release-1\.\d+", b) for b in k8s["branches"])
    assert k8s["paths"]
