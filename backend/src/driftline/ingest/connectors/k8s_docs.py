"""Kubernetes docs from `kubernetes/website`: one version per release branch.

A version is the file as of the newest commit that touched it on `release-1.N`
(GitHub commits API), read from raw.githubusercontent.com pinned to that commit.
`valid_from` is the publish date of the matching `v1.N.0` release of
kubernetes/kubernetes, so "as of v1.29" means "from the day 1.29 shipped".
"""

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx

from driftline.ingest.markdown import parse_markdown
from driftline.ingest.types import RawDocument, SourceFetchError, render_content

GITHUB_API = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"
DEFAULT_BRANCHES = ("release-1.28", "release-1.29", "release-1.30", "release-1.31")
DEFAULT_PATHS = ("content/en/docs/reference/using-api/deprecation-guide.md",)
_BRANCH = re.compile(r"^release-(\d+)\.(\d+)$")
_TOOLTIP = re.compile(r'\{\{<\s*glossary_tooltip\b[^>]*?\btext="([^"]*)"[^>]*>\}\}')
_SHORTCODE = re.compile(r"\{\{[<%].*?[%>]\}\}", re.DOTALL)


def branch_minor(branch: str) -> tuple[int, int]:
    match = _BRANCH.match(branch)
    if match is None:
        raise ValueError(f"not a release branch: {branch!r}")
    return int(match.group(1)), int(match.group(2))


def clean_hugo(text: str) -> str:
    """Keep glossary tooltip text and drop every other Hugo shortcode tag."""
    return _SHORTCODE.sub("", _TOOLTIP.sub(r"\1", text))


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def raise_for_github(response: httpx.Response, what: str) -> None:
    """Map GitHub failures to SourceFetchError; rate limiting is retryable."""
    status = response.status_code
    if status < 400:
        return
    limited = status == 429 or (
        status == 403 and response.headers.get("x-ratelimit-remaining") == "0"
    )
    detail = " (rate limited; set DRIFTLINE_GITHUB_TOKEN)" if limited else ""
    raise SourceFetchError(
        f"{what}: HTTP {status}{detail}", retryable=limited or status >= 500, status=status
    )


class KubernetesDocsConnector:
    kind = "git_docs"

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        branches: tuple[str, ...] | list[str] = DEFAULT_BRANCHES,
        paths: tuple[str, ...] | list[str] = DEFAULT_PATHS,
        repo: str = "kubernetes/website",
        release_repo: str = "kubernetes/kubernetes",
        github_token: str | None = None,
        api_url: str = GITHUB_API,
        raw_url: str = GITHUB_RAW,
    ) -> None:
        self._http = http
        self._branches = sorted(branches, key=branch_minor)
        self._paths = list(paths)
        self._repo = repo
        self._release_repo = release_repo
        self._api = api_url.rstrip("/")
        self._raw = raw_url.rstrip("/")
        self._headers = {"Accept": "application/vnd.github+json"}
        if github_token:
            self._headers["Authorization"] = f"Bearer {github_token}"
        self._release_dates: dict[str, datetime | None] = {}

    async def list_external_ids(self) -> list[str]:
        return sorted(self._paths)

    async def latest_commit(self, branch: str, path: str) -> tuple[str, datetime] | None:
        response = await self._http.get(
            f"{self._api}/repos/{self._repo}/commits",
            params={"sha": branch, "path": path, "per_page": 1},
            headers=self._headers,
        )
        raise_for_github(response, f"commits {branch}:{path}")
        commits = response.json()
        if not commits:
            return None  # the file does not exist on this branch
        return commits[0]["sha"], _parse_ts(commits[0]["commit"]["committer"]["date"])

    async def release_date(self, branch: str) -> datetime | None:
        if branch not in self._release_dates:
            major, minor = branch_minor(branch)
            response = await self._http.get(
                f"{self._api}/repos/{self._release_repo}/releases/tags/v{major}.{minor}.0",
                headers=self._headers,
            )
            if response.status_code == 404:
                self._release_dates[branch] = None  # branch cut, release not published yet
            else:
                raise_for_github(response, f"release v{major}.{minor}.0")
                self._release_dates[branch] = _parse_ts(response.json()["published_at"])
        return self._release_dates[branch]

    async def fetch(
        self, external_id: str, *, since: str | None = None
    ) -> AsyncIterator[RawDocument]:
        """One RawDocument per configured branch newer than `since`, oldest first."""
        floor = branch_minor(since) if since else (0, 0)
        for branch in self._branches:
            if branch_minor(branch) <= floor:
                continue
            commit = await self.latest_commit(branch, external_id)
            if commit is None:
                continue
            sha, committed_at = commit
            raw_uri = f"{self._raw}/{self._repo}/{sha}/{external_id}"
            response = await self._http.get(raw_uri)
            raise_for_github(response, f"raw {sha}:{external_id}")
            doc = parse_markdown(clean_hugo(response.text))
            released = await self.release_date(branch)
            yield RawDocument(
                external_id=external_id,
                title=doc.title or external_id.rsplit("/", 1)[-1],
                version_key=branch,
                valid_from=released or committed_at,
                content=render_content(doc.sections),
                sections=doc.sections,
                raw_uri=raw_uri,
                source_meta={
                    "repo": self._repo,
                    "branch": branch,
                    "commit_sha": sha,
                    "commit_date": committed_at.isoformat(),
                    "release_date": released.isoformat() if released else None,
                },
            )
