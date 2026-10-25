"""LatencyStubAdapter: the benchmark LLM provider (`Settings.llm_bench`).

A real `LLMProvider`, not a mock: replies are deterministic (the responder, normally the
in-repo ExtractiveResponder, so structured answers stay valid for the answer graph), and
each call waits a latency drawn from a seeded log-normal distribution on the injected
clock. Benchmarks then measure the system, not a provider's quota. Reports must label
its numbers with `label` ("stub LLM").
"""

import math
import random
import re

from driftline.clock import Clock, SystemClock
from driftline.llm.adapters.deterministic import Responder, _vector
from driftline.llm.types import CompletionRequest, CompletionResult, DeltaHandler, Role, Usage

STUB_LABEL = "stub LLM"
# Share of the drawn latency spent before the first streamed delta (time to first token);
# the rest is spread evenly across the deltas.
FIRST_TOKEN_SHARE = 0.3
_PIECE = re.compile(r"\S+\s*|\s+")


def _last_user_message(request: CompletionRequest) -> str:
    return next((m.content for m in reversed(request.messages) if m.role is Role.user), "")


def _echo(model: str, request: CompletionRequest) -> str:
    return f"[{model}] {_last_user_message(request)}"


class LatencyStubAdapter:
    """Deterministic text with latency ~ LogNormal(ln(median_ms), sigma), in ms.

    The same `seed` gives the same sequence of latencies. Concurrent calls on one instance
    draw from one sequence in call order.
    """

    label = STUB_LABEL

    def __init__(
        self,
        seed: int,
        median_ms: float,
        sigma: float,
        clock: Clock | None = None,
        *,
        name: str = "bench",
        responder: Responder | None = None,
    ) -> None:
        if not median_ms > 0:
            raise ValueError(f"median_ms must be > 0, got {median_ms}")
        if not sigma >= 0:
            raise ValueError(f"sigma must be >= 0, got {sigma}")
        self.name = name
        self.seed = seed
        self.median_ms = float(median_ms)
        self.sigma = float(sigma)
        self.responder: Responder = responder or _echo
        self._clock = clock or SystemClock()
        self._rng = random.Random(seed)
        self._mu = math.log(self.median_ms)

    def next_delay_ms(self) -> float:
        """Draw the next latency (ms) from the seeded distribution."""
        return self._rng.lognormvariate(self._mu, self.sigma)

    def _result(
        self, model: str, request: CompletionRequest, text: str, delay_ms: float
    ) -> CompletionResult:
        return CompletionResult(
            text=text,
            model=model,
            provider=self.name,
            usage=Usage(
                input_tokens=len(_last_user_message(request).split()),
                output_tokens=len(text.split()),
            ),
            latency_ms=delay_ms,
        )

    async def complete(self, model: str, request: CompletionRequest) -> CompletionResult:
        delay_ms = self.next_delay_ms()
        text = self.responder(model, request)
        await self._clock.sleep(delay_ms / 1000)
        return self._result(model, request, text, delay_ms)

    async def stream(
        self, model: str, request: CompletionRequest, on_delta: DeltaHandler
    ) -> CompletionResult:
        """Stream `complete`'s reply one word (plus spacing) per delta. The drawn latency is
        spent as FIRST_TOKEN_SHARE before the first delta, the rest spread across deltas."""
        delay_ms = self.next_delay_ms()
        text = self.responder(model, request)
        pieces = _PIECE.findall(text)
        if not pieces:
            await self._clock.sleep(delay_ms / 1000)
            return self._result(model, request, text, delay_ms)
        first_s = delay_ms * FIRST_TOKEN_SHARE / 1000
        rest_s = (delay_ms / 1000 - first_s) / len(pieces)
        await self._clock.sleep(first_s)
        for n, piece in enumerate(pieces):
            if n:
                await self._clock.sleep(rest_s)
            await on_delta(piece)
        await self._clock.sleep(rest_s)  # the n-th gap: total sleep equals the drawn delay
        return self._result(model, request, text, delay_ms)

    async def embed(self, model: str, texts: list[str], dim: int) -> list[list[float]]:
        """Deterministic unit vectors, no latency. Bench routers embed through TEI."""
        return [_vector(t, dim) for t in texts]
