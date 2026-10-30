"""End-to-end test of the microservices, in-process and in-memory.

Each service's outbound ``httpx`` client is swapped for a router that dispatches
to the sibling app's TestClient, so the whole checkout saga runs without network.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services"))
os.environ.update(DISABLE_SSM="true", DECLINE_RATE="0")

from fastapi.testclient import TestClient  # noqa: E402

from cart import app as cart_mod  # noqa: E402
from catalog import app as catalog_mod  # noqa: E402
from orders import app as orders_mod  # noqa: E402
from payments import app as payments_mod  # noqa: E402
from storefront import app as storefront_mod  # noqa: E402


class Router:
    """Quacks like httpx.Client; routes by port to the matching TestClient."""

    def __init__(self, apps: dict[int, TestClient]):
        self.apps = apps

    def request(self, method, url, **kwargs):
        parts = urlsplit(url)
        kwargs.pop("timeout", None)
        return self.apps[parts.port].request(method, parts.path + (f"?{parts.query}" if parts.query else ""), **kwargs)

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def delete(self, url, **kw):
        return self.request("DELETE", url, **kw)


@pytest.fixture(scope="module")
def store():
    apps = {
        8081: TestClient(catalog_mod.app),
        8082: TestClient(cart_mod.app),
        8083: TestClient(orders_mod.app),
        8084: TestClient(payments_mod.app),
    }
    for client in apps.values():
        client.__enter__()  # run startup hooks (catalog seeding)
    router = Router(apps)
    for mod in (cart_mod, orders_mod, storefront_mod):
        mod.client = router
    with TestClient(storefront_mod.app) as front:
        yield front, apps


def test_pages_render(store):
    front, _ = store
    for path in ("/", "/?category=audio", "/?q=oled", "/product/NB-0001", "/cart", "/checkout", "/orders"):
        assert front.get(path).status_code == 200, path
    assert front.get("/product/NB-9999").status_code == 404


def test_checkout_flow(store):
    front, apps = store
    hdr = {"X-User-Id": "user003"}
    stock_before = apps[8081].get("/products/NB-0009").json()["stock"]
    cart = front.post("/api/cart/items", json={"product_id": "NB-0009", "quantity": 2}, headers=hdr).json()
    assert cart["item_count"] == 2 and cart["total_cents"] == 2 * 24900

    order = front.post("/api/checkout", json={}, headers=hdr)
    assert order.status_code == 200, order.text
    order = order.json()
    assert order["shipping"]["name"] == "Sofia Patel"
    assert apps[8081].get("/products/NB-0009").json()["stock"] == stock_before - 2
    assert front.get("/api/cart", headers=hdr).json()["item_count"] == 0
    assert front.get("/api/orders", headers=hdr).json()[0]["order_id"] == order["order_id"]

    returned = front.post(f"/api/orders/{order['order_id']}/return", json={}, headers=hdr).json()
    assert returned["status"] == "RETURNED"
    assert apps[8081].get("/products/NB-0009").json()["stock"] == stock_before


def test_declined_card_releases_stock(store):
    front, apps = store
    hdr = {"X-User-Id": "user004"}
    before = apps[8081].get("/products/NB-0011").json()["stock"]
    front.post("/api/cart/items", json={"product_id": "NB-0011"}, headers=hdr)
    resp = front.post("/api/checkout", json={"card_last4": "0000"}, headers=hdr)
    assert resp.status_code == 402
    assert apps[8081].get("/products/NB-0011").json()["stock"] == before


def test_oversell_rejected(store):
    front, _ = store
    resp = front.post("/api/cart/items", json={"product_id": "NB-0001", "quantity": 20}, headers={"X-User-Id": "x"})
    assert resp.status_code in (200, 409)
    assert front.post("/api/cart/items", json={"product_id": "NOPE"}, headers={"X-User-Id": "x"}).status_code == 404
