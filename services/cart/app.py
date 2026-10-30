"""Cart service - one cart per user, line items priced from the catalog."""

from __future__ import annotations

import logging
import time

from fastapi import HTTPException
from pydantic import BaseModel, Field

from common.app_factory import create_app
from common.config import service_url
from common.http import client
from common.store import Table

logger = logging.getLogger("cart")
app = create_app("cart", "NeonByte Cart")
carts = Table("carts", pk="user_id")


class AddItem(BaseModel):
    product_id: str
    quantity: int = Field(1, ge=1, le=20)


def _view(user_id: str) -> dict:
    cart = carts.get(user_id) or {"user_id": user_id, "items": {}}
    items = list(cart["items"].values())
    return {
        "user_id": user_id,
        "items": items,
        "item_count": sum(i["quantity"] for i in items),
        "total_cents": sum(i["quantity"] * i["price_cents"] for i in items),
    }


@app.get("/carts/{user_id}")
def get_cart(user_id: str) -> dict:
    return _view(user_id)


@app.post("/carts/{user_id}/items")
def add_item(user_id: str, body: AddItem) -> dict:
    resp = client.get(f"{service_url('CATALOG_URL')}/products/{body.product_id}")
    if resp.status_code == 404:
        raise HTTPException(404, f"unknown product {body.product_id}")
    resp.raise_for_status()
    product = resp.json()
    if product["stock"] < body.quantity:
        raise HTTPException(409, f"only {product['stock']} units of {product['name']} left")

    cart = carts.get(user_id) or {"user_id": user_id, "items": {}}
    line = cart["items"].get(body.product_id) or {
        "product_id": body.product_id,
        "name": product["name"],
        "category": product["category"],
        "price_cents": product["price_cents"],
        "quantity": 0,
    }
    line["quantity"] = min(line["quantity"] + body.quantity, 20)
    cart["items"][body.product_id] = line
    cart["updated_at"] = int(time.time())
    carts.put(cart)
    logger.info("added to cart", extra={"user_id": user_id, "product_id": body.product_id})
    return _view(user_id)


@app.delete("/carts/{user_id}/items/{product_id}")
def remove_item(user_id: str, product_id: str) -> dict:
    cart = carts.get(user_id)
    if cart and cart["items"].pop(product_id, None):
        carts.put(cart)
    return _view(user_id)


@app.delete("/carts/{user_id}")
def clear_cart(user_id: str) -> dict:
    carts.delete(user_id)
    return _view(user_id)
