"""The Claude Code Skill (`.claude/skills/driftline/SKILL.md`) and the MCP guide
(`docs/mcp.md`) against the real server, so the docs cannot drift from the code.

- Every tool the docs call exists in the real tool list of `build_mcp`, every real tool is
  documented, and the guide's parameter tables match the real input schemas.
- The documented setup runs end to end: the guide's SQL creates the tenant key, and the
  real MCP SDK client connects with exactly the URL path and header of the documented
  `claude mcp add` command, then follows the skill's flow (list_sources, ask with
  `as_of`, get_timeline, diff_versions) against the gateway on a real socket, with a real
  agent worker. No mocks, no stubs.
"""

import re
import shlex
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx2
import pytest
import yaml
from dbseed import VersionSeed, embed_all, seed_history, seed_source
from livesrv import serve
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from starlette.datastructures import State
from test_mcp_server import STEP_TIMEOUT_S, call, running_worker

from driftline.config import Settings
from driftline.gateway.app import create_app
from driftline.mcp import build_mcp

REPO = Path(__file__).resolve().parents[3]
SKILL_MD = REPO / ".claude" / "skills" / "driftline" / "SKILL.md"
MCP_MD = REPO / "docs" / "mcp.md"
README = REPO / "README.md"
CONNECT = (
    'claude mcp add --transport http driftline http://localhost:8010/mcp --header "Authorization: '
    'Bearer $DRIFTLINE_KEY"'
)
KEY_PLACEHOLDER = "YOUR_KEY"
DEMO_KEY = "dl_test_demo_key"

# Fenced blocks in these languages are shell, SQL and the like: their `f(...)` are not tools.
NON_TOOL_FENCES = {"bash", "sh", "shell", "sql", "python", "json", "yaml", "console"}
FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.MULTILINE | re.DOTALL)
INLINE_CODE = re.compile(r"`([^`\n]+)`")
CALL = re.compile(r"(?<![\w.])([a-z][a-z0-9_]*)\(")
TOOL_HEADING = re.compile(r"^### `([a-z][a-z0-9_]*)`\s*$", re.MULTILINE)


async def real_tools() -> dict:
    return {t.name: t for t in await build_mcp(State()).list_tools()}


def tool_calls(markdown: str) -> set[str]:
    """Names called as `name(...)` in inline code and in untagged or `text` fences."""
    code: list[str] = []

    def keep(m: re.Match) -> str:
        if m.group(1) not in NON_TOOL_FENCES:
            code.append(m.group(2))
        return ""

    prose = FENCE.sub(keep, markdown)
    code += INLINE_CODE.findall(prose)
    return {name for snippet in code for name in CALL.findall(snippet)}


def frontmatter(text: str) -> dict:
    assert text.startswith("---\n"), "SKILL.md must start with the frontmatter's opening ---"
    block, sep, _ = text[4:].partition("\n---\n")
    assert sep, "SKILL.md frontmatter has no closing ---"
    meta = yaml.safe_load(block)
    assert isinstance(meta, dict), meta
    return meta


def param_table(markdown: str, tool: str) -> dict[str, bool]:
    """The guide's parameter table for `tool`: parameter -> required."""
    section = markdown.split(f"### `{tool}`", 1)[1]
    section = re.split(r"^#{2,3} ", section, maxsplit=1, flags=re.MULTILINE)[0]
    rows = re.findall(r"^\| `([a-z_]+)` \| [^|]+ \| (yes|no) \|", section, re.MULTILINE)
    return {name: required == "yes" for name, required in rows}


def documented_connect(markdown: str) -> str:
    lines = [ln.strip() for ln in markdown.splitlines() if ln.strip().startswith("claude mcp add")]
    assert lines, "no `claude mcp add` command"
    return lines[0]


# --- the docs match the real tools ---------------------------------------------------------


@pytest.mark.parametrize("doc", [SKILL_MD, MCP_MD], ids=["SKILL.md", "mcp.md"])
async def test_every_tool_the_docs_call_is_a_real_tool(doc):
    tools = await real_tools()
    called = tool_calls(doc.read_text())
    assert called, f"{doc.name} calls no tools"
    assert called <= tools.keys(), f"{doc.name} calls unknown tools: {called - tools.keys()}"


async def test_every_real_tool_is_documented_in_both_docs():
    tools = await real_tools()
    assert tools.keys() == {"ask", "list_sources", "diff_versions", "get_timeline", "watch_answer"}
    assert tools.keys() <= tool_calls(SKILL_MD.read_text())
    guide = MCP_MD.read_text()
    assert set(TOOL_HEADING.findall(guide)) == tools.keys()


async def test_the_guides_parameter_tables_match_the_real_schemas():
    guide = MCP_MD.read_text()
    for name, tool in (await real_tools()).items():
        schema = tool.input_schema
        expected = {p: p in schema.get("required", []) for p in schema.get("properties", {})}
        assert param_table(guide, name) == expected, name


def test_skill_frontmatter_parses_with_the_required_fields():
    meta = frontmatter(SKILL_MD.read_text())
    assert meta["name"] == "driftline"
    description = meta["description"]
    assert isinstance(description, str) and description.strip()
    # Claude Code truncates description + when_to_use at 1,536 characters in its listing.
    assert len(description) + len(meta.get("when_to_use", "")) <= 1536
    assert "as_of" in description or "version" in description


def test_docs_give_the_exact_connect_command_and_readme_links_the_guide():
    assert documented_connect(SKILL_MD.read_text()) == CONNECT
    assert documented_connect(MCP_MD.read_text()) == CONNECT
    readme = README.read_text()
    assert "## Use from Claude Code / Cursor" in readme
    assert "(docs/mcp.md)" in readme


