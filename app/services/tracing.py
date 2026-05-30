"""OpenTelemetry distributed tracing for the claims pipeline."""

import os
from contextlib import contextmanager

try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False

_initialized = False


def init_tracing(service_name: str = "plum-claims-pipeline"):
    """Initialize OpenTelemetry tracing. Safe to call multiple times."""
    global _initialized
    if not OTEL_AVAILABLE or _initialized:
        return
    _initialized = True

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=f"{otlp_endpoint}/v1/traces")
            provider.add_span_processor(BatchSpanProcessor(exporter))
        except Exception:
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    elif os.environ.get("OTEL_TRACE_CONSOLE"):
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)


def get_tracer(name: str = "plum.claims"):
    if not OTEL_AVAILABLE:
        return _NoopTracer()
    init_tracing()
    return trace.get_tracer(name)


@contextmanager
def agent_span(agent_name: str, claim_id: str | None = None):
    """Context manager that creates a span for an agent execution."""
    tracer = get_tracer()
    attributes = {"agent.name": agent_name}
    if claim_id:
        attributes["claim.id"] = claim_id

    if OTEL_AVAILABLE:
        with tracer.start_as_current_span(
            f"agent.{agent_name}",
            attributes=attributes,
        ) as span:
            yield span
    else:
        yield _NoopSpan()


@contextmanager
def pipeline_span(claim_id: str):
    """Top-level span for the entire pipeline execution."""
    tracer = get_tracer()
    if OTEL_AVAILABLE:
        with tracer.start_as_current_span(
            "claims.pipeline",
            attributes={"claim.id": claim_id},
        ) as span:
            yield span
    else:
        yield _NoopSpan()


class _NoopSpan:
    def set_attribute(self, key, value):
        pass

    def set_status(self, status):
        pass

    def add_event(self, name, attributes=None):
        pass

    def record_exception(self, exc):
        pass


class _NoopTracer:
    def start_as_current_span(self, name, **kwargs):
        return _noop_context()

    @contextmanager
    def start_span(self, name, **kwargs):
        yield _NoopSpan()


@contextmanager
def _noop_context():
    yield _NoopSpan()
