"""Run the four backend microservices in-process (no servers, no network).

``mesh()`` imports catalog, cart, orders and payments, keeps their data in memory,
and rewires their service-to-service HTTP calls to each other's ASGI app. It is
used by the test suite and by agents started with ``NEONBYTE_BACKEND=embedded``,
so an agent can run on any machine without starting the microservices.
"""

from __future__ import annotations

import functools
import logging
import os
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

# Ports the services' default URLs use (common.config) -> logical key.
PORTS = {8081: "CATALOG_URL", 8082: "CART_URL", 8083: "ORDERS_URL", 8084: "PAYMENTS_URL"}


class Router:
    """Quacks like ``httpx.Client``: routes a URL to the matching in-process app by port."""

    def __init__(self, apps: dict[str, TestClient]):
        self.apps = apps

    def request(self, method: str, url: str, **kwargs):
        parts = urlsplit(url)
        kwargs.pop("timeout", None)
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        return self.apps[PORTS[parts.port]].request(method, path, **kwargs)

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def delete(self, url, **kw):
        return self.request("DELETE", url, **kw)


@functools.cache
def mesh() -> Router:
    """Build the in-process service mesh once (catalog is seeded on startup)."""
    os.environ.setdefault("DISABLE_SSM", "true")
    for key in PORTS.values():  # in-process routing relies on the default localhost:<port> URLs
        os.environ.pop(key, None)
    for table in ("PRODUCTS_TABLE", "CARTS_TABLE", "ORDERS_TABLE"):
        os.environ.pop(table, None)  # in-memory store

    from cart import app as cart_mod
    from catalog import app as catalog_mod
    from orders import app as orders_mod
    from payments import app as payments_mod

    apps = {
        "CATALOG_URL": TestClient(catalog_mod.app),
        "CART_URL": TestClient(cart_mod.app),
        "ORDERS_URL": TestClient(orders_mod.app),
        "PAYMENTS_URL": TestClient(payments_mod.app),
    }
    for client in apps.values():
        client.__enter__()  # run startup hooks (catalog seeding)
    router = Router(apps)
    for mod in (cart_mod, orders_mod):
        mod.client = router
    # The services install a JSON root log handler for CloudWatch; inside an agent process keep
    # the console readable instead and only surface their warnings.
    logging.basicConfig(force=True, level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for name in ("httpx", "catalog", "cart", "orders", "payments"):
        logging.getLogger(name).setLevel(logging.WARNING)
    return router
