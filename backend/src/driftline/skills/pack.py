"""Domain skill packs (spec section 5): versioned directories `skills/<name>@<semver>/`.

    config.yaml      name, version, description, retrieval, chunking, prompt fragment paths
    glossary.yaml    term -> short definition
    prompts/*.md     fragments appended to the plan / draft prompts (named in config.yaml)
    eval.jsonl       seed eval cases (P7 fills in expected versions from real data)

Loading is strict: unknown keys, bad YAML, a missing fragment or a malformed eval case
raise `PackError` naming the file, so a broken pack fails when the worker starts
(`load_all`), never while a question is being answered.

A job's pack travels in a context variable (`use_pack`): the agent worker sets it around
one run, and the prompt builders, the retriever and the reranker read it when no pack is
passed explicitly. With no pack active, nothing changes.
"""

import json
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

logger = logging.getLogger(__name__)

DEFAULT_PACK = "generic@1.0.0"
PROMPT_KINDS = ("plan", "draft")
SPEC = re.compile(r"^(?P<name>[a-z0-9][a-z0-9-]*)@(?P<version>\d+\.\d+\.\d+)$")
_STRICT = ConfigDict(extra="forbid", frozen=True)


class PackError(ValueError):
    """A skill pack is missing or malformed; the message names the offending file."""


class PackNotFound(PackError):
    pass


class RetrievalParams(BaseModel):
    model_config = _STRICT

    candidates: int = Field(30, ge=1, le=500)  # per search (vector, text) before fusion
    rerank_top_n: int = Field(8, ge=1, le=100)  # at most this many chunks kept after rerank
    rrf_k: int = Field(60, ge=1, le=1000)  # reciprocal-rank fusion constant


class ChunkingParams(BaseModel):
    model_config = _STRICT

    chunk_tokens: int = Field(256, ge=32, le=4096)
    overlap_tokens: int = Field(32, ge=0)

    @model_validator(mode="after")
    def _overlap_below_size(self) -> "ChunkingParams":
        if self.overlap_tokens >= self.chunk_tokens:
            raise ValueError("overlap_tokens must be < chunk_tokens")
        return self


class _Config(BaseModel):
    """config.yaml as written on disk."""

    model_config = _STRICT

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    description: str = ""
    retrieval: RetrievalParams = RetrievalParams()
    chunking: ChunkingParams = ChunkingParams()
    prompts: dict[Literal["plan", "draft"], str] = {}


class EvalCase(BaseModel):
    """One eval.jsonl line. A `seed` case is a template: it has no expected versions yet."""

    model_config = _STRICT

    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    as_of: str | None = None
    kind: Literal["point_in_time", "current", "change", "comparison", "not_in_corpus"]
    expected_version_ids: list[str] = []
    status: Literal["seed", "ready"]
    notes: str = ""

    @model_validator(mode="after")
    def _seed_has_no_answers(self) -> "EvalCase":
        if self.status == "seed" and self.expected_version_ids:
            raise ValueError("a seed case must leave expected_version_ids empty")
        if (
            self.status == "ready"
            and self.kind != "not_in_corpus"
            and not self.expected_version_ids
        ):
            raise ValueError("a ready case needs expected_version_ids")
        return self


