import json
import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg

from driftline.agents.events import AlertEvent
from driftline.drift.alerts import AlertLog, alert_stream_key
from driftline.ingest.outbox import OutboxRelay
from driftline.streams.bus import StreamBus


def make_alert(verdict: str = "changed", title: str = "Runbook") -> AlertEvent:
    return AlertEvent(
        drift_event_id=uuid4(),
        answer_id=uuid4(),
        verdict=verdict,
        document_title=title,
        old_version_id=uuid4(),
        new_version_id=uuid4(),
        before="old text",
        after="new text",
        t=datetime(2026, 10, 25, 12, 0, tzinfo=UTC),
    )


async def add_alert_row(pool, tenant_id: UUID, alert: AlertEvent) -> int:
    payload = {**alert.model_dump(mode="json"), "tenant_id": str(tenant_id)}
    return await add_raw_row(pool, payload)


async def add_raw_row(pool, payload: dict) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO outbox (topic, payload) VALUES ('drift.alert', $1::jsonb) RETURNING id",
            json.dumps(payload),
        )


async def is_published(pool, row_id: int) -> bool:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT published_at IS NOT NULL FROM outbox WHERE id = $1", row_id
        )


def test_alert_stream_key_is_per_tenant():
    tenant = uuid4()
    assert alert_stream_key(tenant) == f"events:alerts:{tenant}"
    assert alert_stream_key(str(tenant)) == f"events:alerts:{tenant}"


async def test_alert_published_to_tenant_stream_only(fresh_pool, redis_client):
    tenant_a, tenant_b = uuid4(), uuid4()
    alert = make_alert()
    row_id = await add_alert_row(fresh_pool, tenant_a, alert)
    alerts = AlertLog(redis_client)
    relay = OutboxRelay(fresh_pool, StreamBus(redis_client), alerts=alerts)

    assert await relay.relay_once() == 1

    assert await alerts.read(tenant_a) == [(1, alert)]
    assert await alerts.read(tenant_b) == []
    assert await redis_client.exists(alert_stream_key(tenant_b)) == 0
    assert await redis_client.exists("drift.alert") == 0
    assert await is_published(fresh_pool, row_id)


async def test_alert_replay_from_last_event_id(fresh_pool, redis_client):
    tenant = uuid4()
    sent = [make_alert(title=f"doc {i}") for i in range(4)]
    for alert in sent:
        await add_alert_row(fresh_pool, tenant, alert)
    alerts = AlertLog(redis_client)
    await OutboxRelay(fresh_pool, StreamBus(redis_client), alerts=alerts).relay_once()

    assert await alerts.last_id(tenant) == 4
    replay = await alerts.read(tenant, after=2)
    assert replay == [(3, sent[2]), (4, sent[3])]
    assert not await alerts.has_gap(tenant, after=2)
    assert await alerts.read(tenant, after=4) == []


async def test_alert_stream_trimmed_to_maxlen(fresh_pool, redis_client):
    tenant = uuid4()
    for i in range(6):
        await add_alert_row(fresh_pool, tenant, make_alert(title=f"doc {i}"))
    alerts = AlertLog(redis_client, maxlen=3, ttl_s=600)
    await OutboxRelay(fresh_pool, StreamBus(redis_client), alerts=alerts).relay_once()

    assert await redis_client.xlen(alert_stream_key(tenant)) == 3
    assert await alerts.first_id(tenant) == 4
    assert [n for n, _ in await alerts.read(tenant)] == [4, 5, 6]
    assert await alerts.has_gap(tenant, after=1)  # a client this far behind gets events_expired
    assert not await alerts.has_gap(tenant, after=3)
    assert 0 < await redis_client.ttl(alert_stream_key(tenant)) <= 600


async def test_relay_redelivery_does_not_duplicate_alert(fresh_pool, fresh_dsn, redis_client):
    tenant = uuid4()
    alert = make_alert()
    row_id = await add_alert_row(fresh_pool, tenant, alert)
    alerts = AlertLog(redis_client)
    relay = OutboxRelay(fresh_pool, StreamBus(redis_client), alerts=alerts)
    crashing = await asyncpg.connect(fresh_dsn)
    tx = crashing.transaction()
    await tx.start()
    assert await relay.claim_and_publish(crashing) == [row_id]
    await crashing.close()  # the relay dies before mark_published commits

    assert await relay.relay_once() == 1  # the same outbox row is published again

    assert await alerts.read(tenant) == [(1, alert)]
    assert await alerts.last_id(tenant) == 1
    assert await is_published(fresh_pool, row_id)


async def test_append_with_same_dedupe_id_returns_original_id(redis_client):
    tenant = uuid4()
    alerts = AlertLog(redis_client)
    first, second = make_alert(), make_alert()
    assert await alerts.append(tenant, first, dedupe_id="7") == 1
    assert await alerts.append(tenant, first, dedupe_id="7") == 1
    assert await alerts.append(tenant, second, dedupe_id="8") == 2
    assert await alerts.append(uuid4(), first, dedupe_id="7") == 1  # dedupe is per tenant
    assert await alerts.read(tenant) == [(1, first), (2, second)]


async def test_invalid_alert_payload_is_logged_and_dead_lettered(fresh_pool, redis_client, caplog):
    tenant = uuid4()
    bad_ids = [
        await add_raw_row(fresh_pool, {"n": 0}),  # not an alert at all
        await add_raw_row(fresh_pool, {**make_alert().model_dump(mode="json")}),  # no tenant
        await add_raw_row(
            fresh_pool,
            {**make_alert().model_dump(mode="json"), "tenant_id": str(tenant), "verdict": "meh"},
        ),
    ]
    good = make_alert()
    good_id = await add_alert_row(fresh_pool, tenant, good)
    alerts = AlertLog(redis_client)
    relay = OutboxRelay(fresh_pool, StreamBus(redis_client), alerts=alerts)

    with caplog.at_level(logging.ERROR, logger="driftline.ingest.outbox"):
        assert await relay.relay_once() == 4

    # The valid alert behind the bad rows still goes out; nothing bad reaches a tenant stream.
    assert await alerts.read(tenant) == [(1, good)]
    assert await is_published(fresh_pool, good_id)
    # Each bad row is dead-lettered with its outbox id and the error, and logged; it is
    # marked published so a payload that can never validate does not block the relay.
    dlq = [json.loads(fields["data"]) for _, fields in await redis_client.xrange("dlq:drift.alert")]
    assert [d["event_id"] for d in dlq] == bad_ids
    assert all(d["topic"] == "drift.alert" and d["error"] for d in dlq)
    for row_id in bad_ids:
        assert await is_published(fresh_pool, row_id)
        assert any(
            r.levelno == logging.ERROR and str(row_id) in r.getMessage() for r in caplog.records
        ), row_id
    assert await relay.relay_once() == 0
