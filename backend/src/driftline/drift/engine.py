"""Drift engine (spec section 7): when a document gets a new version, re-check every
watched answer that still cites an older version of it.

Per claim, the cited section is compared between the cited (old) version and the
document's LATEST version, not the version named in the event, so a worker that falls
behind (v1 -> v2 -> v3 before it runs) evaluates against v3 once, never against v2:
- unchanged section: re-point the citation to the same chunk in the latest version
  (`still_valid`, no alert);
- changed section: re-run the citation verifier against the latest section; supported
  re-points (`still_valid`), unsupported is `changed` with a before/after diff;
- removed section: `broken`, and the answer goes to review (`regenerate_hook`).

Models are called before any write. All writes for one event then happen in one
transaction, under a per-document advisory lock, and are keyed on the
`drift_events (answer_id, new_version_id, claim_idx)` unique index: a redelivered or
concurrently delivered event inserts nothing, so it re-points nothing and publishes no
second alert.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg

from driftline.agents.events import DriftVerdict as Verdict
from driftline.agents.guardrails import verify_claim
from driftline.agents.prompts import build_judge_request
from driftline.agents.schemas import Citation, DraftCitation, DraftClaim, JudgeOutput
from driftline.clock import Clock
from driftline.config import Settings
from driftline.drift.diff import DIFF_CAP_BYTES, section_status, section_text_diff
from driftline.llm.router import LLMRouter
from driftline.retrieval.types import Evidence

DRIFT_ALERT = "drift.alert"
# Called inside the event's transaction for every answer that got a new `broken` verdict.
RegenerateHook = Callable[[asyncpg.Connection, UUID, UUID, dict[str, Any]], Awaitable[None]]

_SEVERITY: dict[str, int] = {"still_valid": 0, "changed": 1, "broken": 2}


@dataclass(frozen=True)
class DriftVerdict:
    answer_id: UUID
    claim_idx: int
    verdict: Verdict
    old_version_id: UUID
    new_version_id: UUID
    before: str | None  # cited section text in the old version
    after: str | None  # the same section in the new version; None when it is gone
    diff: str | None = None  # unified diff of before -> after, capped at 4 KB
    section_path: str = ""
    drift_event_id: UUID | None = None


@dataclass(frozen=True)
class _Chunk:
    id: UUID
    ord: int
    section_path: str
    text: str
    tags: list[str]


@dataclass
class _ClaimEval:
    answer_id: UUID
    claim_idx: int
    verdict: Verdict
    old_version_id: UUID
    section_path: str
    before: str | None
    after: str | None
    diff: str | None
    repoints: dict[UUID, Citation] = field(default_factory=dict)  # old chunk -> new citation


def _cap(text: str, limit: int = DIFF_CAP_BYTES) -> str:
    return text.encode("utf-8")[:limit].decode("utf-8", errors="ignore")


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else (value or {})


async def queue_broken_answer(
    conn: asyncpg.Connection, tenant_id: UUID, answer_id: UUID, payload: dict[str, Any]
) -> None:
    """Default `regenerate_hook`: open one review item per broken answer (idempotent
    through the open-item partial unique index). The 0001 CHECK on review_items.kind
    only allows 'answer' and 'relation', so the reason travels in the payload."""
    await conn.execute(
        "INSERT INTO review_items (kind, ref_id, tenant_id, payload) "
        "VALUES ('answer', $1, $2, $3::jsonb) "
        "ON CONFLICT (kind, ref_id) WHERE status = 'open' DO NOTHING",
        answer_id,
        tenant_id,
        json.dumps({"reason": "broken", **payload}),
    )


class DriftEngine:
    def __init__(
        self,
        pool: asyncpg.Pool,
        router: LLMRouter,
        clock: Clock,
        settings: Settings,
        *,
        regenerate_hook: RegenerateHook | None = None,
    ) -> None:
        self._pool = pool
        self._router = router
        self._clock = clock
        self._settings = settings
        self._regenerate_hook = regenerate_hook or queue_broken_answer

    async def _judge(self, claim: str, quote: str) -> bool:
        parsed, _ = await self._router.structured(
            "judge", build_judge_request(claim, quote), JudgeOutput
        )
        return parsed.entailed

    async def handle_version_created(self, event: dict) -> list[DriftVerdict]:
        """Returns the verdicts this call recorded; a redelivered event returns []."""
        if not self._settings.drift_enabled:
            return []
        document_id = UUID(str(event["document_id"]))
        async with self._pool.acquire() as conn:
            doc = await conn.fetchrow(
                "SELECT d.title, d.external_id, s.tenant_id FROM documents d "
                "JOIN sources s ON s.id = d.source_id WHERE d.id = $1",
                document_id,
            )
            latest = await conn.fetchrow(
                "SELECT id, version_no, valid_from, valid_to, section_hashes FROM doc_versions "
                "WHERE document_id = $1 ORDER BY version_no DESC LIMIT 1",
                document_id,
            )
            if doc is None or latest is None:
                return []
            evals = await self._evaluate(conn, document_id, doc, latest)
        if not evals:
            return []
        return await self._record(document_id, doc, latest["id"], evals)

    # --- phase 1: read and judge, no transaction held ---------------------------------

    async def _evaluate(
        self, conn: asyncpg.Connection, document_id: UUID, doc, latest
    ) -> list[_ClaimEval]:
        # Watched answers of this document's tenant citing any non-latest version of it.
        rows = await conn.fetch(
            "SELECT ac.answer_id, ac.claim_idx, ac.chunk_id, c.section_path, c.ord, "
            "c.text, c.version_id, v.section_hashes, a.body "
            "FROM answer_citations ac "
            "JOIN answers a ON a.id = ac.answer_id "
            "JOIN chunks c ON c.id = ac.chunk_id "
            "JOIN doc_versions v ON v.id = c.version_id "
            "WHERE v.document_id = $1 AND v.id <> $2 AND a.watched AND a.tenant_id = $3 "
            "ORDER BY ac.answer_id, ac.claim_idx, c.ord",
            document_id,
            latest["id"],
            doc["tenant_id"],
        )
        if not rows:
            return []
        new_chunks = [
            _Chunk(r["id"], r["ord"], r["section_path"], r["text"], list(r["tags"]))
            for r in await conn.fetch(
                "SELECT id, ord, section_path, text, tags FROM chunks "
                "WHERE version_id = $1 ORDER BY ord",
                latest["id"],
            )
        ]
        new_hashes = _json(latest["section_hashes"])
        old_sections: dict[tuple[UUID, str], list[_Chunk]] = {}

        async def old_section(version_id: UUID, path: str) -> list[_Chunk]:
            key = (version_id, path)
            if key not in old_sections:
                old_sections[key] = [
                    _Chunk(r["id"], r["ord"], path, r["text"], [])
                    for r in await conn.fetch(
                        "SELECT id, ord, text FROM chunks "
                        "WHERE version_id = $1 AND section_path = $2 ORDER BY ord",
                        version_id,
                        path,
                    )
                ]
            return old_sections[key]

        evals: dict[tuple[UUID, int], _ClaimEval] = {}
        for row in rows:
            path = row["section_path"]
            new_section = [c for c in new_chunks if c.section_path == path]
            old_chunks = await old_section(row["version_id"], path)
            status = section_status(_json(row["section_hashes"]), new_hashes, path)
            if status == "removed" and new_section:
                status = "changed"  # hashes missing (pre-P2 rows): let the verifier decide
            elif not new_section:
                status = "removed"
            claim_text, quote = _claim_and_quote(_json(row["body"]), row["claim_idx"], row)
            before = "\n".join(c.text for c in old_chunks) or row["text"]
            after = "\n".join(c.text for c in new_section) if new_section else None
            verdict: Verdict
            target: Citation | None = None
            if status == "unchanged":
                verdict = "still_valid"
                chunk = _same_chunk(row["chunk_id"], row["text"], old_chunks, new_section)
                target = Citation(chunk_id=chunk.id, version_id=latest["id"], quote=quote)
            elif status == "changed":
                check = await verify_claim(
                    DraftClaim(
                        text=claim_text,
                        citations=[
                            DraftCitation(
                                chunk_id=str(c.id), version_id=str(latest["id"]), quote=quote
                            )
                            for c in new_section
                        ],
                    ),
                    {str(c.id): _evidence(c, document_id, doc, latest) for c in new_section},
                    judge=self._judge,
                )
                if check.supported:
                    verdict, target = "still_valid", check.citations[0]
                else:
                    verdict = "changed"
            else:
                verdict = "broken"
            key = (row["answer_id"], row["claim_idx"])
            current = evals.get(key)
            if current is None or _SEVERITY[verdict] > _SEVERITY[current.verdict]:
                repoints = current.repoints if current else {}
                current = _ClaimEval(
                    answer_id=row["answer_id"],
                    claim_idx=row["claim_idx"],
                    verdict=verdict,
                    old_version_id=row["version_id"],
                    section_path=path,
                    before=_cap(before),
                    after=_cap(after) if after is not None else None,
                    diff=section_text_diff(before, after) if verdict == "changed" else None,
                    repoints=repoints,
                )
                evals[key] = current
            if target is not None:
                current.repoints[row["chunk_id"]] = target
        return list(evals.values())

    # --- phase 2: one transaction for every write of this event -----------------------

    async def _record(
        self, document_id: UUID, doc, new_version_id: UUID, evals: list[_ClaimEval]
    ) -> list[DriftVerdict]:
        tenant_id = doc["tenant_id"]
        now = datetime.fromtimestamp(self._clock.now(), UTC)
        recorded: list[DriftVerdict] = []
        body_updates: dict[UUID, dict[tuple[int, UUID], Citation]] = {}
        broken: dict[UUID, list[int]] = {}
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1::text, 0))", str(document_id)
            )
            for ev in evals:
                detail = {
                    "section_path": ev.section_path,
                    "before": ev.before,
                    "after": ev.after,
                    "diff": ev.diff,
                }
                drift_id = await conn.fetchval(
                    "INSERT INTO drift_events (answer_id, tenant_id, claim_idx, old_version_id, "
                    "new_version_id, verdict, detail, created_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8) "
                    "ON CONFLICT (answer_id, new_version_id, claim_idx) DO NOTHING RETURNING id",
                    ev.answer_id,
                    tenant_id,
                    ev.claim_idx,
                    ev.old_version_id,
                    new_version_id,
                    ev.verdict,
                    json.dumps(detail),
                    now,
                )
                if drift_id is None:
                    continue  # already recorded by an earlier or concurrent delivery
                for old_chunk, target in ev.repoints.items():
                    await conn.execute(
                        "DELETE FROM answer_citations "
                        "WHERE answer_id = $1 AND claim_idx = $2 AND chunk_id = $3",
                        ev.answer_id,
                        ev.claim_idx,
                        old_chunk,
                    )
                    await conn.execute(
                        "INSERT INTO answer_citations (answer_id, claim_idx, chunk_id) "
                        "VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                        ev.answer_id,
                        ev.claim_idx,
                        target.chunk_id,
                    )
                    body_updates.setdefault(ev.answer_id, {})[(ev.claim_idx, old_chunk)] = target
                if ev.verdict != "still_valid":  # still_valid re-points silently
                    await conn.execute(
                        "INSERT INTO outbox (topic, payload) VALUES ($1, $2::jsonb)",
                        DRIFT_ALERT,
                        json.dumps(
                            {
                                "type": "alert",
                                "tenant_id": str(tenant_id),
                                "drift_event_id": str(drift_id),
                                "answer_id": str(ev.answer_id),
                                "verdict": ev.verdict,
                                "document_title": doc["title"],
                                "old_version_id": str(ev.old_version_id),
                                "new_version_id": str(new_version_id),
                                "before": ev.before,
                                "after": ev.after,
                                "t": now.isoformat(),
                            }
                        ),
                    )
                if ev.verdict == "broken":
                    broken.setdefault(ev.answer_id, []).append(ev.claim_idx)
                recorded.append(
                    DriftVerdict(
                        answer_id=ev.answer_id,
                        claim_idx=ev.claim_idx,
                        verdict=ev.verdict,
                        old_version_id=ev.old_version_id,
                        new_version_id=new_version_id,
                        before=ev.before,
                        after=ev.after,
                        diff=ev.diff,
                        section_path=ev.section_path,
                        drift_event_id=drift_id,
                    )
                )
            for answer_id, changes in body_updates.items():
                await _repoint_body(conn, answer_id, changes)
            for answer_id, claims in broken.items():
                await self._regenerate_hook(
                    conn,
                    tenant_id,
                    answer_id,
                    {
                        "document_id": str(document_id),
                        "new_version_id": str(new_version_id),
                        "claims": claims,
                    },
                )
        return recorded


def _claim_and_quote(body: dict, claim_idx: int, row) -> tuple[str, str]:
    """The claim's text and the quote it used for the cited chunk, from the answer body."""
    claim = next((c for c in body.get("claims", []) if c.get("idx") == claim_idx), None)
    if claim is None:
        return row["text"], row["text"]
    quote = next(
        (c["quote"] for c in claim.get("citations", []) if c["chunk_id"] == str(row["chunk_id"])),
        claim["text"],
    )
    return claim["text"], quote


