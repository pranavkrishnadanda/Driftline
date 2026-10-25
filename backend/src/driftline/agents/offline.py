"""ExtractiveResponder: a deterministic, offline policy for the answer graph's prompts.

Plugged into DeterministicAdapter (`responder=`), it answers the plan, draft and judge
prompts from the prompt text alone: it splits multi-part questions, cites the first
sentence of the evidence chunks that share the most words with the question, and judges
entailment by word overlap. No network and no cost, so benchmarks (P7) and the offline
mode (`DRIFTLINE_LLM_OFFLINE=true`) run the whole graph for real. It is product code; it
is deliberately simple and is not expected to match a real model's quality.
"""

import json
import re

from driftline.agents.prompts import (
    DRAFT_SCHEMA,
    JUDGE_SCHEMA,
    PLAN_SCHEMA,
    extract_tag,
    last_user_message,
    parse_evidence_block,
)
from driftline.ingest.chunker import is_instruction_like
from driftline.llm.types import CompletionRequest

_WORD = re.compile(r"[a-z0-9][a-z0-9.\-]*[a-z0-9]|[a-z0-9]")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_SPLIT = re.compile(r"\s*;\s*|\s+and also\s+", re.IGNORECASE)
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "should",
        "that",
        "the",
        "their",
        "then",
        "there",
        "these",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
    ]
)
MAX_CLAIMS = 3


def words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS}


def first_sentence(text: str) -> str:
    lines = [line.removeprefix("> ") for line in text.strip().splitlines()]
    return _SENTENCE.split(" ".join(lines).strip(), maxsplit=1)[0]


class ExtractiveResponder:
    def __call__(self, model: str, request: CompletionRequest) -> str:
        prompt = last_user_message(request)
        if request.schema_name == PLAN_SCHEMA:
            return json.dumps(self.plan(extract_tag(prompt, "question") or ""))
        if request.schema_name == DRAFT_SCHEMA:
            return json.dumps(self.draft(extract_tag(prompt, "question") or "", prompt))
        if request.schema_name == JUDGE_SCHEMA:
            claim = extract_tag(prompt, "claim") or ""
            quote = extract_tag(prompt, "quote") or ""
            return json.dumps(self.judge(claim, quote))
        return f"[{model}] {prompt}"

    def plan(self, question: str) -> dict:
        parts = [p.strip(" ?") + "?" for p in _SPLIT.split(question) if p.strip(" ?")]
        if len(parts) <= 1:
            return {"mode": "single", "sub_questions": [{"question": question, "as_of": None}]}
        return {
            "mode": "fan_out",
            "sub_questions": [{"question": p, "as_of": None} for p in parts[:4]],
        }

    def draft(self, question: str, prompt: str) -> dict:
        wanted = words(question)
        scored = []
        for n, chunk in enumerate(parse_evidence_block(prompt)):
            if chunk.get("quoted") == "true" or is_instruction_like(chunk["text"]):
                continue  # never build an answer out of instruction-like text
            sentence = first_sentence(chunk["text"])
            overlap = len(wanted & words(chunk["text"]))
            if sentence and overlap:
                scored.append((-overlap, n, sentence, chunk))
        scored.sort()
        claims, seen = [], set()
        for _, _, sentence, chunk in scored:
            if sentence in seen:
                continue
            seen.add(sentence)
            claims.append(
                {
                    "text": sentence,
                    "citations": [
                        {
                            "chunk_id": chunk["chunk_id"],
                            "version_id": chunk["version_id"],
                            "quote": sentence,
                        }
                    ],
                }
            )
            if len(claims) == MAX_CLAIMS:
                break
        answer = " ".join(c["text"] for c in claims)
        return {"answer": answer, "claims": claims}

    def judge(self, claim: str, quote: str) -> dict:
        claimed = words(claim)
        if not claimed:
            return {"entailed": False, "reason": "empty claim"}
        covered = len(claimed & words(quote)) / len(claimed)
        return {"entailed": covered >= 0.8, "reason": f"{covered:.0%} of the claim's words"}
