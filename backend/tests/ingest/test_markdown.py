from driftline.ingest.markdown import parse_markdown


def paths(doc) -> list[str]:
    return [s.path for s in doc.sections]


def test_front_matter_title_and_preamble():
    doc = parse_markdown(
        '---\ntitle: "Deprecated API Migration Guide"\nweight: 45\n---\n\n'
        "Intro text.\n\n## Removed APIs\n\nBody.\n"
    )
    assert doc.title == "Deprecated API Migration Guide"
    assert doc.front_matter["weight"] == 45
    assert paths(doc) == ["", "Removed APIs"]
    assert doc.sections[0].text == "Intro text."


def test_heading_paths_nest_and_pop():
    doc = parse_markdown("# Guide\n\n## A\n\na\n\n### A1\n\na1\n\n## B\n\nb\n")
    assert paths(doc) == ["Guide", "Guide > A", "Guide > A > A1", "Guide > B"]
    assert doc.title == "Guide"
    assert doc.sections[0].text == ""


def test_headings_inside_fences_are_ignored():
    doc = parse_markdown("## Run\n\n```shell\n# not a heading\nkubectl get pods\n```\n")
    assert paths(doc) == ["Run"]
    assert "# not a heading" in doc.sections[0].text


def test_hugo_anchor_and_html_comments_are_stripped():
    doc = parse_markdown(
        "<!-- overview -->\n### v1.29\n\n"
        "#### Flow control resources {#flowcontrol-resources-v129}\n\nText.\n"
    )
    assert paths(doc) == ["v1.29", "v1.29 > Flow control resources"]
    assert doc.sections[1].text == "Text."


def test_duplicate_headings_get_suffixes():
    doc = parse_markdown("## Notes\n\none\n\n## Notes\n\ntwo\n")
    assert paths(doc) == ["Notes", "Notes [2]"]


def test_malformed_front_matter_is_ignored():
    doc = parse_markdown("---\ntitle: [unclosed\n---\n# Real title\n\nbody\n")
    assert doc.front_matter == {}
    assert doc.title == "Real title"
