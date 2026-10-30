"""Fault injection for observability exercises.

Each service reads two knobs, refreshed every ``CHAOS_REFRESH_SECONDS``:

* ``{PREFIX}/chaos/<service>/latency_ms``  - extra latency added to every request
* ``{PREFIX}/chaos/<service>/error_rate``  - fraction (0-1) of requests answered with HTTP 500

On AWS they are SSM parameters (flip them in the console or CLI, no redeploy);
locally the env vars ``CHAOS_LATENCY_MS`` / ``CHAOS_ERROR_RATE`` are used instead.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time

from fastapi import Request
from fastapi.responses import JSONResponse

from common.config import AWS_REGION, PARAMETER_STORE_PREFIX

logger = logging.getLogger(__name__)
_REFRESH = float(os.getenv("CHAOS_REFRESH_SECONDS", "30"))
_EXEMPT = {"/health", "/ping"}


class Chaos:
    def __init__(self, service: str):
        self.service = service
        self.latency_ms = float(os.getenv("CHAOS_LATENCY_MS", "0"))
        self.error_rate = float(os.getenv("CHAOS_ERROR_RATE", "0"))
        self._use_ssm = os.getenv("DISABLE_SSM", "").lower() != "true"
        self._loaded_at = 0.0

    def _refresh(self) -> None:
        if not self._use_ssm or time.monotonic() - self._loaded_at < _REFRESH:
            return
        self._loaded_at = time.monotonic()
        try:
            import boto3

            names = {
                f"{PARAMETER_STORE_PREFIX}/chaos/{self.service}/latency_ms": "latency_ms",
                f"{PARAMETER_STORE_PREFIX}/chaos/{self.service}/error_rate": "error_rate",
            }
            resp = boto3.client("ssm", region_name=AWS_REGION).get_parameters(Names=list(names))
            for p in resp.get("Parameters", []):
                setattr(self, names[p["Name"]], float(p["Value"]))
        except Exception as exc:  # noqa: BLE001 - chaos is best-effort
            logger.debug("chaos refresh failed: %s", exc)

    async def middleware(self, request: Request, call_next):
        if request.url.path in _EXEMPT:
            return await call_next(request)
        await asyncio.to_thread(self._refresh)
        if self.latency_ms > 0:
            await asyncio.sleep(self.latency_ms / 1000 * random.uniform(0.8, 1.2))
        if self.error_rate > 0 and random.random() < self.error_rate:
            logger.error("chaos: injected failure on %s %s", request.method, request.url.path)
            return JSONResponse({"error": "injected fault (chaos)"}, status_code=500)
        return await call_next(request)
