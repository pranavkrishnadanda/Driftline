"""P7 eval metrics (spec section 12): pure functions over per-case outcomes, no I/O.

The runner resolves every citation against the database (the cited version's window and
the cited chunk's text) and runs the verifier on every claim; these functions only count.

Definitions (citation metrics are pooled over all citations of the scored cases, so an
answer with three citations weighs three times as much as one with one):
- citation_precision: citations that count / all citations. A citation counts only if
  its version was in force at the case's as_of (window [valid_from, valid_to), not yet
  replaced by an applied supersedes/deprecates relation) AND its quote is supported by
  the cited chunk of that version (`quote_supported`, the guardrail's own check).
  Partial overlap with the chunk does not count.
- outdated_citation_rate: citations of a real version that was NOT in force at as_of
  (superseded, replaced or not yet in force) / all citations. A citation of a version
  that does not exist is imprecise but not outdated.
- faithfulness: supported claims / all presented claims, from the verifier's claim
  results; `judged=True` uses the optional LLM-judge sample instead.
- insufficient_evidence_accuracy: cases where "insufficient evidence" was answered
  exactly when the case expects it (not_in_corpus) / all scored cases. A refusal is
  neither an answer nor insufficient evidence, so it is wrong either way.
- latency_p95: nearest-rank 95th percentile of per-case latency (ms).
- cost_per_answer: mean cost (USD) per scored case.
A metric with nothing to measure (e.g. precision with no citations) is None, and
`aggregate` leaves it out rather than reporting a made-up 0 or 1.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from driftline.agents.guardrails import quote_supported


@dataclass(frozen=True)
class VersionWindow:
    """When a version was in force: [valid_from, valid_to), and no longer from the moment
    an applied supersedes/deprecates relation of another document took effect."""

    valid_from: datetime
    valid_to: datetime | None = None
    superseded_from: datetime | None = None

    def in_force_at(self, when: datetime) -> bool:
        if when < self.valid_from:
            return False
        if self.valid_to is not None and when >= self.valid_to:
            return False
        return self.superseded_from is None or when < self.superseded_from


@dataclass(frozen=True)
class ScoredCitation:
    """One citation as the system gave it, resolved against the database.

    `version_id` is None when the cited id is not a UUID. `window` is None when the
    tenant has no such version. `chunk_text` is the cited chunk's text, or None when
    that chunk does not exist or is not a chunk of the cited version."""

    version_id: UUID | None
    quote: str
    window: VersionWindow | None
    chunk_text: str | None


@dataclass(frozen=True)
class CaseOutcome:
    """What one scored case contributes to the metrics."""

    as_of: datetime
    citations: Sequence[ScoredCitation] = ()
    claims_supported: Sequence[bool] = ()  # the verifier's result per presented claim
    judged: Sequence[bool] = ()  # LLM-judge entailment for the sampled claims
    expects_insufficient: bool = False  # a not_in_corpus case
    answer_status: str = "answered"
    trap: bool = False
    latency_ms: float = 0.0
    cost_usd: float = 0.0


def citation_counts(citation: ScoredCitation, as_of: datetime) -> bool:
    """In force at as_of AND the quote is supported by the cited chunk of that version."""
    return (
        citation.window is not None
        and citation.window.in_force_at(as_of)
        and citation.chunk_text is not None
        and quote_supported(citation.quote, citation.chunk_text)
    )


def is_outdated(citation: ScoredCitation, as_of: datetime) -> bool:
    """A real version that was not in force at as_of."""
    return citation.window is not None and not citation.window.in_force_at(as_of)


def _ratio(hits: int, total: int) -> float | None:
    return hits / total if total else None


def citation_precision(cases: Sequence[CaseOutcome]) -> float | None:
    pairs = [(c, case.as_of) for case in cases for c in case.citations]
    return _ratio(sum(citation_counts(c, when) for c, when in pairs), len(pairs))


def outdated_citation_rate(cases: Sequence[CaseOutcome]) -> float | None:
    pairs = [(c, case.as_of) for case in cases for c in case.citations]
    return _ratio(sum(is_outdated(c, when) for c, when in pairs), len(pairs))


def faithfulness(cases: Sequence[CaseOutcome], *, judged: bool = False) -> float | None:
    results = [r for case in cases for r in (case.judged if judged else case.claims_supported)]
    return _ratio(sum(results), len(results))


def insufficient_evidence_accuracy(cases: Sequence[CaseOutcome]) -> float | None:
    right = sum(
        (case.answer_status == "insufficient_evidence")
        if case.expects_insufficient
        else (case.answer_status == "answered")
        for case in cases
    )
    return _ratio(right, len(cases))


def latency_p95(latencies_ms: Sequence[float]) -> float | None:
    """Nearest rank: the ceil(0.95 * n)-th smallest value."""
    if not latencies_ms:
        return None
    ordered = sorted(latencies_ms)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def cost_per_answer(costs_usd: Sequence[float]) -> float | None:
    return sum(costs_usd) / len(costs_usd) if costs_usd else None


def aggregate(cases: Sequence[CaseOutcome]) -> dict[str, float]:
    """Every defined metric over the scored cases, plus the counts behind them."""
    traps = [c for c in cases if c.trap]
    values: dict[str, float | None] = {
        "citation_precision": citation_precision(cases),
        "outdated_citation_rate": outdated_citation_rate(cases),
        "trap_citation_precision": citation_precision(traps),
        "trap_outdated_citation_rate": outdated_citation_rate(traps),
        "faithfulness": faithfulness(cases),
        "faithfulness_judge": faithfulness(cases, judged=True),
        "insufficient_evidence_accuracy": insufficient_evidence_accuracy(cases),
        "latency_p95_ms": latency_p95([c.latency_ms for c in cases]),
        "cost_per_answer_usd": cost_per_answer([c.cost_usd for c in cases]),
        "scored": len(cases),
        "citations": sum(len(c.citations) for c in cases),
        "claims": sum(len(c.claims_supported) for c in cases),
        "claims_judged": sum(len(c.judged) for c in cases),
    }
    return {name: float(v) for name, v in values.items() if v is not None}


# The CI gate (spec section 12), in points on the 0..1 scale.
MAX_PRECISION_DROP = 0.02
MAX_OUTDATED_RISE = 0.01
_EPS = 1e-9  # 0.90 - 0.88 is 0.0200000000000001 in floating point: still within the gate


def gate(base: Mapping[str, float], head: Mapping[str, float]) -> list[str]:
    """Why `head` regressed against `base` (empty: it passes). A gated metric the base
    has but the head lacks is a failure; one the base never had has nothing to gate."""
    failures = []
    for name, limit, sign in (
        ("citation_precision", MAX_PRECISION_DROP, -1.0),
        ("outdated_citation_rate", MAX_OUTDATED_RISE, 1.0),
    ):
        if name not in base:
            continue
        if name not in head:
            failures.append(f"{name}: missing from the head run (base {base[name]:.4f})")
            continue
        change = sign * (head[name] - base[name])
        if change > limit + _EPS:
            direction = "dropped" if sign < 0 else "rose"
            failures.append(
                f"{name} {direction} by {change * 100:.2f} points "
                f"({base[name]:.4f} -> {head[name]:.4f}; limit {limit * 100:.0f})"
            )
    return failures
