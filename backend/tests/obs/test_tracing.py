import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from driftline.config import Settings
from driftline.llm.types import CompletionResult, Usage
from driftline.obs.tracing import (
    NoopTracer,
    OtelTracer,
    build_tracer,
    langfuse_otlp,
    record_generation,
)


def test_tracing_is_a_noop_without_langfuse_keys():
    tracer = build_tracer(Settings(_env_file=None))
    assert isinstance(tracer, NoopTracer) and tracer.enabled is False
    with tracer.span("ask", job_id="j") as span:
        span.set("anything", 1)
    half = build_tracer(Settings(_env_file=None, langfuse_public_key="pk-lf-1"))
    assert isinstance(half, NoopTracer)  # both keys are required
    # Compose passes unset keys through as empty strings (`${VAR:-}`).
    empty = build_tracer(Settings(_env_file=None, langfuse_public_key="", langfuse_secret_key=""))
    assert isinstance(empty, NoopTracer)


def test_langfuse_exporter_targets_the_otlp_endpoint_with_basic_auth():
    settings = Settings(
        _env_file=None,
        langfuse_public_key="pk-lf-1",
        langfuse_secret_key="sk-lf-2",
        langfuse_host="http://langfuse:3000/",
    )
    endpoint, headers = langfuse_otlp(settings)
    assert endpoint == "http://langfuse:3000/api/public/otel/v1/traces"
    assert headers == {"Authorization": "Basic cGstbGYtMTpzay1sZi0y"}  # base64("pk-lf-1:sk-lf-2")
    tracer = build_tracer(settings)
    assert isinstance(tracer, OtelTracer) and tracer.enabled
    tracer.shutdown()


def test_spans_nest_and_carry_generation_attributes():
    exporter = InMemorySpanExporter()
    tracer = build_tracer(Settings(_env_file=None), exporter=exporter)
    result = CompletionResult(
        text="{}",
        model="claude-sonnet-5-5",
        provider="anthropic",
        usage=Usage(input_tokens=120, output_tokens=30),
        latency_ms=850.0,
        degraded=True,
    )
    with tracer.span("ask", job_id="job-1", tenant_id=None) as root:
        root.set("driftline.status", "answered")
        with tracer.span("llm.draft", node="draft") as span:
            record_generation(span, result, 0.00054)
    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert set(spans) == {"ask", "llm.draft"}
    assert spans["llm.draft"].parent.span_id == spans["ask"].context.span_id
    attrs = spans["llm.draft"].attributes
    assert attrs["gen_ai.request.model"] == "claude-sonnet-5-5"
    assert attrs["gen_ai.usage.input_tokens"] == 120
    assert attrs["gen_ai.usage.cost"] == pytest.approx(0.00054)
    assert attrs["driftline.degraded"] is True
    assert spans["ask"].attributes["job_id"] == "job-1"
    assert "tenant_id" not in spans["ask"].attributes  # None values are dropped
    assert spans["ask"].resource.attributes["service.name"] == "driftline"
    tracer.shutdown()


def test_exceptions_mark_the_span_as_error():
    exporter = InMemorySpanExporter()
    tracer = build_tracer(Settings(_env_file=None), exporter=exporter)
    with pytest.raises(RuntimeError), tracer.span("node.verify"):
        raise RuntimeError("judge unavailable")
    [span] = exporter.get_finished_spans()
    assert span.status.status_code is StatusCode.ERROR
    assert span.events[0].name == "exception"
    tracer.shutdown()
