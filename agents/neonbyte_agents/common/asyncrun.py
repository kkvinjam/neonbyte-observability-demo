"""Run a coroutine from sync code, even inside a live event loop."""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Coroutine
from typing import Any


def run_coro_sync(coro: Coroutine[Any, Any, Any]) -> Any:
    """Await ``coro`` and return its result, safe to call from sync code."""
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if running is not None:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(coro)).result()
    return asyncio.run(coro)
