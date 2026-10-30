"""Orders service - checkout saga (cart -> stock -> payment -> order) and returns."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import HTTPException
from pydantic import BaseModel, Field

from common.app_factory import create_app
from common.config import service_url
from common.http import client
from common.store import Table
from common.users import shipping_for

logger = logging.getLogger("orders")
app = create_app("orders", "NeonByte Orders")
orders = Table("orders", pk="user_id", sk="order_id")
RETURN_WINDOW_DAYS = 30


class Shipping(BaseModel):
    name: str
    street: str
    city: str
    state: str
    zip: str


class Checkout(BaseModel):
    user_id: str
    shipping: Shipping | None = Field(None, description="defaults to the shopper's address on file")
    card_last4: str = "4242"


class ReturnRequest(BaseModel):
    reason: str = "changed my mind"


def _release(reserved: list[dict]) -> None:
    for line in reserved:
        client.post(
            f"{service_url('CATALOG_URL')}/products/{line['product_id']}/release",
            json={"quantity": line["quantity"]},
        )


@app.post("/orders/checkout", status_code=201)
def checkout(body: Checkout) -> dict:
    cart = client.get(f"{service_url('CART_URL')}/carts/{body.user_id}")
    cart.raise_for_status()
    cart = cart.json()
    if not cart["items"]:
        raise HTTPException(400, "cart is empty")

    order_id = f"ORD-{uuid.uuid4().hex[:10].upper()}"
    ctx = {"user_id": body.user_id, "order_id": order_id}

    # 1. Reserve stock line by line, rolling back on the first shortage.
    reserved: list[dict] = []
    for line in cart["items"]:
        resp = client.post(
            f"{service_url('CATALOG_URL')}/products/{line['product_id']}/reserve",
            json={"quantity": line["quantity"]},
        )
        if resp.status_code != 200:
            _release(reserved)
            logger.warning("checkout failed: stock", extra=ctx)
            raise HTTPException(409, f"{line['name']} is out of stock")
        reserved.append(line)

    # 2. Charge the card; a decline releases the stock again.
    pay = client.post(
        f"{service_url('PAYMENTS_URL')}/payments/charge",
        json={
            "user_id": body.user_id,
            "order_id": order_id,
            "amount_cents": cart["total_cents"],
            "card_last4": body.card_last4,
        },
    )
    if pay.status_code != 200:
        _release(reserved)
        logger.warning("checkout failed: payment %s", pay.status_code, extra=ctx)
        raise HTTPException(402 if pay.status_code == 402 else 502, "payment failed: " + pay.text[:200])

    order = {
        "user_id": body.user_id,
        "order_id": order_id,
        "status": "CONFIRMED",
        "items": cart["items"],
        "total_cents": cart["total_cents"],
        "payment_id": pay.json()["payment_id"],
        "shipping": body.shipping.model_dump() if body.shipping else shipping_for(body.user_id),
        "created_at": int(time.time()),
    }
    orders.put(order)
    client.delete(f"{service_url('CART_URL')}/carts/{body.user_id}")
    logger.info("order placed", extra={**ctx, "amount_cents": cart["total_cents"]})
    return order


@app.get("/orders/{user_id}")
def list_orders(user_id: str) -> list[dict]:
    return sorted(orders.query(user_id), key=lambda o: o["created_at"], reverse=True)


@app.get("/orders/{user_id}/{order_id}")
def get_order(user_id: str, order_id: str) -> dict:
    order = orders.get(user_id, order_id)
    if not order:
        raise HTTPException(404, f"order {order_id} not found for {user_id}")
    # Orders "ship" a minute after purchase and are "delivered" after five - good enough for a demo.
    age = time.time() - order["created_at"]
    if order["status"] == "CONFIRMED":
        order["fulfillment"] = "DELIVERED" if age > 300 else "SHIPPED" if age > 60 else "PROCESSING"
    return order


@app.post("/orders/{user_id}/{order_id}/return")
def request_return(user_id: str, order_id: str, body: ReturnRequest) -> dict:
    order = get_order(user_id, order_id)
    if order["status"] != "CONFIRMED":
        raise HTTPException(409, f"order is already {order['status']}")
    if time.time() - order["created_at"] > RETURN_WINDOW_DAYS * 86400:
        raise HTTPException(409, "outside the 30-day return window")
    refund = client.post(
        f"{service_url('PAYMENTS_URL')}/payments/refund",
        json={"payment_id": order["payment_id"], "amount_cents": order["total_cents"]},
    )
    refund.raise_for_status()
    _release(order["items"])
    order.pop("fulfillment", None)
    order.update(status="RETURNED", return_reason=body.reason, refund_id=refund.json()["refund_id"])
    orders.put(order)
    logger.info("order returned", extra={"user_id": user_id, "order_id": order_id})
    return order
