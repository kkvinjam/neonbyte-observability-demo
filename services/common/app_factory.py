"""FastAPI app factory shared by every NeonByte microservice.

Telemetry is *not* configured here: on ECS the ADOT Python auto-instrumentation
(mounted by an init container and activated through ``PYTHONPATH``) instruments
FastAPI, httpx and botocore with zero code, exactly like the reference
``petlistadoptions-py`` service. This module only adds JSON logs that carry the
active trace id so CloudWatch Logs and X-Ray traces can be correlated.
"""

from __future__ import annotations

import json
import logging
import os
import sys

from fastapi import FastAPI

from common.chaos import Chaos


class _JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Set by the OTel logging instrumentation (OTEL_PYTHON_LOG_CORRELATION=true).
        trace_id = getattr(record, "otelTraceID", None)
        if trace_id and trace_id != "0":
            entry["traceId"] = f"1-{trace_id[:8]}-{trace_id[8:]}"  # X-Ray format
            entry["spanId"] = getattr(record, "otelSpanID", None)
        for key in ("user_id", "order_id", "product_id", "amount_cents"):
            if hasattr(record, key):
                entry[key] = getattr(record, key)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def configure_logging(service: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO"))
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def create_app(service: str, title: str) -> FastAPI:
    configure_logging(service)
    app = FastAPI(title=title)
    chaos = Chaos(service)
    app.middleware("http")(chaos.middleware)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": service}

    return app
