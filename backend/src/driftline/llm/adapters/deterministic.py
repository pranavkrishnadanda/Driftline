import hashlib
import math

from driftline.clock import Clock, SystemClock
from driftline.llm.types import CompletionRequest, CompletionResult, Role, Usage


class DeterministicAdapter:
    """A real in-process provider with deterministic output and scriptable failures.

    Used by benchmarks (to measure the system, not provider quota) and to exercise
    routing failure paths. It is product code, not a test double.
    """

    def __init__(
        self,
        name: str = "deterministic",
        *,
        latency_ms: float = 0.0,
        script: list[Exception | None] | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.name = name
        self.latency_ms = latency_ms
        self.calls: list[str] = []
        self._script = list(script or [])
        self._clock = clock or SystemClock()

    async def _step(self, model: str) -> None:
        self.calls.append(model)
        if self._script:
            outcome = self._script.pop(0)
            if outcome is not None:
                raise outcome
        if self.latency_ms:
            await self._clock.sleep(self.latency_ms / 1000)

    async def complete(self, model: str, request: CompletionRequest) -> CompletionResult:
        await self._step(model)
        prompt = next((m.content for m in reversed(request.messages) if m.role is Role.user), "")
        text = f"[{model}] {prompt}"
        return CompletionResult(
            text=text,
            model=model,
            provider=self.name,
            usage=Usage(input_tokens=len(prompt.split()), output_tokens=len(text.split())),
            latency_ms=self.latency_ms,
        )

    async def embed(self, model: str, texts: list[str], dim: int) -> list[list[float]]:
        await self._step(model)
        return [_vector(t, dim) for t in texts]


def _vector(text: str, dim: int) -> list[float]:
    digest = hashlib.sha256(text.encode()).digest()
    values = [(digest[i % len(digest)] ^ (i * 31 % 256)) / 255.0 - 0.5 for i in range(dim)]
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]
