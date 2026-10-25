"""The one place the answer graph calls models: every call is traced and costed."""

from uuid import UUID

from pydantic import BaseModel

from driftline.llm.router import LLMRouter
from driftline.llm.types import CompletionRequest, CompletionResult, DeltaHandler
from driftline.obs.cost import CostLedger
from driftline.obs.tracing import NoopTracer, Tracer, record_generation


class AgentLLM:
    def __init__(
        self, router: LLMRouter, *, ledger: CostLedger | None = None, tracer: Tracer | None = None
    ) -> None:
        self.router = router
        self._ledger = ledger
        self._tracer = tracer or NoopTracer()

    async def _account(
        self, span, result: CompletionResult, *, node: str, tier: str, job_id, tenant_id
    ) -> None:
        cost = 0.0
        if self._ledger is not None:
            cost = float(
                await self._ledger.record(
                    result, node=node, tier=tier, job_id=job_id, tenant_id=tenant_id
                )
            )
        record_generation(span, result, cost)

    async def structured[M: BaseModel](
        self,
        request: CompletionRequest,
        output: type[M],
        *,
        node: str,
        tier: str,
        job_id: UUID | None,
        tenant_id: UUID | None,
        on_delta: DeltaHandler | None = None,
    ) -> tuple[M, CompletionResult]:
        with self._tracer.span(f"llm.{node}", node=node, tier=tier) as span:
            parsed, result = await self.router.structured(tier, request, output, on_delta=on_delta)
            await self._account(
                span, result, node=node, tier=tier, job_id=job_id, tenant_id=tenant_id
            )
            return parsed, result
