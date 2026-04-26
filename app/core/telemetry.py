import logging

import sentry_sdk
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_initialized = False


def init_telemetry() -> None:
    """Initialize OpenTelemetry tracing and Sentry error tracking.

    Safe to call multiple times — only the first call takes effect.
    Does nothing if no OTLP endpoint or Sentry DSN is configured.
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    settings = get_settings()

    _init_tracing(settings)
    _init_sentry(settings)
    _init_auto_instrumentation(settings)


def _init_tracing(settings) -> None:
    resource = Resource.create({
        "service.name": settings.otel_service_name,
        "deployment.environment": settings.environment,
    })

    provider = TracerProvider(resource=resource)

    if settings.otel_exporter_otlp_endpoint:
        headers = _parse_headers(settings.otel_exporter_otlp_headers)
        exporter = OTLPSpanExporter(
            endpoint=f"{settings.otel_exporter_otlp_endpoint}/v1/traces",
            headers=headers,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        logger.info("OTel tracing enabled → %s", settings.otel_exporter_otlp_endpoint)
    elif settings.environment == "development":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        logger.info("OTel tracing enabled → console (dev mode)")
    else:
        logger.info("OTel tracing disabled (no OTLP endpoint configured)")

    trace.set_tracer_provider(provider)


def _init_sentry(settings) -> None:
    if not settings.sentry_dsn:
        logger.info("Sentry disabled (no DSN configured)")
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=0.1,
        send_default_pii=False,
    )
    logger.info("Sentry error tracking enabled")


def _init_auto_instrumentation(settings) -> None:
    HTTPXClientInstrumentor().instrument()
    logger.info("OTel auto-instrumentation: httpx")


def instrument_app(app) -> None:
    """Instrument a FastAPI app. Call after app creation."""
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,docs,openapi.json")
    logger.info("OTel auto-instrumentation: FastAPI")


def instrument_db_engine(engine) -> None:
    """Instrument a SQLAlchemy engine."""
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    logger.info("OTel auto-instrumentation: SQLAlchemy")


def _parse_headers(header_string: str) -> dict[str, str]:
    """Parse 'Key=Value,Key2=Value2' format into a dict."""
    if not header_string:
        return {}
    headers = {}
    for pair in header_string.split(","):
        if "=" in pair:
            key, value = pair.split("=", 1)
            headers[key.strip()] = value.strip()
    return headers


def get_tracer(name: str = "fde") -> trace.Tracer:
    """Get a named tracer for manual span creation."""
    return trace.get_tracer(name)
