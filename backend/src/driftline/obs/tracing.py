"""Tracing (spec section 11) through OpenTelemetry, exported to Langfuse's OTLP endpoint.

Zero cost by default: unless both DRIFTLINE_LANGFUSE_PUBLIC_KEY and
DRIFTLINE_LANGFUSE_SECRET_KEY are set (or an exporter is passed in), `build_tracer`
returns a NoopTracer and nothing leaves the process. The global OpenTelemetry provider
is never touched, so tests and processes do not share state.
"""

import base64
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter

from driftline.config import Settings
from driftline.llm.types import CompletionResult

AttrValue = str | bool | int | float


class SpanHandle(Protocol):
    def set(self, key: str, value: AttrValue | None) -> None: ...


class Tracer(Protocol):
    enabled: bool

    def span(self, name: str, **attributes: AttrValue | None) -> Any: ...

    def shutdown(self) -> None: ...


class _NoopSpan:
    def set(self, key: str, value: AttrValue | None) -> None:
        return None


class NoopTracer:
    enabled = False

    @contextmanager
    def span(self, name: str, **attributes: AttrValue | None) -> Iterator[_NoopSpan]:
        yield _NoopSpan()

    def shutdown(self) -> None:
        return None


class _OtelSpan:
    def __init__(self, span) -> None:
        self._span = span

    def set(self, key: str, value: AttrValue | None) -> None:
        if value is not None:
            self._span.set_attribute(key, value)


class OtelTracer:
    enabled = True

    def __init__(self, provider: TracerProvider) -> None:
        self._provider = provider
        self._tracer = provider.get_tracer("driftline")

    @contextmanager
    def span(self, name: str, **attributes: AttrValue | None) -> Iterator[_OtelSpan]:
        attrs = {k: v for k, v in attributes.items() if v is not None}
        with self._tracer.start_as_current_span(
            name, attributes=attrs, record_exception=True, set_status_on_exception=True
        ) as span:
            yield _OtelSpan(span)

    def shutdown(self) -> None:
        self._provider.shutdown()


def langfuse_otlp(settings: Settings) -> tuple[str, dict[str, str]]:
    """(endpoint, headers) for Langfuse's OTLP/HTTP trace ingestion (basic auth pk:sk)."""
    token = base64.b64encode(
        f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}".encode()
    ).decode()
    endpoint = f"{settings.langfuse_host.rstrip('/')}/api/public/otel/v1/traces"
    return endpoint, {"Authorization": f"Basic {token}"}


def build_tracer(settings: Settings, *, exporter: SpanExporter | None = None) -> Tracer:
    """OpenTelemetry tracer when Langfuse keys are set or an exporter is given, else no-op.

    A passed-in exporter is flushed synchronously (SimpleSpanProcessor); the Langfuse
    exporter batches in the background.
    """
    if exporter is None:
        if not (settings.langfuse_public_key and settings.langfuse_secret_key):
            return NoopTracer()
        endpoint, headers = langfuse_otlp(settings)
        processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, headers=headers))
    else:
        processor = SimpleSpanProcessor(exporter)
    provider = TracerProvider(resource=Resource.create({"service.name": "driftline"}))
    provider.add_span_processor(processor)
    return OtelTracer(provider)


def record_generation(span: SpanHandle, result: CompletionResult, cost_usd: float) -> None:
    """GenAI semantic-convention attributes Langfuse maps onto a generation."""
    span.set("langfuse.observation.type", "generation")
    span.set("gen_ai.system", result.provider)
    span.set("gen_ai.request.model", result.model)
    span.set("gen_ai.usage.input_tokens", result.usage.input_tokens)
    span.set("gen_ai.usage.output_tokens", result.usage.output_tokens)
    span.set("gen_ai.usage.cost", cost_usd)
    span.set("driftline.degraded", result.degraded)
    span.set("driftline.latency_ms", result.latency_ms)
