"""The human review queue (spec section 5): low-confidence and broken answers, and the
supersession relations ingestion was unsure about.

- `open` is idempotent: the partial unique index allows one OPEN item per (kind, ref).
- `resolve` happens exactly once. The item row is locked (`FOR UPDATE`) and must still
  be open, so a second or concurrent call gets `AlreadyResolved` (HTTP 409); every
  effect of the resolution commits in the same transaction as the status change.
- Effects, by kind:
  - `relation`: approve applies the relation (edit: with the corrected `kind`), reject
    rejects it. Applying it also queues a `cache.invalidate` of every version of the
    replaced document, so the semantic cache stops serving answers that cite it. Items
    queued for a malformed extraction reference a version, not a relation, and are only
    marked resolved.
  - `broken_answer` (and legacy `answer` rows from the P4 drift hook): approve or edit
    queues an ask that regenerates the answer through `run_ask`; reject does nothing.
  - `low_confidence_answer` (ref = the paused ask's job id): any action queues the
    reviewer's decision for the paused graph thread, which the agent worker resumes.
  - any `edit` also records an `eval_cases` row.
- Follow-ups go through the transactional outbox, written in the resolve's transaction
  (topics `ask.resume` / `ask.regenerate` -> stream `agent`, and `cache.invalidate`).
  Only the one successful resolution ever writes them, and a failed publish is retried
  by the relay instead of leaving a paused ask stranded. Delivery is at-least-once: the
  agent worker resumes a given decision only once (see `AgentWorker.handle_ask`).
"""

import builtins
import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import asyncpg
from pydantic import BaseModel

from driftline.agents.schemas import AskJob, ReviewAction, ReviewDecision
from driftline.ingest.outbox import (
    ASK_REGENERATE_TOPIC,
    ASK_RESUME_TOPIC,
    CACHE_INVALIDATE_TOPIC,
)

ReviewKind = Literal["relation", "broken_answer", "low_confidence_answer", "answer"]
ReviewStatus = Literal["open", "resolved"]
ANSWER_KINDS = ("broken_answer", "answer")  # 'answer': rows written before migration 0006
RELATION_KINDS = ("supersedes", "amends", "deprecates")

_COLUMNS = (
    "id, kind, ref_id, tenant_id, status, payload, resolution, resolved_at, resolved_by, created_at"
)


class ReviewItem(BaseModel):
    id: UUID
    kind: ReviewKind
    ref_id: UUID
    tenant_id: UUID
    status: ReviewStatus
    payload: dict[str, Any]
    resolution: dict[str, Any] | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    created_at: datetime


class ReviewNotFound(LookupError):
    """No such item in this tenant (HTTP 404)."""


class AlreadyResolved(Exception):
    """The item was resolved before (HTTP 409)."""


class InvalidResolution(ValueError):
    """The action or edit does not fit the item (HTTP 422)."""


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _item(row: asyncpg.Record) -> ReviewItem:
    data = dict(row)
    data["payload"] = _json(data["payload"]) or {}
    data["resolution"] = _json(data["resolution"])
    return ReviewItem.model_validate(data)


def _check_edit(kind: str, action: str, edit: dict | None) -> None:
    if action != "edit":
        if edit is not None:
            raise InvalidResolution(f"an edit needs action 'edit', not {action!r}")
        return
    if not edit:
        raise InvalidResolution("action 'edit' needs an edit")
    if kind == "relation":
        if set(edit) != {"kind"} or edit["kind"] not in RELATION_KINDS:
            raise InvalidResolution(f"a relation edit is {{'kind': one of {RELATION_KINDS}}}")
    elif set(edit) != {"answer"} or not isinstance(edit["answer"], str) or not edit["answer"]:
        raise InvalidResolution("an answer edit is {'answer': '<corrected answer text>'}")


async def _outbox(conn: asyncpg.Connection, topic: str, payload: str) -> None:
    await conn.execute("INSERT INTO outbox (topic, payload) VALUES ($1, $2::jsonb)", topic, payload)


