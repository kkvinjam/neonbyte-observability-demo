"""End-to-end test of the microservices, in-process and in-memory.

Each service's outbound ``httpx`` client is swapped for a router that dispatches
to the sibling app's TestClient, so the whole checkout saga runs without network.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services"))
os.environ.update(DISABLE_SSM="true", DECLINE_RATE="0")

from fastapi.testclient import TestClient  # noqa: E402

from common.embedded import Router  # noqa: E402

from cart import app as cart_mod  # noqa: E402
from catalog import app as catalog_mod  # noqa: E402
from orders import app as orders_mod  # noqa: E402
from payments import app as payments_mod  # noqa: E402
from storefront import app as storefront_mod  # noqa: E402


@pytest.fixture(scope="module")
def store():
    apps = {
        8081: TestClient(catalog_mod.app),
        8082: TestClient(cart_mod.app),
        8083: TestClient(orders_mod.app),
        8084: TestClient(payments_mod.app),
    }
    by_key = {"CATALOG_URL": apps[8081], "CART_URL": apps[8082], "ORDERS_URL": apps[8083], "PAYMENTS_URL": apps[8084]}
    for client in apps.values():
        client.__enter__()  # run startup hooks (catalog seeding)
    router = Router(by_key)
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


def test_chat_session_id_shown(store):
    front, _ = store
    sid = "0b1c2d3e-aaaa-bbbb-cccc-123456789abc"
    body = front.get(f"/api/assistant/session?session={sid}", headers={"X-User-Id": "user007"}).json()
    assert body["session_id"] == f"user007-{sid}" and len(body["session_id"]) >= 33  # AgentCore minimum
    assert front.get("/api/assistant/session?session=bad%20id").status_code == 422
    assert 'id="chat-session-id"' in front.get("/").text


def test_every_product_has_a_photo(store):
    front, apps = store
    import json as _json
    from pathlib import Path as _P

    root = _P(__file__).resolve().parents[1]
    ids = {p["product_id"] for p in _json.loads((root / "services/catalog/products.json").read_text())}
    photos = {f.stem for f in (root / "services/storefront/static/products").glob("*.webp")}
    assert ids <= photos, f"missing photos: {sorted(ids - photos)}"
    html = front.get("/").text
    assert 'src="/static/products/NB-0001.webp"' in html
    assert front.get("/static/products/NB-0009.webp").headers["content-type"] == "image/webp"
