import io
import zipfile
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from conftest_cassettes import scrub_response_headers

from driftline.ingest.connectors.openfda import (
    HistoryEntry,
    OpenFDAConnector,
    parse_hl7_date,
    parse_published_date,
    parse_spl,
    resolve_valid_from,
    spl_xml_from_zip,
)
from driftline.ingest.types import SourceFetchError

LIPITOR = "a60cc18b-0631-4cf0-b021-9f52224ece65"  # 7 archived versions, 3 distinct texts
TOFACITINIB_ER = "024bb9f2-8c26-4d9d-a33b-eb3c0a7c59ed"  # DailyMed archives only v5+


def keep_spl_xml_only(response: dict[str, Any]) -> dict[str, Any]:
    """Shrink recorded DailyMed zips to their SPL XML member (drop label images and cookies).

    The connector still unzips a real DailyMed archive on replay; only image members,
    which it never reads, are left out so cassettes stay around half a megabyte.
    """
    body = response.get("body", {}).get("string")
    if isinstance(body, bytes) and body[:4] == b"PK\x03\x04":
        src = zipfile.ZipFile(io.BytesIO(body))
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
            for info in src.infolist():
                if info.filename.lower().endswith(".xml"):
                    dst.writestr(info.filename, src.read(info))
        response["body"]["string"] = out.getvalue()
        for key in list(response.get("headers") or {}):
            if key.lower() == "content-length":
                response["headers"][key] = [str(len(out.getvalue()))]
    headers = response.get("headers") or {}
    response["headers"] = {k: v for k, v in headers.items() if k.lower() != "set-cookie"}
    return scrub_response_headers(response)


@pytest.fixture(scope="module")
def vcr_config():
    return {
        "before_record_response": keep_spl_xml_only,
        "filter_headers": ["cookie"],
        "filter_query_parameters": ["api_key"],
        "match_on": ["method", "scheme", "host", "path", "query"],
    }


def spl_xml(effective: str | None = "20240415", version: str = "3") -> bytes:
    eff = "<effectiveTime/>" if effective is None else f'<effectiveTime value="{effective}"/>'
    body = (
        '<component><section><code code="34066-1" displayName="BOXED WARNING SECTION"/>'
        "<title>WARNING: HEPATOTOXICITY</title><text><paragraph>Liver failure.</paragraph>"
        "</text></section></component>"
        '<component><section><code code="43685-7" displayName="WARNINGS AND PRECAUTIONS"/>'
        "<title>5 WARNINGS AND PRECAUTIONS</title><text>See below.</text>"
        "<component><section><title>5.1 Liver Enzyme Abnormalities</title>"
        "<text>Monitor  ALT.</text></section></component></section></component>"
        '<component><section><code code="42229-5" displayName="SPL UNCLASSIFIED SECTION"/>'
        "<text>One.</text></section></component>"
        '<component><section><code code="42229-5" displayName="SPL UNCLASSIFIED SECTION"/>'
        "<text>Two.</text></section></component>"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><document xmlns="urn:hl7-org:v3">'
        f'<id root="doc-1"/><title>DRUGX tablets</title>{eff}<setId root="set-1"/>'
        f'<versionNumber value="{version}"/><component><structuredBody>{body}'
        "</structuredBody></component></document>"
    ).encode()


def test_parse_hl7_date_variants():
    assert parse_hl7_date("20240415") == datetime(2024, 4, 15, tzinfo=UTC)
    assert parse_hl7_date("202404151230") == datetime(2024, 4, 15, 12, 30, tzinfo=UTC)
    assert parse_hl7_date("20240415123045") == datetime(2024, 4, 15, 12, 30, 45, tzinfo=UTC)
    assert parse_hl7_date("") is None
    assert parse_hl7_date(None) is None
    assert parse_hl7_date("20241399") is None


def test_parse_published_date():
    assert parse_published_date("Jul 15, 2026") == datetime(2026, 7, 15, tzinfo=UTC)
    assert parse_published_date("not a date") is None
    assert parse_published_date(None) is None


