"""Drug labels: discovery via openFDA, full version history via DailyMed SPL archives.

openFDA's /drug/label endpoint serves only the current version of each label (one
record per set_id), so older versions come from DailyMed:
  history:  GET {dailymed}/services/v2/spls/{set_id}/history.json
  version:  GET {dailymed}/getFile.cfm?type=zip&setid={set_id}&version={n}  (zip with the SPL XML)
"""

import io
import re
import zipfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from xml.etree.ElementTree import Element

import httpx
from defusedxml import DefusedXmlException
from defusedxml import ElementTree as SafeET

from driftline.ingest.types import (
    RawDocument,
    Section,
    SourceFetchError,
    render_content,
    unique_sections,
)

OPENFDA_URL = "https://api.fda.gov/drug/label.json"
DAILYMED_URL = "https://dailymed.nlm.nih.gov/dailymed"
V3 = "{urn:hl7-org:v3}"
_WS = re.compile(r"\s+")
_LINK_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')


@dataclass(frozen=True)
class LabelRef:
    set_id: str
    version: str
    effective_time: str | None
    brand_name: list[str]
    generic_name: list[str]


@dataclass(frozen=True)
class HistoryEntry:
    spl_version: int
    published_date: datetime | None


@dataclass(frozen=True)
class ParsedSpl:
    document_id: str
    set_id: str
    version: int
    effective_time: datetime | None
    title: str
    sections: tuple[Section, ...]


def _text(el: Element | None) -> str:
    return _WS.sub(" ", "".join(el.itertext())).strip() if el is not None else ""


def parse_hl7_date(value: str | None) -> datetime | None:
    """HL7 TS `YYYYMMDD[HHMM[SS]]` -> aware UTC datetime; blank or malformed -> None."""
    digits = re.sub(r"\D", "", (value or "").strip()[:14])
    for width, fmt in ((14, "%Y%m%d%H%M%S"), (12, "%Y%m%d%H%M"), (8, "%Y%m%d")):
        if len(digits) >= width:
            try:
                return datetime.strptime(digits[:width], fmt).replace(tzinfo=UTC)
            except ValueError:
                return None
    return None


def parse_published_date(value: str | None) -> datetime | None:
    """DailyMed history dates look like `Jul 15, 2026`."""
    try:
        return datetime.strptime((value or "").strip(), "%b %d, %Y").replace(tzinfo=UTC)
    except ValueError:
        return None


def _section_pairs(section: Element, parents: list[str]) -> list[tuple[str, str]]:
    code = section.find(f"{V3}code")
    label = _text(section.find(f"{V3}title")) or (
        code.get("displayName", "") if code is not None else ""
    )
    path = [*parents, label or "Untitled"]
    pairs = [(" > ".join(path), _text(section.find(f"{V3}text")))]
    for child in section.findall(f"{V3}component/{V3}section"):
        pairs.extend(_section_pairs(child, path))
    return pairs


def _attr(root: Element, tag: str, name: str) -> str:
    el = root.find(f"{V3}{tag}")
    return el.get(name, "") if el is not None else ""


def parse_spl(xml: bytes) -> ParsedSpl:
    """Parse an SPL document into sections keyed by their title path."""
    try:
        root = SafeET.fromstring(xml)
    except (SafeET.ParseError, DefusedXmlException) as exc:
        raise SourceFetchError(f"invalid SPL XML: {exc}", retryable=False) from exc
    pairs: list[tuple[str, str]] = []
    for top in root.findall(f"{V3}component/{V3}structuredBody/{V3}component/{V3}section"):
        pairs.extend(_section_pairs(top, []))
    version = _attr(root, "versionNumber", "value")
    return ParsedSpl(
        document_id=_attr(root, "id", "root"),
        set_id=_attr(root, "setId", "root"),
        version=int(version) if version.isdigit() else 0,
        effective_time=parse_hl7_date(_attr(root, "effectiveTime", "value")),
        title=_text(root.find(f"{V3}title")),
        sections=unique_sections(pairs),
    )


def spl_xml_from_zip(data: bytes) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = sorted(n for n in zf.namelist() if n.lower().endswith(".xml"))
            if not names:
                raise SourceFetchError("SPL archive contains no XML file", retryable=False)
            return zf.read(names[0])
    except zipfile.BadZipFile as exc:
        raise SourceFetchError(f"SPL archive is not a zip file: {exc}", retryable=False) from exc


def resolve_valid_from(spl: ParsedSpl, entry: HistoryEntry) -> datetime:
    """The label's own effectiveTime; DailyMed's published date only when that is missing."""
    if spl.effective_time is not None:
        return spl.effective_time
    if entry.published_date is not None:
        return entry.published_date
    raise SourceFetchError(
        f"SPL {spl.set_id} v{entry.spl_version} has neither effectiveTime nor published date",
        retryable=False,
    )


