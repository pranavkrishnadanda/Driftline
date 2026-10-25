import json

from driftline.llm.jsonstream import JsonStringFieldStreamer

DOC = {"answer": 'ALT "monthly"\nthen stop é \U0001f600 \\ done', "claims": [{"text": "x"}]}


def feed_all(text: str, size: int) -> str:
    s = JsonStringFieldStreamer("answer")
    return "".join(s.feed(text[i : i + size]) for i in range(0, len(text), size))


def test_decodes_field_for_every_delta_size():
    text = json.dumps(DOC)  # \u escapes for non-ASCII, including a surrogate pair
    for size in range(1, 12):
        assert feed_all(text, size) == DOC["answer"], size
    assert feed_all(json.dumps(DOC, ensure_ascii=False), 3) == DOC["answer"]


def test_field_need_not_be_first_and_stops_at_closing_quote():
    text = json.dumps({"claims": [{"text": 'say \\"answer\\": "no"'}], "answer": "yes"})
    s = JsonStringFieldStreamer("answer")
    assert "".join(s.feed(c) for c in text) == "yes"
    assert s.done
    assert s.feed('"more"') == ""


def test_missing_field_or_non_json_yields_nothing():
    s = JsonStringFieldStreamer("answer")
    assert s.feed("not json at all") == ""
    assert s.feed('{"claims": []}') == ""
    assert not s.done
