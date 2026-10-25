"""Cost accounting (spec section 4): tokens x price per call, persisted per job.

Prices are USD per million tokens (Anthropic first-party list prices, verified against
platform.claude.com/docs/en/about-claude/pricing on 2026-10-25). Local
models (TEI) and the in-process DeterministicAdapter cost nothing. A model with no
price is recorded at 0 and reported by `unpriced`, so a missing price is visible
instead of silently wrong.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

import asyncpg

from driftline.llm.types import CompletionResult


@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: Decimal
    output_per_mtok: Decimal
    # Some models charge more once a prompt exceeds a size (Haiku 5.5: above 100K tokens).
    long_threshold_tokens: int | None = None
    long_input_per_mtok: Decimal | None = None
    long_output_per_mtok: Decimal | None = None


PRICES: dict[str, ModelPrice] = {
    "claude-haiku-5-5": ModelPrice(
        Decimal("0.10"), Decimal("0.50"), 100_000, Decimal("0.50"), Decimal("2.50")
    ),
    "claude-sonnet-5-5": ModelPrice(Decimal("2.00"), Decimal("10.00")),
    "claude-opus-5-5": ModelPrice(Decimal("4.00"), Decimal("20.00")),
}
FREE_PROVIDERS = frozenset({"tei", "deterministic", "det"})
_MTOK = Decimal(1_000_000)
_CENT_FRACTION = Decimal("0.000001")


def call_cost(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    prices: dict[str, ModelPrice] = PRICES,
) -> Decimal | None:
    """USD for one call, rounded to 6 places; None when the model has no price."""
    if provider in FREE_PROVIDERS:
        return Decimal(0)
    price = prices.get(model)
    if price is None:
        return None
    rate_in, rate_out = price.input_per_mtok, price.output_per_mtok
    if price.long_threshold_tokens is not None and input_tokens > price.long_threshold_tokens:
        if price.long_input_per_mtok is not None:
            rate_in = price.long_input_per_mtok
        if price.long_output_per_mtok is not None:
            rate_out = price.long_output_per_mtok
    cost = (rate_in * input_tokens + rate_out * output_tokens) / _MTOK
    return cost.quantize(_CENT_FRACTION)


class CostLedger:
    """Writes one `llm_calls` row per completion and sums them per job."""

    def __init__(self, pool: asyncpg.Pool, *, prices: dict[str, ModelPrice] = PRICES) -> None:
        self._pool = pool
        self._prices = prices
        self.unpriced: set[str] = set()

    async def record(
        self,
        result: CompletionResult,
        *,
        node: str,
        tier: str,
        job_id: UUID | None,
        tenant_id: UUID | None,
    ) -> Decimal:
        cost = call_cost(
            result.provider,
            result.model,
            result.usage.input_tokens,
            result.usage.output_tokens,
            self._prices,
        )
        if cost is None:
            self.unpriced.add(result.model)
            cost = Decimal(0)
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO llm_calls (job_id, tenant_id, node, tier, provider, model, "
                "input_tokens, output_tokens, cost_usd, latency_ms, degraded) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
                job_id,
                tenant_id,
                node,
                tier,
                result.provider,
                result.model,
                result.usage.input_tokens,
                result.usage.output_tokens,
                cost,
                result.latency_ms,
                result.degraded,
            )
        return cost


@dataclass(frozen=True)
class JobCost:
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal


async def job_cost(conn: asyncpg.Connection, job_id: UUID) -> JobCost:
    row = await conn.fetchrow(
        "SELECT count(*) AS calls, coalesce(sum(input_tokens), 0) AS input_tokens, "
        "coalesce(sum(output_tokens), 0) AS output_tokens, "
        "coalesce(sum(cost_usd), 0) AS cost_usd FROM llm_calls WHERE job_id = $1",
        job_id,
    )
    return JobCost(
        row["calls"], int(row["input_tokens"]), int(row["output_tokens"]), Decimal(row["cost_usd"])
    )
