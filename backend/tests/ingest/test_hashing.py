import json

from driftline.ingest.hashing import content_hash, diff_sections, section_hashes
from driftline.ingest.types import Section


def test_whitespace_only_changes_hash_equal():
    assert content_hash([Section("A", "a  b\n c")]) == content_hash([Section("A", "a b c")])
    assert content_hash([Section("A", "a b c")]) != content_hash([Section("A", "a b d")])


def test_content_hash_depends_on_section_order_and_paths():
    a, b = Section("A", "x"), Section("B", "y")
    assert content_hash([a, b]) != content_hash([b, a])
    assert content_hash([Section("A", "x")]) != content_hash([Section("B", "x")])
    assert len(content_hash([a])) == 64


def test_section_hashes_keyed_by_path_in_order():
    hashes = section_hashes([Section("B", "x"), Section("A", "x")])
    assert list(hashes) == ["B", "A"]
    assert hashes["A"] == hashes["B"]


def test_diff_classifies_added_removed_changed_unchanged():
    prev = section_hashes([Section("keep", "1"), Section("edit", "2"), Section("gone", "3")])
    new = section_hashes([Section("keep", "1"), Section("edit", "2b"), Section("new", "4")])
    assert diff_sections(prev, new) == {
        "added": ["new"],
        "removed": ["gone"],
        "changed": ["edit"],
        "unchanged": ["keep"],
    }


def test_diff_from_nothing_marks_all_added_and_is_json_ready():
    diff = diff_sections(None, section_hashes([Section("b", "1"), Section("a", "2")]))
    assert diff == {"added": ["a", "b"], "removed": [], "changed": [], "unchanged": []}
    assert json.loads(json.dumps(diff)) == diff
