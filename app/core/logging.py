import json
import logging
import sys
from datetime import datetime, timezone

from opentelemetry import trace


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter with OTel trace correlation."""

    def format(self, record: logging.LogRecord) -> str:
        log = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.trace_id:
            log["trace_id"] = format(ctx.trace_id, "032x")
            log["span_id"] = format(ctx.span_id, "016x")

        if hasattr(record, "workflow_id"):
            log["workflow_id"] = record.workflow_id
        if hasattr(record, "agent"):
            log["agent"] = record.agent

        if record.exc_info and record.exc_info[1]:
            log["exception"] = self.formatException(record.exc_info)

        for key in ("workflow_id", "agent", "model", "tokens", "duration_ms", "status", "error"):
            val = record.__dict__.get(key)
            if val is not None:
                log[key] = val

        return json.dumps(log, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Configure structured JSON logging for the application."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
