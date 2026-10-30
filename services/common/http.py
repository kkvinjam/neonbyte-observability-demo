"""Shared HTTP client for service-to-service calls (auto-instrumented by ADOT)."""

from __future__ import annotations

import httpx

from common.config import HTTP_TIMEOUT

client = httpx.Client(timeout=HTTP_TIMEOUT)
