"""Guardrails for the answer graph (spec section 5): input screening, as-of parsing, and
the deterministic half of citation verification (the LLM judge is the other half)."""

import calendar
import re
import unicodedata
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher

from driftline.agents.schemas import Citation, DraftCitation, DraftClaim
from driftline.ingest.chunker import is_instruction_like
from driftline.retrieval.types import Evidence

_EXTRA_INJECTION = re.compile(
    r"\b(reveal|print|show|repeat)\b.{0,40}\b(system prompt|instructions|api key|secret)"
    r"|\bact as\b.{0,30}\b(unrestricted|jailbroken|dan)\b",
    re.IGNORECASE,
)
_VERSION = re.compile(r"\b(?:v|kubernetes\s+|k8s\s+)(\d+)\.(\d+)(?:\.\d+)?\b", re.IGNORECASE)
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS |= {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m} | {"sept": 9}
_MONTH_YEAR = re.compile(
    r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?\s+((?:19|20)\d{2})\b",
    re.IGNORECASE,
)
# "in 2000 patients" or "by 2010 mg" is a count or a dose, not a year.
_NOT_A_YEAR = (
    r"(?!\s*(?:%|(?:patients?|people|persons?|subjects?|participants?|cases?|tablets?"
    r"|capsules?|doses?|units?|mg|mcg|µg|ug|g|kg|ml|l|iu)\b))"
)
_BEFORE_YEAR = re.compile(r"\bbefore\s+((?:19|20)\d{2})\b" + _NOT_A_YEAR, re.IGNORECASE)
_YEAR = re.compile(
    r"\b(?:as of|in|since|after|during|by|until)\s+((?:19|20)\d{2})\b" + _NOT_A_YEAR,
    re.IGNORECASE,
)
_QUOTE_PREFIX = re.compile(r"^\s*>\s?", re.MULTILINE)
_PUNCT = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})
# A quote shorter than this (normalised) supports nothing, however exact: "ALT" or
# "Check" occur in many chunks and would let any claim pass the deterministic check.
MIN_QUOTE_CHARS = 10
MIN_FUZZY_CHARS = 20
_EOD = timedelta(days=1) - timedelta(microseconds=1)


def screen_question(question: str) -> str | None:
    """A reason to refuse, when the question tries to steer the model instead of asking."""
    if is_instruction_like(question) or _EXTRA_INJECTION.search(question):
        return "prompt_injection"
    return None


@dataclass(frozen=True)
class AsOfHint:
    """What the question says about time: a date, a release, or nothing."""

    as_of: datetime | None = None
    version_key: str | None = None  # e.g. "release-1.28" (the K8s connector's version key)
    source: str = "default"


def _end_of_day(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=UTC) + _EOD


def extract_as_of_hint(question: str) -> AsOfHint:
    """Dates resolve to the END of the named day, month or year (so versions effective
    that day count); 'before 2024' resolves to the end of 2023."""
    if m := _VERSION.search(question):
        return AsOfHint(
            version_key=f"release-{int(m.group(1))}.{int(m.group(2))}", source="version"
        )
    if m := _ISO_DATE.search(question):
        try:
            return AsOfHint(_end_of_day(*map(int, m.groups())), source="date")
        except ValueError:
            pass  # not a real date (2024-13-45, 0000-01-01): look for other hints
    if m := _MONTH_YEAR.search(question):
        month, year = _MONTHS[m.group(1).lower()], int(m.group(2))
        return AsOfHint(
            _end_of_day(year, month, calendar.monthrange(year, month)[1]), source="month"
        )
    if m := _BEFORE_YEAR.search(question):
        return AsOfHint(_end_of_day(int(m.group(1)) - 1, 12, 31), source="before_year")
    if m := _YEAR.search(question):
        return AsOfHint(_end_of_day(int(m.group(1)), 12, 31), source="year")
    return AsOfHint()


def clamp_as_of(as_of: datetime, now: datetime) -> datetime:
    """Nothing is known about the future: later dates mean 'now'."""
    if as_of.tzinfo is None or now.tzinfo is None:
        raise ValueError("as_of and now must be timezone-aware")
    return min(as_of, now)


def _normalise(text: str) -> tuple[str, list[int], str]:
    """(normalised, offsets, source): NFC, curly punctuation made straight, lower case,
    whitespace runs collapsed to one space and trimmed. `offsets[i]` is the index in
    `source` (the NFC text) that normalised character i came from, so a match can be
    mapped back to the chunk's own words."""
    source = unicodedata.normalize("NFC", text)
    out: list[str] = []
    offsets: list[int] = []
    space_at: int | None = None
    for i, ch in enumerate(source):
        if ch.isspace():
            if space_at is None:
                space_at = i
            continue
        if space_at is not None and out:
            out.append(" ")
            offsets.append(space_at)
        space_at = None
        for c in ch.translate(_PUNCT).lower():
            out.append(c)
            offsets.append(i)
    return "".join(out), offsets, source