class SkillPack(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    version: str
    description: str = ""
    retrieval: RetrievalParams = RetrievalParams()
    chunking: ChunkingParams = ChunkingParams()
    glossary: dict[str, str] = {}
    prompts: dict[str, str] = {}
    eval_path: Path

    @property
    def spec(self) -> str:
        return f"{self.name}@{self.version}"


def _where(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


def _yaml(path: Path) -> object:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PackError(f"{_where(path)}: file is missing") from None
    except yaml.YAMLError as exc:
        raise PackError(f"{_where(path)}: invalid YAML: {exc}") from None


def _errors(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}" for e in exc.errors()
    )


def _load_glossary(path: Path) -> dict[str, str]:
    data = _yaml(path)
    if not isinstance(data, dict) or not data:
        raise PackError(f"{_where(path)}: must be a non-empty mapping of term -> definition")
    for term, definition in data.items():
        if not isinstance(term, str) or not isinstance(definition, str) or not definition.strip():
            raise PackError(f"{_where(path)}: {term!r} needs a non-empty string definition")
    return {term: " ".join(definition.split()) for term, definition in data.items()}


def _check_eval(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        raise PackError(f"{_where(path)}: file is missing") from None
    seen: set[str] = set()
    for n, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            case = EvalCase.model_validate(json.loads(line))
        except json.JSONDecodeError as exc:
            raise PackError(f"{_where(path)}:{n}: invalid JSON: {exc}") from None
        except ValidationError as exc:
            raise PackError(f"{_where(path)}:{n}: {_errors(exc)}") from None
        if case.id in seen:
            raise PackError(f"{_where(path)}:{n}: duplicate id {case.id!r}")
        seen.add(case.id)


def load_pack(path: Path | str) -> SkillPack:
    """Load and validate one pack directory; raises PackError naming the bad file."""
    path = Path(path)
    if not path.is_dir():
        raise PackNotFound(f"{path.name}: no such skill pack directory")
    config_path = path / "config.yaml"
    raw = _yaml(config_path)
    if not isinstance(raw, dict):
        raise PackError(f"{_where(config_path)}: must be a mapping")
    try:
        config = _Config.model_validate(raw)
    except ValidationError as exc:
        raise PackError(f"{_where(config_path)}: {_errors(exc)}") from None
    spec = f"{config.name}@{config.version}"
    if path.name != spec:
        raise PackError(
            f"{_where(config_path)}: declares {spec} but lives in directory {path.name}"
        )
    prompts = {}
    for kind, rel in config.prompts.items():
        fragment = (path / rel).resolve()
        if not fragment.is_relative_to(path.resolve()):
            raise PackError(f"{_where(config_path)}: prompt {rel} is outside the pack")
        try:
            text = fragment.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            raise PackError(f"{path.name}/{rel}: prompt fragment file is missing") from None
        if not text:
            raise PackError(f"{path.name}/{rel}: prompt fragment is empty")
        prompts[kind] = text
    eval_path = path / "eval.jsonl"
    _check_eval(eval_path)
    return SkillPack(
        name=config.name,
        version=config.version,
        description=config.description,
        retrieval=config.retrieval,
        chunking=config.chunking,
        glossary=_load_glossary(path / "glossary.yaml"),
        prompts=prompts,
        eval_path=eval_path,
    )


def resolve_pack(root: Path | str, spec: str) -> SkillPack:
    """The pack `name@x.y.z` under `root`; PackNotFound if the spec is malformed or absent."""
    if not SPEC.match(spec or ""):
        raise PackNotFound(f"{spec!r}: not a skill pack spec (expected name@x.y.z)")
    return load_pack(Path(root) / spec)


def load_all(root: Path | str) -> dict[str, SkillPack]:
    """Every pack under `root`, validated (run at worker start-up so errors surface early).
    The default pack must be among them."""
    root = Path(root)
    packs = {
        d.name: load_pack(d)
        for d in sorted(root.iterdir())
        if d.is_dir() and not d.name.startswith(".")
    }
    if DEFAULT_PACK not in packs:
        raise PackError(f"{root.name}/{DEFAULT_PACK}: the default skill pack is missing")
    return packs


@lru_cache(maxsize=64)
def _cached(root: Path, spec: str) -> SkillPack:
    return resolve_pack(root, spec)


def tenant_pack(root: Path | str, spec: str | None) -> SkillPack:
    """The tenant's pack (cached). An unknown or malformed spec falls back to the default
    pack with a warning; a tenant without a pack gets the default silently."""
    root = Path(root).resolve()
    if spec:
        try:
            return _cached(root, spec)
        except PackNotFound:
            logger.warning("skill pack %r not found; falling back to %s", spec, DEFAULT_PACK)
    return _cached(root, DEFAULT_PACK)


_ACTIVE: ContextVar[SkillPack | None] = ContextVar("driftline_skill_pack", default=None)


def active_pack() -> SkillPack | None:
    """The pack of the job running in this context, or None."""
    return _ACTIVE.get()


@contextmanager
def use_pack(pack: SkillPack | None) -> Iterator[SkillPack | None]:
    token = _ACTIVE.set(pack)
    try:
        yield pack
    finally:
        _ACTIVE.reset(token)
