from datetime import UTC, datetime

import httpx
import pytest
from conftest_cassettes import scrub_response_headers

from driftline.ingest.connectors.k8s_docs import (
    DEFAULT_BRANCHES,
    DEFAULT_PATHS,
    KubernetesDocsConnector,
    branch_minor,
    clean_hugo,
    raise_for_github,
)
from driftline.ingest.types import SourceFetchError

GUIDE = "content/en/docs/reference/using-api/deprecation-guide.md"


@pytest.fixture(scope="module")
def vcr_config():
    return {
        "filter_headers": ["authorization"],
        "before_record_response": scrub_response_headers,
        "match_on": ["method", "scheme", "host", "path", "query"],
    }


def test_branch_minor_parses_sorts_and_rejects():
    assert branch_minor("release-1.31") == (1, 31)
    branches = ["release-1.30", "release-1.4", "release-1.28"]
    assert sorted(branches, key=branch_minor) == ["release-1.4", "release-1.28", "release-1.30"]
    assert DEFAULT_BRANCHES == ("release-1.28", "release-1.29", "release-1.30", "release-1.31")
    with pytest.raises(ValueError):
        branch_minor("main")


def test_clean_hugo_keeps_tooltip_text():
    text = (
        'A {{< glossary_tooltip text="Pod" term_id="pod" >}} runs. '
        '{{< note >}}Careful.{{< /note >}} {{% heading "x" %}}'
    )
    assert clean_hugo(text) == "A Pod runs. Careful. "


def test_rate_limited_response_is_retryable():
    request = httpx.Request("GET", "https://api.github.com/repos/kubernetes/website/commits")
    response = httpx.Response(403, headers={"x-ratelimit-remaining": "0"}, request=request)
    with pytest.raises(SourceFetchError) as info:
        raise_for_github(response, "commits")
    assert info.value.retryable is True
    assert info.value.status == 403
    assert "DRIFTLINE_GITHUB_TOKEN" in str(info.value)


def test_not_found_is_not_retryable_and_success_passes():
    request = httpx.Request("GET", "https://raw.githubusercontent.com/kubernetes/website/x")
    with pytest.raises(SourceFetchError) as info:
        raise_for_github(httpx.Response(404, request=request), "raw")
    assert info.value.retryable is False
    raise_for_github(httpx.Response(200, request=request), "raw")


async def test_list_external_ids_returns_configured_paths():
    async with httpx.AsyncClient() as http:
        connector = KubernetesDocsConnector(http, paths=["b.md", "a.md"])
        assert await connector.list_external_ids() == ["a.md", "b.md"]
    assert DEFAULT_PATHS == (GUIDE,)


@pytest.mark.vcr
async def test_fetch_yields_one_version_per_release_branch(require_cassette):
    async with httpx.AsyncClient(timeout=180) as http:
        connector = KubernetesDocsConnector(http, branches=["release-1.31", "release-1.28"])
        docs = [d async for d in connector.fetch(GUIDE)]
    assert [d.version_key for d in docs] == ["release-1.28", "release-1.31"]
    assert docs[0].valid_from == datetime(2023, 8, 15, 17, 0, 3, tzinfo=UTC)
    assert docs[1].valid_from == datetime(2024, 8, 13, 13, 47, 21, tzinfo=UTC)
    for doc in docs:
        sha = doc.source_meta["commit_sha"]
        assert doc.title == "Deprecated API Migration Guide"
        assert doc.raw_uri == f"https://raw.githubusercontent.com/kubernetes/website/{sha}/{GUIDE}"
        assert "{{<" not in doc.content
    paths_128 = {s.path for s in docs[0].sections}
    paths_131 = {s.path for s in docs[1].sections}
    assert "Removed APIs by release > v1.32" in paths_131 - paths_128
    assert "Removed APIs by release > v1.29 > Flow control resources" in paths_128 & paths_131


@pytest.mark.vcr
async def test_fetch_since_skips_older_branches(require_cassette):
    async with httpx.AsyncClient(timeout=180) as http:
        connector = KubernetesDocsConnector(http, branches=["release-1.28", "release-1.31"])
        docs = [d async for d in connector.fetch(GUIDE, since="release-1.28")]
    assert [d.version_key for d in docs] == ["release-1.31"]
