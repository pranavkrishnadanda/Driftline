"""A real TEI reranker (BAAI/bge-reranker-base) shared by the whole session."""

import time

import httpx
import pytest
from conftest_embedder import MODEL_CACHE_VOLUME, _tei_image
from testcontainers.core.container import DockerContainer

RERANK_MODEL = "BAAI/bge-reranker-base"
# A cold start downloads ~1.1 GB into MODEL_CACHE_VOLUME (minutes); a warm one is ~10 s.
READY_TIMEOUT_S = 300.0


def _wait_until_ready(container: DockerContainer, url: str, timeout_s: float) -> None:
    """Poll /health until it answers 200. Fail loudly, with the container's logs, if the
    container exits (e.g. OOM-killed while loading) or `timeout_s` passes."""
    wrapped = container.get_wrapped_container()
    deadline = time.monotonic() + timeout_s
    while True:
        wrapped.reload()
        if wrapped.status != "running":
            state = wrapped.attrs["State"]
            logs = wrapped.logs(tail=30).decode(errors="replace")
            pytest.fail(
                f"reranker container {wrapped.status} (exit={state.get('ExitCode')}, "
                f"oom_killed={state.get('OOMKilled')}):\n{logs}"
            )
        try:
            if httpx.get(f"{url}/health", timeout=2).status_code == 200:
                return
        except httpx.TransportError:
            pass
        if time.monotonic() > deadline:
            logs = wrapped.logs(tail=30).decode(errors="replace")
            pytest.fail(f"reranker not ready after {timeout_s:.0f} s:\n{logs}")
        time.sleep(1)


@pytest.fixture(scope="session")
def reranker_url():
    container = DockerContainer("placeholder")
    container.image = _tei_image(container)
    container = (
        container.with_command(["--model-id", RERANK_MODEL])
        .with_exposed_ports(80)
        .with_volume_mapping(MODEL_CACHE_VOLUME, "/data", mode="rw")
        # Measured ~2.15 GiB resident; a 2g limit OOM-kills it while loading.
        .with_kwargs(mem_limit="3g")
    )
    with container:
        url = f"http://{container.get_container_host_ip()}:{container.get_exposed_port(80)}"
        _wait_until_ready(container, url, READY_TIMEOUT_S)
        yield url