class ReviewQueue:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def open(
        self,
        kind: ReviewKind,
        ref_id: UUID,
        tenant_id: UUID,
        payload: dict[str, Any],
        *,
        conn: asyncpg.Connection | None = None,
    ) -> UUID | None:
        """Open an item; returns its id, or None when the same item is already open."""
        sql = (
            "INSERT INTO review_items (kind, ref_id, tenant_id, payload) "
            "VALUES ($1, $2, $3, $4::jsonb) "
            "ON CONFLICT (kind, ref_id) WHERE status = 'open' DO NOTHING RETURNING id"
        )
        args = (kind, ref_id, tenant_id, json.dumps(payload))
        if conn is not None:
            return await conn.fetchval(sql, *args)
        async with self._pool.acquire() as c:
            return await c.fetchval(sql, *args)

    async def list(
        self,
        tenant_id: UUID,
        status: ReviewStatus = "open",
        kind: ReviewKind | None = None,
        *,
        limit: int = 100,
    ) -> builtins.list[ReviewItem]:
        """This tenant's items, oldest first. `broken_answer` also matches legacy rows."""
        kinds = list(ANSWER_KINDS) if kind == "broken_answer" else [kind] if kind else None
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_COLUMNS} FROM review_items WHERE tenant_id = $1 AND status = $2 "
                "AND ($3::text[] IS NULL OR kind = ANY($3::text[])) "
                "ORDER BY created_at, id LIMIT $4",
                tenant_id,
                status,
                kinds,
                limit,
            )
        return [_item(r) for r in rows]

    async def resolve(
        self,
        item_id: UUID,
        action: ReviewAction,
        edit: dict[str, Any] | None = None,
        *,
        by: str,
        tenant_id: UUID,
    ) -> ReviewItem:
        if action not in ("approve", "edit", "reject"):
            raise InvalidResolution(f"unknown action {action!r}")
        follow_up: tuple[str, AskJob] | None = None
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"SELECT {_COLUMNS} FROM review_items WHERE id = $1 AND tenant_id = $2 FOR UPDATE",
                item_id,
                tenant_id,
            )
            if row is None:
                raise ReviewNotFound(str(item_id))
            item = _item(row)
            if item.status != "open":
                raise AlreadyResolved(str(item_id))
            _check_edit(item.kind, action, edit)
            resolution: dict[str, Any] = {"action": action, "edit": edit}
            if item.kind == "relation":
                question, as_of, original = await self._resolve_relation(conn, item, action, edit)
            elif item.kind in ANSWER_KINDS:
                job, question, as_of, original = await self._resolve_broken(conn, item, action)
                follow_up = (ASK_REGENERATE_TOPIC, job) if job is not None else None
            else:
                job, question, as_of, original = await self._resolve_paused(
                    conn, item, action, edit, by
                )
                follow_up = (ASK_RESUME_TOPIC, job)
            if follow_up is not None:
                topic, job = follow_up
                await _outbox(conn, topic, job.model_dump_json())
                resolution["job_id"] = str(job.job_id)
            if action == "edit":
                await conn.execute(
                    "INSERT INTO eval_cases (tenant_id, source_review_id, question, as_of, "
                    "expected) VALUES ($1, $2, $3, $4, $5::jsonb)",
                    tenant_id,
                    item.id,
                    question,
                    as_of,
                    json.dumps(
                        {"review_kind": item.kind, "edit": edit, "original": original},
                        default=str,
                    ),
                )
            done = await conn.fetchrow(
                "UPDATE review_items SET status = 'resolved', resolution = $2::jsonb, "
                f"resolved_at = now(), resolved_by = $3 WHERE id = $1 RETURNING {_COLUMNS}",
                item.id,
                json.dumps(resolution),
                by,
            )
        return _item(done)

    async def _resolve_relation(self, conn, item: ReviewItem, action: str, edit: dict | None):
        rel = await conn.fetchrow(
            "SELECT r.id, r.kind, r.status, r.dst_document_id, sv.valid_from, "
            "sd.title AS src_title, "
            "dd.title AS dst_title FROM relations r "
            "JOIN doc_versions sv ON sv.id = r.src_version_id "
            "JOIN documents sd ON sd.id = sv.document_id "
            "JOIN sources s ON s.id = sd.source_id "
            "JOIN documents dd ON dd.id = r.dst_document_id "
            "WHERE r.id = $1 AND s.tenant_id = $2",
            item.ref_id,
            item.tenant_id,
        )
        if rel is None:  # a malformed-extraction item: it references a version
            if action == "edit":
                raise InvalidResolution("this item has no relation to edit")
            return None, None, None
        kind = edit["kind"] if edit else rel["kind"]
        status = "rejected" if action == "reject" else "applied"
        await conn.execute(
            "UPDATE relations SET status = $2, kind = $3 WHERE id = $1", rel["id"], status, kind
        )
        if status == "applied":
            # Cached answers citing the replaced document must not be served again: its
            # versions are still inside their validity windows, so the cache's own
            # in-force re-check would not catch it. (Amendments too: the meaning changed.)
            versions = await conn.fetch(
                "SELECT id FROM doc_versions WHERE document_id = $1", rel["dst_document_id"]
            )
            if versions:
                await _outbox(
                    conn,
                    CACHE_INVALIDATE_TOPIC,
                    json.dumps({"version_ids": [str(v["id"]) for v in versions]}),
                )
        question = f"Does {rel['src_title']!s} {kind} {rel['dst_title']!s}?"
        return question, rel["valid_from"], {"kind": rel["kind"], "status": rel["status"]}

    async def _resolve_broken(self, conn, item: ReviewItem, action: str):
        answer = await conn.fetchrow(
            "SELECT question, as_of, body FROM answers WHERE id = $1 AND tenant_id = $2",
            item.ref_id,
            item.tenant_id,
        )
        if answer is None:
            raise InvalidResolution("the answer under review no longer exists")
        original = _json(answer["body"])
        if action == "reject":
            return None, answer["question"], answer["as_of"], original
        # Regenerate as of now: the answer is watched, so it should reflect what is in
        # force today. The new run pauses for review again before replacing the answer.
        job = await self._queue_ask(conn, item.tenant_id, answer["question"])
        job = job.model_copy(update={"answer_id": item.ref_id})
        await conn.execute(
            "UPDATE jobs SET payload = $2::jsonb WHERE id = $1",
            job.job_id,
            job.model_dump_json(),
        )
        return job, answer["question"], answer["as_of"], original

    async def _resolve_paused(
        self, conn, item: ReviewItem, action: str, edit: dict | None, by: str
    ):
        request = item.payload
        job_row = await conn.fetchrow(
            "SELECT id, payload FROM jobs WHERE id = $1 AND tenant_id = $2 AND kind = 'ask' "
            "FOR UPDATE",
            item.ref_id,
            item.tenant_id,
        )
        if job_row is None:
            raise InvalidResolution("the paused ask no longer exists")
        job = AskJob.model_validate(request["job"]).model_copy(
            update={"resume": ReviewDecision(review_id=item.id, action=action, edit=edit, by=by)}
        )
        await conn.execute(
            "UPDATE jobs SET status = 'queued' WHERE id = $1 AND status = 'needs_review'",
            item.ref_id,
        )
        answer = request.get("answer") or {}
        as_of = datetime.fromisoformat(answer["as_of"]) if answer.get("as_of") else None
        return job, request.get("question") or job.question, as_of, answer

    async def _queue_ask(self, conn, tenant_id: UUID, question: str) -> AskJob:
        job_id = await conn.fetchval(
            "INSERT INTO jobs (tenant_id, kind) VALUES ($1, 'ask') RETURNING id", tenant_id
        )
        return AskJob(job_id=job_id, tenant_id=tenant_id, question=question)