def _same_chunk(
    old_id: UUID, old_text: str, old_section: list[_Chunk], new_section: list[_Chunk]
) -> _Chunk:
    """The new-version chunk matching the cited one in an unchanged section: same text,
    else the same position within the section, else the section's first chunk."""
    for c in new_section:
        if c.text == old_text:
            return c
    pos = next((n for n, c in enumerate(old_section) if c.id == old_id), 0)
    return new_section[pos] if pos < len(new_section) else new_section[0]


def _evidence(chunk: _Chunk, document_id: UUID, doc, latest) -> Evidence:
    return Evidence(
        chunk_id=chunk.id,
        version_id=latest["id"],
        document_id=document_id,
        external_id=doc["external_id"],
        title=doc["title"],
        section_path=chunk.section_path,
        text=chunk.text,
        tags=chunk.tags,
        version_no=latest["version_no"],
        valid_from=latest["valid_from"],
        valid_to=latest["valid_to"],
        retrieved_as_of=latest["valid_from"],
    )


async def _repoint_body(
    conn: asyncpg.Connection, answer_id: UUID, changes: dict[tuple[int, UUID], Citation]
) -> None:
    """Rewrite the re-pointed citations inside the stored AnswerSchema body."""
    body = _json(
        await conn.fetchval("SELECT body FROM answers WHERE id = $1 FOR UPDATE", answer_id)
    )
    by_chunk = {str(old): new for (_, old), new in changes.items()}

    def swap(cites: list[dict], claim_idx: int | None) -> list[dict]:
        out = []
        for c in cites:
            new = by_chunk.get(c.get("chunk_id", ""))
            if new is not None and (
                claim_idx is None or (claim_idx, UUID(c["chunk_id"])) in changes
            ):
                out.append(new.model_dump(mode="json"))
            else:
                out.append(c)
        return out

    for claim in body.get("claims", []):
        claim["citations"] = swap(claim.get("citations", []), claim.get("idx"))
    body["citations"] = swap(body.get("citations", []), None)
    await conn.execute(
        "UPDATE answers SET body = $2::jsonb WHERE id = $1", answer_id, json.dumps(body)
    )