def test_parse_spl_sections_and_metadata():
    spl = parse_spl(spl_xml())
    assert (spl.document_id, spl.set_id, spl.version) == ("doc-1", "set-1", 3)
    assert spl.effective_time == datetime(2024, 4, 15, tzinfo=UTC)
    assert spl.title == "DRUGX tablets"
    assert [s.path for s in spl.sections] == [
        "WARNING: HEPATOTOXICITY",
        "5 WARNINGS AND PRECAUTIONS",
        "5 WARNINGS AND PRECAUTIONS > 5.1 Liver Enzyme Abnormalities",
        "SPL UNCLASSIFIED SECTION",
        "SPL UNCLASSIFIED SECTION [2]",
    ]
    assert spl.sections[0].text == "Liver failure."
    assert spl.sections[2].text == "Monitor ALT."


def test_missing_effective_time_falls_back_to_published_date():
    spl = parse_spl(spl_xml(effective=None))
    assert spl.effective_time is None
    entry = HistoryEntry(spl_version=3, published_date=datetime(2026, 7, 15, tzinfo=UTC))
    assert resolve_valid_from(spl, entry) == datetime(2026, 7, 15, tzinfo=UTC)
    dated = parse_spl(spl_xml())
    assert resolve_valid_from(dated, entry) == datetime(2024, 4, 15, tzinfo=UTC)


def test_missing_both_dates_raises_non_retryable():
    spl = parse_spl(spl_xml(effective=""))
    with pytest.raises(SourceFetchError) as info:
        resolve_valid_from(spl, HistoryEntry(spl_version=3, published_date=None))
    assert info.value.retryable is False


def test_invalid_or_hostile_xml_raises_non_retryable():
    for bad in (
        b"<document><unclosed>",
        b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x "boom">]><document>&x;</document>',
    ):
        with pytest.raises(SourceFetchError) as info:
            parse_spl(bad)
        assert info.value.retryable is False


def test_spl_xml_from_zip_reads_xml_and_rejects_non_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("image-01.jpg", b"\xff\xd8")
        zf.writestr("abc.xml", spl_xml())
    assert spl_xml_from_zip(buf.getvalue()) == spl_xml()
    with pytest.raises(SourceFetchError):
        spl_xml_from_zip(b"<html>not a zip</html>")


@pytest.mark.vcr
async def test_search_labels_follows_link_pagination(require_cassette):
    async with httpx.AsyncClient(timeout=120) as http:
        connector = OpenFDAConnector(
            http, search='openfda.generic_name:"atorvastatin"', limit=3, page_size=2
        )
        refs = await connector.search_labels()
    assert len(refs) == 3
    assert len({r.set_id for r in refs}) == 3
    assert all(len(r.set_id) == 36 and r.version for r in refs)
    assert all("ATORVASTATIN" in " ".join(r.generic_name).upper() for r in refs)


@pytest.mark.vcr
async def test_lipitor_history_yields_all_archived_versions_oldest_first(require_cassette):
    async with httpx.AsyncClient(timeout=120) as http:
        docs = [d async for d in OpenFDAConnector(http).fetch(LIPITOR)]
    assert [d.version_key for d in docs] == ["1", "2", "4", "5", "6", "7", "8"]
    by_key = {d.version_key: d for d in docs}
    assert by_key["1"].valid_from == datetime(2023, 2, 15, tzinfo=UTC)
    # Real data: v5 (warnings changes) and v7 (carton text) share one effectiveTime.
    assert by_key["5"].valid_from == by_key["7"].valid_from == datetime(2024, 4, 15, tzinfo=UTC)
    assert len({d.sections for d in docs}) == 3  # v1=v2=v4, v5=v6, v7=v8
    latest = by_key["8"]
    assert latest.title.startswith("LIPITOR (ATORVASTATIN CALCIUM)")
    assert latest.raw_uri.endswith(f"setid={LIPITOR}&version=8")
    assert latest.source_meta["spl_version"] == 8
    assert any(s.path.startswith("5 WARNINGS AND PRECAUTIONS") for s in latest.sections)


@pytest.mark.vcr
async def test_fetch_since_cursor_skips_older_versions(require_cassette):
    async with httpx.AsyncClient(timeout=120) as http:
        docs = [d async for d in OpenFDAConnector(http).fetch(LIPITOR, since="6")]
    assert [d.version_key for d in docs] == ["7", "8"]


@pytest.mark.vcr
async def test_unarchived_version_returns_none(require_cassette):
    async with httpx.AsyncClient(timeout=120) as http:
        connector = OpenFDAConnector(http)
        _, entries = await connector.history(TOFACITINIB_ER)
        assert entries and 1 not in [e.spl_version for e in entries]
        assert await connector.spl_version_xml(TOFACITINIB_ER, 1) is None