def _check(response: httpx.Response, what: str) -> None:
    status = response.status_code
    if status >= 400:
        raise SourceFetchError(
            f"{what}: HTTP {status}", retryable=status == 429 or status >= 500, status=status
        )


class OpenFDAConnector:
    kind = "openfda"

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        search: str = "_exists_:boxed_warning",
        limit: int = 10,
        page_size: int = 100,
        api_key: str | None = None,
        openfda_url: str = OPENFDA_URL,
        dailymed_url: str = DAILYMED_URL,
    ) -> None:
        self._http = http
        self._search = search
        self._limit = limit
        self._page_size = min(page_size, 1000)
        self._api_key = api_key
        self._openfda_url = openfda_url
        self._dailymed_url = dailymed_url.rstrip("/")

    async def search_labels(self) -> list[LabelRef]:
        """Current labels matching `search`, following openFDA's `Link: rel="next"` pages."""
        params: dict[str, str | int] | None = {"search": self._search, "limit": self._page_size}
        if self._api_key:
            params["api_key"] = self._api_key
        url: str | None = self._openfda_url
        refs: list[LabelRef] = []
        while url and len(refs) < self._limit:
            response = await self._http.get(url, params=params)
            if response.status_code == 404:  # openFDA answers "No matches found!" with 404
                break
            _check(response, "openFDA label search")
            for r in response.json().get("results", []):
                ofda = r.get("openfda", {})
                refs.append(
                    LabelRef(
                        set_id=r["set_id"],
                        version=str(r.get("version", "")),
                        effective_time=r.get("effective_time"),
                        brand_name=ofda.get("brand_name", []),
                        generic_name=ofda.get("generic_name", []),
                    )
                )
            match = _LINK_NEXT.search(response.headers.get("link", ""))
            # The next-page URL already carries every query parameter (and search_after);
            # httpx would replace its query string with `params`, so send none.
            url, params = (match.group(1), None) if match else (None, None)
        return refs[: self._limit]

    async def list_external_ids(self) -> list[str]:
        return sorted({ref.set_id for ref in await self.search_labels()})

    async def history(self, set_id: str) -> tuple[str, list[HistoryEntry]]:
        """(title, entries oldest first). DailyMed may list only some old versions."""
        entries: list[HistoryEntry] = []
        title, page = "", 1
        while True:
            response = await self._http.get(
                f"{self._dailymed_url}/services/v2/spls/{set_id}/history.json",
                params={"pagesize": 100, "page": page},
            )
            _check(response, f"DailyMed history {set_id}")
            body = response.json()
            title = body["data"]["spl"].get("title", "") or title
            entries += [
                HistoryEntry(int(h["spl_version"]), parse_published_date(h.get("published_date")))
                for h in body["data"]["history"]
            ]
            if page >= int(body["metadata"].get("total_pages", 1)):
                break
            page += 1
        return title, sorted(entries, key=lambda e: e.spl_version)

    async def spl_version_xml(self, set_id: str, version: int) -> bytes | None:
        """The SPL XML of one version, or None when DailyMed no longer archives it."""
        response = await self._http.get(
            f"{self._dailymed_url}/getFile.cfm",
            params={"type": "zip", "setid": set_id, "version": version},
        )
        if response.status_code == 404:
            return None
        _check(response, f"DailyMed SPL {set_id} v{version}")
        return spl_xml_from_zip(response.content)

    async def fetch(
        self, external_id: str, *, since: str | None = None
    ) -> AsyncIterator[RawDocument]:
        """Every archived version newer than `since` (an spl_version), oldest first."""
        floor = int(since) if since and since.isdigit() else 0
        title, entries = await self.history(external_id)
        for entry in entries:
            if entry.spl_version <= floor:
                continue
            xml = await self.spl_version_xml(external_id, entry.spl_version)
            if xml is None:
                continue
            spl = parse_spl(xml)
            yield RawDocument(
                external_id=external_id,
                title=title or spl.title,
                version_key=str(entry.spl_version),
                valid_from=resolve_valid_from(spl, entry),
                content=render_content(spl.sections),
                sections=spl.sections,
                raw_uri=(
                    f"{self._dailymed_url}/getFile.cfm?type=zip&setid={external_id}"
                    f"&version={entry.spl_version}"
                ),
                source_meta={
                    "set_id": external_id,
                    "spl_version": entry.spl_version,
                    "spl_document_id": spl.document_id,
                    "effective_time": spl.effective_time.isoformat()
                    if spl.effective_time
                    else None,
                    "published_date": (
                        entry.published_date.isoformat() if entry.published_date else None
                    ),
                },
            )
