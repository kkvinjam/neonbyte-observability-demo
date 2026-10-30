"""Thin client over the NeonByte microservices, shared by every agent's tools.

Calls go through ``httpx`` so ADOT auto-instrumentation records each tool call as
a CLIENT span to catalog / cart / orders — the agent -> microservice edges in the
Application Signals map. Errors come back as ``{"error": ...}`` dicts the LLM can read.
"""

from __future__ import annotations

from typing import Any

import httpx

from neonbyte_agents.common import config

_client = httpx.Client(timeout=config.HTTP_TIMEOUT)


def _call(method: str, key: str, path: str, **kwargs: Any) -> Any:
    url = f"{config.backend_url(key)}{path}"
    try:
        resp = _client.request(method, url, **kwargs)
    except httpx.HTTPError as exc:
        return {"error": f"{key} unreachable: {exc}"}
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail") or resp.text
        except ValueError:
            detail = resp.text
        return {"error": f"HTTP {resp.status_code}: {str(detail)[:300]}"}
    return resp.json()


def _slim(p: dict) -> dict:
    """Keep listings short: the LLM rarely needs full specs in a list."""
    return {k: p[k] for k in ("product_id", "name", "brand", "category", "price_cents", "rating", "stock") if k in p}


# --- catalog
def search_products(q: str | None = None, category: str | None = None, max_price_cents: int | None = None) -> Any:
    params = {k: v for k, v in {"q": q, "category": category, "max_price_cents": max_price_cents}.items() if v}
    result = _call("GET", "CATALOG_URL", "/products", params=params)
    return [_slim(p) for p in result] if isinstance(result, list) else result


def get_product(product_id: str) -> Any:
    return _call("GET", "CATALOG_URL", f"/products/{product_id}")


def list_categories() -> Any:
    return _call("GET", "CATALOG_URL", "/categories")


# --- cart
def get_cart(user_id: str) -> Any:
    return _call("GET", "CART_URL", f"/carts/{user_id}")


def add_to_cart(user_id: str, product_id: str, quantity: int = 1) -> Any:
    return _call("POST", "CART_URL", f"/carts/{user_id}/items", json={"product_id": product_id, "quantity": quantity})


def remove_from_cart(user_id: str, product_id: str) -> Any:
    return _call("DELETE", "CART_URL", f"/carts/{user_id}/items/{product_id}")


# --- orders
def checkout(user_id: str) -> Any:
    # Shipping defaults server-side; the storefront pre-fills the shopper's address for UI checkouts.
    return _call("POST", "ORDERS_URL", "/orders/checkout", json={"user_id": user_id})


def list_orders(user_id: str) -> Any:
    result = _call("GET", "ORDERS_URL", f"/orders/{user_id}")
    if isinstance(result, list):
        return [
            {k: o.get(k) for k in ("order_id", "status", "total_cents", "created_at")}
            | {"items": [f"{i['quantity']} x {i['name']} ({i['product_id']})" for i in o.get("items", [])]}
            for o in result[:10]
        ]
    return result


def get_order(user_id: str, order_id: str) -> Any:
    return _call("GET", "ORDERS_URL", f"/orders/{user_id}/{order_id}")


def request_return(user_id: str, order_id: str, reason: str) -> Any:
    return _call("POST", "ORDERS_URL", f"/orders/{user_id}/{order_id}/return", json={"reason": reason})
