"""Golden-set curation: candidate selection and validation against real seeded rows, and
the Claude proposer replayed from a recorded cassette.

Record the proposer cassette once with
`uv run --env-file <backend/.env> pytest ... --record-mode=once`; without it that test skips.
"""

import json
import os
from datetime import UTC, date, datetime

import pytest
from conftest_cassettes import scrub_response_headers
from dbseed import VersionSeed, seed_history, seed_source

from driftline.clock import ManualClock
from driftline.eval.curate import (
    CORPUS_KINDS,
    Draft,
    DraftBatch,
    changed_sections,
    drafts_to_cases,
    pick_as_of,
    propose_cases,
    stable_sections,
    validate_case,
    version_manifest,
    write_jsonl,
)
from driftline.eval.types import GoldenCase
from driftline.llm.adapters.anthropic import AnthropicAdapter
from driftline.llm.router import LLMRouter, Route
from driftline.obs.cost import CostLedger

API_KEY = os.environ.get("DRIFTLINE_ANTHROPIC_API_KEY", "replay-only")
TODAY = date(2026, 10, 25)
PATH = "content/en/docs/reference/using-api/deprecation-guide.md"
REMOVED = "Removed APIs by release > v1.29 > Flow control resources"
MIGRATE = "Migrate using kubectl-convert"

# Kubernetes deprecation-guide passages (kubernetes/website): the flow control section
# changes between versions (v1beta2 goes from "will no longer be served" to "is no longer
# served", and the migration target moves from v1beta3 to v1); kubectl-convert never does.
V1_FLOW = (
    "The flowcontrol.apiserver.k8s.io/v1beta2 API version of FlowSchema and "
    "PriorityLevelConfiguration will no longer be served in v1.29. Migrate manifests and "
    "API clients to use the flowcontrol.apiserver.k8s.io/v1beta3 API version, available "
    "since v1.26."
)
V2_FLOW = (
    "The flowcontrol.apiserver.k8s.io/v1beta2 API version of FlowSchema and "
    "PriorityLevelConfiguration is no longer served as of v1.29. Migrate manifests and API "
    "clients to use the flowcontrol.apiserver.k8s.io/v1 API version, available since v1.29. "
    "All existing persisted objects are accessible via the new API."
)
CONVERT = (
    "The kubectl convert plugin can be helpful to address migrating manifest files to "
    "different API versions. It is not installed by default, so it has to be installed "
    "separately before it can convert a manifest to a newer API version."
)
WINDOWS = [
    datetime(2023, 12, 13, tzinfo=UTC),
    datetime(2024, 12, 11, tzinfo=UTC),
    datetime(2025, 4, 23, tzinfo=UTC),
]


async def seed_k8s_doc(conn):
    """Three real-shaped versions: flow control changes v1 -> v2; kubectl-convert never."""
    _, source = await seed_source(conn, kind="git_docs")
    texts = [
        [(REMOVED, V1_FLOW), (MIGRATE, CONVERT)],
        [(REMOVED, V2_FLOW), (MIGRATE, CONVERT)],
        [(REMOVED, V2_FLOW), (MIGRATE, CONVERT)],
    ]
    keys = ["release-1.29", "release-1.32", "release-1.33"]
    doc, versions, _ = await seed_history(
        conn,
        source,
        external_id=PATH,
        title="Deprecated API Migration Guide",
        versions=[
            VersionSeed(valid_from=w, texts=t, version_key=k)
            for w, t, k in zip(WINDOWS, texts, keys, strict=True)
        ],
    )
    # seed_history leaves section_hashes empty; the curator diffs versions by them.
    for vid, ts in zip(versions, texts, strict=True):
        hashes = {path: f"h:{hash(text)}" for path, text in ts}
        await conn.execute(
            "UPDATE doc_versions SET section_hashes = $2::jsonb WHERE id = $1",
            vid,
            json.dumps(hashes),
        )
    return doc, versions


def case(versions, **overrides) -> GoldenCase:
    fields = {
        "id": "k8s-001",
        "corpus": "k8s",
        "question": "Which API version should FlowSchema manifests be migrated to?",
        "as_of": date(2024, 6, 1),
        "kind": "point_in_time",
        "expected_answer": "flowcontrol.apiserver.k8s.io/v1beta3; v1beta2 will stop being served.",
        "expected_version_ids": [versions[0]],
        "expected_quotes": ["will no longer be served in v1.29"],
        "trap": True,
    }
    fields.update(overrides)
    return GoldenCase(**fields)


def test_corpora_map_to_source_kinds():
    assert CORPUS_KINDS == {"pharma": "openfda", "k8s": "git_docs"}


