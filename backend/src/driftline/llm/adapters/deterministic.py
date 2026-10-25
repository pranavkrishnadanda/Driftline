import hashlib
import math
import re
from collections.abc import Callable
from dataclasses import dataclass

from driftline.clock import Clock, SystemClock
from driftline.llm.types import (
    CompletionRequest,
    CompletionResult,
    DeltaHandler,
    ProviderError,
    Role,
    Usage,
)

# A responder computes the reply text for a request (see driftline.agents.offline).
Responder = Callable[[str, CompletionRequest], str]
_PIECE = re.compile(r"\S+\s*|\s+")


@dataclass(frozen=True)
class FailMidStream:
    """Script entry: stream `after_deltas` deltas, then raise `error`."""

    after_deltas: int
    error: ProviderError


ScriptEntry = Exception | str | FailMidStream | None


class DeterministicAdapter:
    """A real in-process provider with deterministic output and scriptable outcomes.

    Used by benchmarks (to measure the system, not provider quota), by the offline
    mode (`Settings.llm_offline`), and to exercise routing failure paths. It is product
    code, not a test double.

    `script` entries are consumed one per call: an exception is raised, a string is
    returned as the reply text, a `FailMidStream` fails part-way through a stream, and
    `None` uses the normal reply. The normal reply is `responder(model, request)` when
    a responder is given, else `"[{model}] {last user message}"`.
    """

    def __init__(
        self,
        name: str = "deterministic",
        *,
        latency_ms: float = 0.0,
        script: list[ScriptEntry] | None = None,
        responder: Responder | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.name = name
        self.latency_ms = latency_ms
        self.calls: list[str] = []
        self.requests: list[CompletionRequest] = []
        self._script = list(script or [])
        self._responder = responder
        self._clock = clock or SystemClock()

    async def _step(self, model: str) -> ScriptEntry:
        self.calls.append(model)
        outcome = self._script.pop(0) if self._script else None
        if isinstance(outcome, Exception):
            raise outcome
        if self.latency_ms:
            await self._clock.sleep(self.latency_ms / 1000)
        return outcome

    def _reply(self, model: str, request: CompletionRequest, outcome: ScriptEntry) -> str:
        if isinstance(outcome, str):
            return outcome
        if self._responder is not None:
            return self._responder(model, request)
        prompt = next((m.content for m in reversed(request.messages) if m.role is Role.user), "")
        return f"[{model}] {prompt}"

    def _result(self, model: str, request: CompletionRequest, text: str) -> CompletionResult:
        prompt = next((m.content for m in reversed(request.messages) if m.role is Role.user), "")
        return CompletionResult(
            text=text,
            model=model,
            provider=self.name,
            usage=Usage(input_tokens=len(prompt.split()), output_tokens=len(text.split())),
            latency_ms=self.latency_ms,
        )

    async def complete(self, model: str, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        outcome = await self._step(model)
        if isinstance(outcome, FailMidStream):
            # A plain completion has no partial delivery: the scripted failure is total.
            raise outcome.error
        return self._result(model, request, self._reply(model, request, outcome))

    async def stream(
        self, model: str, request: CompletionRequest, on_delta: DeltaHandler
    ) -> CompletionResult:
        """Stream the same reply `complete` would give, one word (plus spacing) per delta."""
        self.requests.append(request)
        outcome = await self._step(model)
        text = self._reply(model, request, outcome)
        for n, piece in enumerate(_PIECE.findall(text)):
            if isinstance(outcome, FailMidStream) and n >= outcome.after_deltas:
                raise outcome.error
            await on_delta(piece)
        if isinstance(outcome, FailMidStream):
            # The reply was shorter than `after_deltas`: still fail, never succeed silently.
            raise outcome.error
        return self._result(model, request, text)

    async def embed(self, model: str, texts: list[str], dim: int) -> list[list[float]]:
        await self._step(model)
        return [_vector(t, dim) for t in texts]


def _vector(text: str, dim: int) -> list[float]:
    digest = hashlib.sha256(text.encode()).digest()
    values = [(digest[i % len(digest)] ^ (i * 31 % 256)) / 255.0 - 0.5 for i in range(dim)]
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]
