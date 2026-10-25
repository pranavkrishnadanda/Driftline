"""The SSE contract for the frontend (P5a): JSON Schema of every event plus a complete,
valid example stream. `python -m driftline.gateway.contract --write` regenerates the
committed fixture; a test fails if the fixture and the code disagree."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from driftline.agents.events import (
    ALERT_EVENT_ADAPTER,
    ASK_EVENT_ADAPTER,
    AlertEvent,
    ClaimEvent,
    ErrorEvent,
    FinalEvent,
    StepEvent,
    TokenEvent,
)
from driftline.agents.schemas import AnswerSchema, Citation, Claim

CONTRACT_PATH = Path(__file__).resolve().parents[4] / "contracts" / "sse" / "ask-events.v1.json"
ALERT_CONTRACT_PATH = CONTRACT_PATH.with_name("alert-events.v1.json")
_CHUNK = UUID("00000000-0000-4000-8000-0000000000c2")
_VERSION = UUID("00000000-0000-4000-8000-0000000000a2")
_DOCUMENT = UUID("00000000-0000-4000-8000-0000000000d1")
_QUOTE = "Check ALT monthly during therapy."


def example_events() -> list[tuple[int, Any]]:
    citation = Citation(
        chunk_id=_CHUNK,
        version_id=_VERSION,
        quote=_QUOTE,
        document_id=_DOCUMENT,
        title="Lipitor (atorvastatin calcium) label",
        external_id="lipitor",
        version_no=2,
        section_path="Warnings and Precautions > Liver Dysfunction",
        valid_from="2024-04-15T00:00:00Z",
        valid_to=None,
    )
    answer = AnswerSchema(
        status="answered",
        answer="ALT should be checked monthly during therapy.",
        claims=[
            Claim(
                idx=0,
                text="ALT is checked monthly during therapy.",
                citations=[citation],
                verified=True,
            )
        ],
        citations=[citation],
        as_of="2024-06-01T00:00:00Z",
        confidence=1.0,
        answer_id=UUID("00000000-0000-4000-8000-0000000000f1"),
        cost_usd=0.0042,
    )
    events = [
        StepEvent(node="classify", status="started", t_ms=0.0),
        StepEvent(
            node="classify",
            status="completed",
            detail={"as_of": "2024-06-01T00:00:00+00:00", "source": "request", "refused": None},
            t_ms=2.1,
        ),
        StepEvent(node="cache", status="miss", t_ms=9.8),
        StepEvent(node="plan", status="started", t_ms=10.0),
        StepEvent(
            node="plan",
            status="completed",
            detail={
                "mode": "single",
                "sub_questions": [
                    {
                        "question": "How often should ALT be checked?",
                        "as_of": "2024-06-01T00:00:00+00:00",
                    }
                ],
            },
            t_ms=812.4,
        ),
        StepEvent(
            node="subagent",
            status="started",
            detail={
                "branch": 0,
                "sub_question": "How often should ALT be checked?",
                "as_of": "2024-06-01T00:00:00+00:00",
            },
            t_ms=813.0,
        ),
        StepEvent(
            node="subagent",
            status="completed",
            detail={
                "branch": 0,
                "retrieved": 30,
                "kept": 8,
                "reranked": True,
                "rerank_error": None,
            },
            t_ms=1290.5,
        ),
        StepEvent(node="merge", status="completed", detail={"evidence": 8}, t_ms=1291.0),
        StepEvent(node="draft", status="started", detail={"attempt": 0}, t_ms=1291.2),
        TokenEvent(text="ALT should be checked "),
        TokenEvent(text="monthly during therapy."),
        StepEvent(
            node="draft", status="completed", detail={"attempt": 0, "claims": 1}, t_ms=3410.7
        ),
        StepEvent(node="verify", status="started", detail={"attempt": 0}, t_ms=3411.0),
        ClaimEvent(idx=0, verified=True, citation=citation),
        StepEvent(
            node="verify",
            status="completed",
            detail={"supported": 1, "unsupported": 0},
            t_ms=4210.3,
        ),
        StepEvent(
            node="respond",
            status="completed",
            detail={"outcome": "answered", "error": None},
            t_ms=4212.9,
        ),
        FinalEvent(answer=answer),
    ]
    return list(enumerate(events, start=1))


def build_contract() -> dict[str, Any]:
    examples = [
        {"id": seq, "event": event.type, "data": event.model_dump(mode="json")}
        for seq, event in example_events()
    ]
    examples.append(
        {
            "id": None,
            "event": "error",
            "data": ErrorEvent(
                code="events_expired",
                retryable=False,
                message="events after 3 are no longer stored",
            ).model_dump(mode="json"),
        }
    )
    return {
        "name": "driftline.ask.events",
        "version": 1,
        "media_type": "text/event-stream",
        "endpoints": {
            "submit": "POST /v1/ask -> 202 {job_id, events_url, status_url}",
            "events": "GET /v1/jobs/{job_id}/events (alias GET /v1/ask/{job_id}/events)",
            "status": "GET /v1/jobs/{job_id}",
        },
        "framing": {
            "id": "integer, strictly increasing per job, starting at 1; absent on gateway-made events",
            "event": "the event type: step | token | claim | final | error",
            "data": "one JSON object matching `schema`",
            "heartbeat": ": ping (an SSE comment line, sent when no event arrives for 15 s)",
            "terminal": "the stream ends after `final`, or after `error` with retryable=false",
            "resume": "reconnect with the Last-Event-ID header (or ?last_event_id=) to replay",
        },
        "schema": ASK_EVENT_ADAPTER.json_schema(),
        "examples": examples,
    }


_ANSWER = UUID("00000000-0000-4000-8000-0000000000f1")
_DOC_V1 = UUID("00000000-0000-4000-8000-0000000000a1")
_DOC_V2 = UUID("00000000-0000-4000-8000-0000000000a2")
_DOC_V3 = UUID("00000000-0000-4000-8000-0000000000a3")


def example_alert_events() -> list[tuple[int, Any]]:
    events = [
        AlertEvent(
            drift_event_id=UUID("00000000-0000-4000-8000-0000000000d1"),
            answer_id=_ANSWER,
            verdict="changed",
            document_title="Drug X label",
            old_version_id=_DOC_V1,
            new_version_id=_DOC_V2,
            before="Check ALT monthly during therapy.",
            after="Check ALT every two weeks during therapy.",
            t="2024-07-01T09:30:00Z",
        ),
        AlertEvent(
            drift_event_id=UUID("00000000-0000-4000-8000-0000000000d2"),
            answer_id=_ANSWER,
            verdict="broken",
            document_title="Drug X label",
            old_version_id=_DOC_V2,
            new_version_id=_DOC_V3,
            before="Check ALT every two weeks during therapy.",
            after=None,
            t="2024-09-01T09:30:00Z",
        ),
    ]
    return list(enumerate(events, start=1))


def build_alert_contract() -> dict[str, Any]:
    examples = [
        {"id": seq, "event": event.type, "data": event.model_dump(mode="json")}
        for seq, event in example_alert_events()
    ]
    examples.append(
        {
            "id": None,
            "event": "error",
            "data": ErrorEvent(
                code="events_expired",
                retryable=False,
                message="alerts after 1 are no longer stored; GET /v1/drift/events",
            ).model_dump(mode="json"),
        }
    )
    return {
        "name": "driftline.alert.events",
        "version": 1,
        "media_type": "text/event-stream",
        "endpoints": {
            "stream": "GET /v1/alerts/stream?tenant=<name>",
            "history": "GET /v1/drift/events?tenant=<name>&limit=<n>",
            "watch": "POST /v1/answers/{answer_id}/watch?tenant=<name> (DELETE to unwatch)",
        },
        "framing": {
            "id": "integer, strictly increasing per tenant, starting at 1; "
            "absent on gateway-made events",
            "event": "the event type: alert | error",
            "data": "one JSON object matching `schema`",
            "heartbeat": ": ping (an SSE comment line, sent when no event arrives for 15 s)",
            "terminal": "none: the stream stays open; it ends only after `error` "
            "(events_expired), when the client should reload GET /v1/drift/events",
            "resume": "reconnect with the Last-Event-ID header (or ?last_event_id=) to replay",
            "verdicts": "still_valid is recorded but not alerted; changed carries before "
            "and after; broken has after=null",
        },
        "schema": ALERT_EVENT_ADAPTER.json_schema(),
        "examples": examples,
    }


def install_event_schemas(app: FastAPI) -> None:
    """Publish the AskEvent and AlertEvents unions (and their parts) under
    components.schemas in OpenAPI."""

    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        for name, adapter in (
            ("AskEvent", ASK_EVENT_ADAPTER),
            ("AlertEvents", ALERT_EVENT_ADAPTER),
        ):
            union = adapter.json_schema(ref_template="#/components/schemas/{model}")
            components.update(union.pop("$defs", {}))
            components[name] = union
        app.openapi_schema = schema
        return schema

    app.openapi = openapi


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m driftline.gateway.contract")
    parser.add_argument(
        "--write", action="store_true", help=f"write {CONTRACT_PATH} and {ALERT_CONTRACT_PATH}"
    )
    args = parser.parse_args(argv)
    contracts = {CONTRACT_PATH: build_contract(), ALERT_CONTRACT_PATH: build_alert_contract()}
    for path, contract in contracts.items():
        text = json.dumps(contract, indent=2, sort_keys=True) + "\n"
        if args.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        else:
            sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