def test_skill_teaches_as_of_and_the_non_answer_results():
    skill = SKILL_MD.read_text()
    for needle in ("as_of", "insufficient_evidence", '"running"', "job_id", "valid_from"):
        assert needle in skill, needle
    # At least one historical example passes as_of explicitly.
    assert re.search(r"ask\(question=.*as_of=", skill)


# --- the documented flow works against a live gateway --------------------------------------

OLD = "Check ALT every 12 weeks during therapy."
NEW = "Check ALT monthly during therapy."


def at(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=UTC)


@pytest.fixture
async def demo(fresh_conn, embedder_url):
    """Tenant `demo` as the ingest CLI leaves it (no usable key), with one label in two
    versions, then the guide's SQL run verbatim to give it a key."""
    _, source = await seed_source(fresh_conn, kind="upload", tenant="demo", api_key=None)
    doc, versions, _ = await seed_history(
        fresh_conn,
        source,
        external_id="liver.md",
        title="Liver safety",
        versions=[
            VersionSeed(at(2023), [("Monitoring", OLD)], "release-1.27"),
            VersionSeed(at(2025), [("Monitoring", NEW)], "release-1.28"),
        ],
    )
    await embed_all(fresh_conn, embedder_url)
    sql = [b for lang, b in FENCE.findall(MCP_MD.read_text()) if lang == "sql"]
    assert len(sql) == 1 and KEY_PLACEHOLDER in sql[0], sql
    await fresh_conn.execute(sql[0].replace(KEY_PLACEHOLDER, DEMO_KEY))
    return {"source": source, "doc": doc, "old": versions[0], "new": versions[1]}


@asynccontextmanager
async def client_from_docs(base: str, key: str):
    """The real SDK client, configured from the documented `claude mcp add` command alone:
    its URL path and its header (with $DRIFTLINE_KEY expanded, as the shell would)."""
    argv = shlex.split(documented_connect(SKILL_MD.read_text()).replace("$DRIFTLINE_KEY", key))
    assert argv[:5] == ["claude", "mcp", "add", "--transport", "http"], argv
    name, url = argv[5], argv[6]
    header = argv[argv.index("--header") + 1]
    assert name == "driftline"
    field, _, value = header.partition(": ")
    path = urlsplit(url).path
    async with (
        httpx2.AsyncClient(
            headers={field: value}, timeout=httpx2.Timeout(30.0, read=STEP_TIMEOUT_S)
        ) as http_client,
        Client(streamable_http_client(f"{base}{path}", http_client=http_client)) as c,
    ):
        yield c


async def test_the_documented_setup_and_skill_flow_work_end_to_end(
    fresh_dsn, fresh_pool, redis_url, redis_client, checkpointer, embedder_url, demo
):
    settings = Settings(_env_file=None, database_url=fresh_dsn, redis_url=redis_url)
    transcript: list[str] = []
    async with (
        serve(create_app(settings)) as base,
        running_worker(fresh_pool, redis_client, checkpointer, embedder_url),
        client_from_docs(base, DEMO_KEY) as client,
    ):
        tools = sorted(t.name for t in (await client.list_tools()).tools)
        transcript.append(f"list_tools -> {tools}")

        sources = (await call(client, "list_sources"))["sources"]
        assert [s["id"] for s in sources] == [str(demo["source"])]
        transcript.append(f"list_sources -> {[(s['kind'], s['documents']) for s in sources]}")

        question = "How often should ALT be checked?"
        then = await call(client, "ask", {"question": question, "as_of": "2023", "timeout_s": 90})
        assert then["status"] == "answered", then
        assert "12 weeks" in then["answer"]
        cite = then["citations"][0]
        assert cite["version_id"] == str(demo["old"])
        assert (cite["title"], cite["version_no"]) == ("Liver safety", 1)
        assert datetime.fromisoformat(cite["valid_from"]) == at(2023)
        assert datetime.fromisoformat(cite["valid_to"]) == at(2025)
        transcript.append(
            f"ask(as_of='2023') -> {then['status']}: {then['answer']!r}; cites "
            f"{cite['title']} v{cite['version_no']} [{cite['valid_from']}, {cite['valid_to']})"
        )

        now = await call(client, "ask", {"question": question, "timeout_s": 90})
        assert now["status"] == "answered" and "monthly" in now["answer"], now
        assert {c["version_id"] for c in now["citations"]} == {str(demo["new"])}
        transcript.append(f"ask() -> {now['status']}: {now['answer']!r}")

        timeline = await call(client, "get_timeline", {"document_id": cite["document_id"]})
        windows = [(v["version_no"], v["valid_from"], v["valid_to"]) for v in timeline["versions"]]
        assert [w[0] for w in windows] == [1, 2] and windows[1][2] is None
        transcript.append(f"get_timeline -> {windows}")

        diff = await call(client, "diff_versions", {"document_id": cite["document_id"]})
        assert (diff["from_version"], diff["to_version"]) == (1, 2)
        assert f"-{OLD}" in diff["diff"] and f"+{NEW}" in diff["diff"]
        transcript.append(f"diff_versions -> v1..v2 sections {diff['sections']}")

        watched = await call(client, "watch_answer", {"answer_id": now["answer_id"]})
        assert watched == {"answer_id": now["answer_id"], "watched": True}
        transcript.append(f"watch_answer -> {watched}")
    print("\nMCP transcript (documented flow):\n  " + "\n  ".join(transcript))