def _norm(text: str) -> str:
    return _normalise(text)[0]


def _fuzzy_span(t: str, q: str, min_ratio: float) -> tuple[int, int] | None:
    """The span of `t` best aligned with `q`, when its similarity ratio is >= min_ratio."""
    longest = SequenceMatcher(None, t, q, autojunk=False).find_longest_match(0, len(t), 0, len(q))
    if longest.size == 0:
        return None
    slack = len(q) // 10 + 1
    lo = max(0, longest.a - longest.b - slack)
    hi = min(len(t), longest.a - longest.b + len(q) + slack)
    blocks = [
        b
        for b in SequenceMatcher(None, t[lo:hi], q, autojunk=False).get_matching_blocks()
        if b.size
    ]
    start, end = lo + blocks[0].a, lo + blocks[-1].a + blocks[-1].size
    if SequenceMatcher(None, t[start:end], q, autojunk=False).ratio() < min_ratio:
        return None
    return start, end


def locate_quote(quote: str, text: str, *, min_ratio: float = 0.9) -> str | None:
    """The passage of `text` that `quote` cites, in the chunk's own words, or None.

    The quote must be at least MIN_QUOTE_CHARS long (normalised) and either an exact
    normalised substring, or (from MIN_FUZZY_CHARS on) a near-exact match: the best
    aligned span of `text` has a similarity ratio >= min_ratio. A `> ` quoting prefix
    (how untrusted text is shown) is ignored. Returning the source span, not the model's
    quote, means a near-exact paraphrase (a dropped "not") is never stored or judged."""
    q = _norm(_QUOTE_PREFIX.sub("", quote))
    if len(q) < MIN_QUOTE_CHARS:
        return None
    t, offsets, source = _normalise(text)
    start = t.find(q)
    if start >= 0:
        span: tuple[int, int] | None = (start, start + len(q))
    elif len(q) >= MIN_FUZZY_CHARS:
        span = _fuzzy_span(t, q, min_ratio)
    else:
        span = None
    if span is None:
        return None
    return source[offsets[span[0]] : offsets[span[1] - 1] + 1].strip()


def quote_supported(quote: str, text: str, *, min_ratio: float = 0.9) -> bool:
    """See `locate_quote`."""
    return locate_quote(quote, text, min_ratio=min_ratio) is not None


@dataclass(frozen=True)
class CitationCheck:
    ok: bool
    reason: str | None = None
    citation: Citation | None = None


def check_citation(cited: DraftCitation, evidence: Mapping[str, Evidence]) -> CitationCheck:
    """The chunk must be one we retrieved, of the version claimed, in force at the as_of
    it was retrieved for, and must contain the quote. The passing citation carries the
    chunk's own words for the quote (see `locate_quote`)."""
    item = evidence.get(cited.chunk_id.strip().lower())
    if item is None:
        return CitationCheck(False, "unknown_chunk")
    if str(item.version_id) != cited.version_id.strip().lower():
        return CitationCheck(False, "version_mismatch")
    if not item.in_force_at(item.retrieved_as_of):
        return CitationCheck(False, "not_in_force")
    quote = locate_quote(cited.quote, item.text)
    if quote is None:
        return CitationCheck(False, "quote_not_found")
    return CitationCheck(True, None, Citation.from_evidence(item, quote))


Judge = Callable[[str, str], Awaitable[bool]]


@dataclass(frozen=True)
class ClaimCheck:
    supported: bool
    reason: str | None = None
    citations: list[Citation] = field(default_factory=list)


async def verify_claim(
    claim: DraftClaim, evidence: Mapping[str, Evidence], *, judge: Judge | None = None
) -> ClaimCheck:
    """Supported when at least one citation passes `check_citation` and (if a judge is
    given) the judge finds the claim entailed by the passing quotes."""
    if not claim.citations:
        return ClaimCheck(False, "no_citation")
    checks = [check_citation(c, evidence) for c in claim.citations]
    passing = [c.citation for c in checks if c.ok and c.citation is not None]
    if not passing:
        return ClaimCheck(False, checks[0].reason)
    if judge is not None and not await judge(claim.text, " ".join(c.quote for c in passing)):
        return ClaimCheck(False, "not_entailed", passing)
    return ClaimCheck(True, None, passing)


def evidence_index(items: Sequence[Evidence]) -> dict[str, Evidence]:
    return {str(e.chunk_id): e for e in items}
