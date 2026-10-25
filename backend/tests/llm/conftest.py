import os

import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import HttpWaitStrategy

EMBED_MODEL = "BAAI/bge-base-en-v1.5"
TEI_TAGS = {"arm64": "cpu-arm64-1.9.4", "aarch64": "cpu-arm64-1.9.4", "x86_64": "cpu-1.9.4"}
TEI_REPO = "ghcr.io/huggingface/text-embeddings-inference"
# Named Docker volume that keeps the downloaded model between test runs.
MODEL_CACHE_VOLUME = "driftline-tei-model-cache"


def _tei_image(container: DockerContainer) -> str:
    override = os.environ.get("DRIFTLINE_EMBED_IMAGE")
    if override:
        return override
    arch = container.get_docker_client().client.info()["Architecture"]
    return f"{TEI_REPO}:{TEI_TAGS.get(arch, TEI_TAGS['x86_64'])}"


@pytest.fixture(scope="session")
def embedder_url():
    container = DockerContainer("placeholder")
    container.image = _tei_image(container)
    container = (
        container.with_command(["--model-id", EMBED_MODEL])
        .with_exposed_ports(80)
        .with_volume_mapping(MODEL_CACHE_VOLUME, "/data", mode="rw")
        .with_kwargs(mem_limit="2g")
        .waiting_for(HttpWaitStrategy(80, "/health").with_startup_timeout(600))
    )
    with container:
        yield f"http://{container.get_container_host_ip()}:{container.get_exposed_port(80)}"
