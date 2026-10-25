"""Section-aware chunking with deterministic ordinals."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.utils import get_tokenizer

from driftline.ingest.types import INSTRUCTION_LIKE, Section

_INSTRUCTION_PATTERNS = re.compile(
    r"ignore (all |any )?(previous|prior|above) (instructions|prompts?)"
    r"|disregard (the |all )?(previous|prior|above)"
    r"|you are now\b"
    r"|system prompt"
    r"|<\s*/?\s*(system|assistant|instructions?)\s*>",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ChunkDraft:
    ord: int
    section_path: str
    text: str
    tags: tuple[str, ...] = ()


def count_tokens(text: str) -> int:
    """Tokens as LlamaIndex counts them (tiktoken cl100k_base, bundled offline)."""
    return len(get_tokenizer()(text))


def is_instruction_like(text: str) -> bool:
    return _INSTRUCTION_PATTERNS.search(text) is not None


@lru_cache(maxsize=8)
def _splitter(chunk_tokens: int, overlap_tokens: int) -> SentenceSplitter:
    return SentenceSplitter(chunk_size=chunk_tokens, chunk_overlap=overlap_tokens)


def chunk_sections(
    sections: Sequence[Section], *, chunk_tokens: int = 256, overlap_tokens: int = 32
) -> list[ChunkDraft]:
    """Split each section on its own (chunks never span sections); `ord` runs 0..n-1."""
    if not 0 <= overlap_tokens < chunk_tokens:
        raise ValueError("overlap_tokens must be >= 0 and < chunk_tokens")
    splitter = _splitter(chunk_tokens, overlap_tokens)
    drafts: list[ChunkDraft] = []
    for section in sections:
        for piece in splitter.split_text(section.text):
            piece = piece.strip()
            if not piece:
                continue
            tags = (INSTRUCTION_LIKE,) if is_instruction_like(piece) else ()
            drafts.append(ChunkDraft(len(drafts), section.path, piece, tags))
    return drafts
