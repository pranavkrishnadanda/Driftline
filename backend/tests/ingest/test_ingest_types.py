from datetime import UTC, datetime

import pytest

from driftline.ingest.types import (
    RawDocument,
    Section,
    SourceFetchError,
    normalize_text,
    render_content,
    unique_sections,
)


def _raw(**overrides) -> RawDocument:
    fields = {
        "external_id": "doc",
        "title": "Doc",
        "version_key": "1",
        "valid_from": datetime(2024, 1, 1, tzinfo=UTC),
        "content": "",
        "sections": (Section("A", "a"),),
        "raw_uri": "file:///doc",
    }
    fields.update(overrides)
    return RawDocument(**fields)


def test_raw_document_requires_aware_valid_from():
    with pytest.raises(ValueError, match="timezone-aware"):
        _raw(valid_from=datetime(2024, 1, 1))


def test_raw_document_rejects_duplicate_section_paths():
    with pytest.raises(ValueError, match="unique"):
        _raw(sections=(Section("A", "1"), Section("A", "2")))
    assert _raw().source_meta == {}


def test_unique_sections_suffixes_repeats():
    sections = unique_sections([("A", "1"), ("B", "2"), ("A", "3"), ("A", "4")])
    assert [s.path for s in sections] == ["A", "B", "A [2]", "A [3]"]
    assert sections[2].text == "3"


def test_render_content_joins_paths_and_text():
    text = render_content([Section("", "intro"), Section("A", ""), Section("B", "body")])
    assert text == "intro\n\nA\n\nB\nbody"


def test_normalize_text_collapses_whitespace_and_applies_nfc():
    assert normalize_text("  a \n\t b  ") == "a b"
    assert normalize_text("Café") == normalize_text("Café")


def test_source_fetch_error_carries_retryable_and_status():
    err = SourceFetchError("boom", retryable=True, status=503)
    assert (str(err), err.retryable, err.status) == ("boom", True, 503)