def test_pick_as_of_keeps_the_whole_day_inside_the_window():
    start = datetime(2024, 1, 10, 15, 0, tzinfo=UTC)
    end = datetime(2024, 1, 20, tzinfo=UTC)
    day = pick_as_of(start, end, today=TODAY)
    assert day is not None
    assert datetime(day.year, day.month, day.day, tzinfo=UTC) >= start
    assert datetime(day.year, day.month, day.day, tzinfo=UTC).date() < end.date()
    # Less than one whole UTC day in the window: no safe as_of.
    assert pick_as_of(start, datetime(2024, 1, 11, 12, tzinfo=UTC), today=TODAY) is None
    # An open window ends today (nothing is known about the future).
    open_day = pick_as_of(datetime(2026, 10, 1, tzinfo=UTC), None, today=TODAY)
    assert open_day is not None and date(2026, 10, 1) <= open_day < TODAY


async def test_changed_and_stable_sections_come_from_section_hashes(fresh_pool):
    async with fresh_pool.acquire() as conn:
        _, versions = await seed_k8s_doc(conn)
    changes = await changed_sections(fresh_pool, "k8s")
    assert [(c.section_path, c.old.version_id, c.new.version_id) for c in changes] == [
        (REMOVED, versions[0], versions[1])
    ]
    assert "will no longer be served in v1.29." in changes[0].old_only
    assert changes[0].new_text.startswith("The flowcontrol")
    stable = await stable_sections(fresh_pool, "k8s")
    assert {(s.section_path, s.version.version_id) for s in stable} == {
        (MIGRATE, v) for v in versions
    }
    assert await changed_sections(fresh_pool, "pharma") == []  # another corpus


async def test_documents_with_fewer_than_three_versions_are_skipped(fresh_pool):
    async with fresh_pool.acquire() as conn:
        _, source = await seed_source(conn, kind="git_docs")
        await seed_history(
            conn,
            source,
            external_id="two-versions.md",
            title="Two",
            versions=[
                VersionSeed(valid_from=WINDOWS[0], texts=[("A", V1_FLOW)]),
                VersionSeed(valid_from=WINDOWS[1], texts=[("A", V2_FLOW)]),
            ],
        )
    assert await changed_sections(fresh_pool, "k8s") == []
    assert await stable_sections(fresh_pool, "k8s") == []


async def test_a_case_tied_to_a_real_version_quote_and_window_validates(fresh_pool):
    async with fresh_pool.acquire() as conn:
        _, versions = await seed_k8s_doc(conn)
    assert await validate_case(fresh_pool, case(versions)) == []
    # Near-exact quotes pass (curly quotes, case, a typo within the 0.9 ratio).
    near = case(
        versions,
        trap=False,  # the sentence is in every version
        expected_quotes=[
            (
                "Migrate manifests and API clients to use the "
                "flowcontrol.apiserver.k8s.io/v1beta3 API versoin"
            )
        ],
    )
    assert await validate_case(fresh_pool, near) == []


async def test_validation_rejects_missing_versions_quotes_and_windows(fresh_pool):
    async with fresh_pool.acquire() as conn:
        _, versions = await seed_k8s_doc(conn)
    from uuid import uuid4

    assert await validate_case(fresh_pool, case(versions, expected_version_ids=[uuid4()])) == [
        "version_missing"
    ]
    assert await validate_case(
        fresh_pool,
        case(versions, trap=False, expected_quotes=["is no longer served as of v1.29"]),
    ) == ["quote_not_found"]
    # 2024-12-11 starts version 2: the whole day is outside version 1's window.
    assert await validate_case(fresh_pool, case(versions, as_of=date(2024, 12, 11))) == [
        "as_of_outside_window"
    ]
    assert await validate_case(fresh_pool, case(versions, as_of=date(2023, 12, 12))) == [
        "as_of_outside_window"
    ]
    assert await validate_case(fresh_pool, case(versions, corpus="pharma")) == ["wrong_corpus"]


async def test_validation_rejects_traps_whose_answer_did_not_change(fresh_pool):
    async with fresh_pool.acquire() as conn:
        _, versions = await seed_k8s_doc(conn)
    unchanged = case(versions, expected_quotes=["The kubectl convert plugin can be helpful"])
    assert await validate_case(fresh_pool, unchanged) == ["trap_not_changed"]
    # The same quote is fine for a non-trap case.
    assert await validate_case(fresh_pool, unchanged.model_copy(update={"trap": False})) == []
    # A trap in the newest version has nothing it changed into.
    last = case(
        versions,
        as_of=date(2025, 6, 1),
        expected_version_ids=[versions[2]],
        expected_quotes=["All existing persisted objects are accessible via the new API."],
    )
    assert await validate_case(fresh_pool, last) == ["trap_not_changed"]
    # A reworded sentence is a change, even though a citation check would accept the
    # old wording as a near-exact quote of the new one.
    reworded = case(
        versions,
        expected_quotes=[
            (
                "The flowcontrol.apiserver.k8s.io/v1beta2 API version of FlowSchema and "
                "PriorityLevelConfiguration will no longer be served in v1.29."
            )
        ],
    )
    assert await validate_case(fresh_pool, reworded) == []


