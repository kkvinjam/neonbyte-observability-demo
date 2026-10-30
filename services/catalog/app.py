"""Catalog service - products, categories, search and stock reservations."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import HTTPException, Query
from pydantic import BaseModel, Field

from common.app_factory import create_app
from common.store import ConditionFailed, Table

logger = logging.getLogger("catalog")
app = create_app("catalog", "NeonByte Catalog")
products = Table("products", pk="product_id")


def _seed() -> None:
    """Load the bundled catalog when the table is empty (idempotent across tasks)."""
    if products.scan(limit=1):
        return
    seed = json.loads((Path(__file__).parent / "products.json").read_text())
    for item in seed:
        products.put(item)
    logger.info("seeded %d products into %s backend", len(seed), products.backend)


@app.on_event("startup")
def startup() -> None:
    _seed()


class Quantity(BaseModel):
    quantity: int = Field(1, ge=1, le=20)


@app.get("/categories")
def list_categories() -> list[dict]:
    counts: dict[str, int] = {}
    for p in products.scan():
        counts[p["category"]] = counts.get(p["category"], 0) + 1
    return [{"category": c, "products": n} for c, n in sorted(counts.items())]


@app.get("/products")
def list_products(
    category: str | None = None,
    q: str | None = Query(None, description="free-text search over name, brand, description"),
    max_price_cents: int | None = None,
    brand: str | None = None,
) -> list[dict]:
    items = products.scan()
    if category:
        items = [p for p in items if p["category"] == category.lower()]
    if brand:
        items = [p for p in items if p["brand"].lower() == brand.lower()]
    if max_price_cents:
        items = [p for p in items if p["price_cents"] <= max_price_cents]
    if q:
        terms = q.lower().split()
        items = [
            p
            for p in items
            if all(
                t in f"{p['name']} {p['brand']} {p['category']} {p['description']}".lower()
                for t in terms
            )
        ]
    return sorted(items, key=lambda p: p["product_id"])


@app.get("/products/{product_id}")
def get_product(product_id: str) -> dict:
    item = products.get(product_id)
    if not item:
        logger.warning("product not found", extra={"product_id": product_id})
        raise HTTPException(404, f"product {product_id} not found")
    return item


@app.post("/products/{product_id}/reserve")
def reserve(product_id: str, body: Quantity) -> dict:
    """Atomically take ``quantity`` units out of stock (409 when not enough left)."""
    get_product(product_id)
    try:
        left = products.add_to_counter(product_id, "stock", -body.quantity)
    except ConditionFailed:
        logger.warning("insufficient stock", extra={"product_id": product_id})
        raise HTTPException(409, f"insufficient stock for {product_id}") from None
    return {"product_id": product_id, "reserved": body.quantity, "stock": left}


@app.post("/products/{product_id}/release")
def release(product_id: str, body: Quantity) -> dict:
    """Return previously reserved units to stock (failed payment, returns)."""
    left = products.add_to_counter(product_id, "stock", body.quantity, floor=-(10**9))
    return {"product_id": product_id, "released": body.quantity, "stock": left}