async def test_validation_rejects_questions_that_carry_their_own_date(fresh_pool):
    async with fresh_pool.acquire() as conn:
        _, versions = await seed_k8s_doc(conn)
    dated = case(versions, question="As of March 2024, which FlowSchema API should I use?")
    assert await validate_case(fresh_pool, dated) == ["question_has_time_hint"]
    release = case(versions, question="Which FlowSchema API does Kubernetes 1.29 serve?")
    assert await validate_case(fresh_pool, release) == ["question_has_time_hint"]


async def test_drafts_become_cases_tied_to_the_candidates_versions(fresh_pool):
    async with fresh_pool.acquire() as conn:
        _, versions = await seed_k8s_doc(conn)
    change = (await changed_sections(fresh_pool, "k8s"))[0]
    batch = DraftBatch(
        drafts=[
            Draft(
                item=1,
                usable=True,
                question="What happens to the v1beta2 FlowSchema API?",
                answer="It will stop being served in v1.29.",
                quote="  will no longer   be served in v1.29 ",
                answer_after="It is no longer served.",
            ),
            Draft(item=2, usable=False, question="", answer="", quote="", answer_after=""),
            Draft(item=9, usable=True, question="Q?", answer="A", quote="x" * 20, answer_after=""),
            Draft(
                item=3,
                usable=True,
                question="Which API replaces v1beta2 FlowSchema?",
                answer="flowcontrol.apiserver.k8s.io/v1",
                quote="Migrate manifests and API clients",
                answer_after="Flowcontrol.apiserver.k8s.io/v1 ",  # the same answer: no trap
            ),
        ]
    )
    cases, rejected = drafts_to_cases(batch, [change, change, change], corpus="k8s", today=TODAY)
    assert rejected == {"declined": 1, "unknown_item": 1, "trap_answer_unchanged": 1}
    [only] = cases
    assert only.trap and only.kind == "point_in_time"
    assert only.expected_version_ids == [versions[0]]
    assert only.expected_quotes == ["will no longer be served in v1.29"]  # source's words
    assert await validate_case(fresh_pool, only) == []


def test_write_jsonl_renumbers_and_round_trips(tmp_path):
    from uuid import uuid4

    cases = [
        case([uuid4()], id="draft-a"),
        case([uuid4()], id="draft-b", trap=False),
    ]
    out = tmp_path / "golden" / "k8s.jsonl"
    write_jsonl(cases, out)
    lines = out.read_text().splitlines()
    loaded = [GoldenCase.model_validate_json(line) for line in lines]
    assert [c.id for c in loaded] == ["k8s-001", "k8s-002"]
    assert [c.trap for c in loaded] == [True, False]


@pytest.fixture(scope="module")
def vcr_config():
    return {
        "filter_headers": ["x-api-key", "authorization"],
        "before_record_response": scrub_response_headers,
        "match_on": ["method", "scheme", "host", "path"],
    }


@pytest.mark.vcr
async def test_claude_proposes_trap_and_stable_cases_that_validate(require_cassette, fresh_pool):
    async with fresh_pool.acquire() as conn:
        _, versions = await seed_k8s_doc(conn)
    router = LLMRouter(
        providers={"anthropic": AnthropicAdapter(API_KEY)},
        chains={"extract": [Route("anthropic", "claude-haiku-5-5")]},
        clock=ManualClock(),
    )
    ledger = CostLedger(fresh_pool)
    result = await propose_cases(
        fresh_pool, router, "k8s", n=3, today=TODAY, ledger=ledger, batch_size=8
    )
    assert result.calls == 1  # one batched prompt
    assert result.cases, result.rejected
    valid = [c for c in result.cases if await validate_case(fresh_pool, c) == []]
    assert any(c.trap for c in valid) and any(not c.trap for c in valid)
    for c in result.cases:
        assert set(c.expected_version_ids) <= set(versions)
    trap = next(c for c in valid if c.trap)
    assert trap.expected_version_ids == [versions[0]]
    async with fresh_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT count(*) AS n, sum(cost_usd) AS cost FROM llm_calls WHERE node = 'curate'"
        )
    assert row["n"] == 1 and row["cost"] > 0


async def test_version_manifest_identifies_each_expected_version_by_source(fresh_pool):
    async with fresh_pool.acquire() as conn:
        _, versions = await seed_k8s_doc(conn)
    rows = await version_manifest(fresh_pool, [case(versions), case(versions, id="k8s-002")])
    assert [r["version_id"] for r in rows] == [str(versions[0])]  # deduplicated
    [row] = rows
    assert row["kind"] == "git_docs" and row["external_id"] == PATH
    assert row["version_key"] == "release-1.29" and row["version_no"] == 1
    assert row["valid_from"] == "2023-12-13T00:00:00+00:00"
    assert row["valid_to"] == "2024-12-11T00:00:00+00:00"
    assert row["content_hash"]
