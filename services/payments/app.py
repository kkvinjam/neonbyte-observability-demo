"""Payments service - a simulated card processor.

Business declines (HTTP 402) happen at ``decline_rate`` and are distinct from the
chaos faults (HTTP 500) every service supports. The decline rate comes from the
``{PREFIX}/payments/decline_rate`` SSM parameter on AWS (env ``DECLINE_RATE`` locally),
so a workshop can raise it and watch the checkout error budget burn.
"""

from __future__ import annotations

import logging
import os
import random
import time
import uuid

from fastapi import HTTPException
from pydantic import BaseModel, Field

from common.app_factory import create_app
from common.config import ssm_value

logger = logging.getLogger("payments")
app = create_app("payments", "NeonByte Payments")
_decline = {"rate": float(os.getenv("DECLINE_RATE", "0.03")), "at": 0.0}


def _decline_rate() -> float:
    if time.monotonic() - _decline["at"] > 30:
        _decline["at"] = time.monotonic()
        value = ssm_value("payments/decline_rate", fresh=True)
        if value:
            _decline["rate"] = float(value)
    return _decline["rate"]


class Charge(BaseModel):
    user_id: str
    order_id: str
    amount_cents: int = Field(..., gt=0)
    card_last4: str = Field("4242", min_length=4, max_length=4)


class Refund(BaseModel):
    payment_id: str
    amount_cents: int = Field(..., gt=0)


@app.post("/payments/charge")
def charge(body: Charge) -> dict:
    # A real processor's round-trip; large amounts take longer to "risk score".
    time.sleep(random.uniform(0.05, 0.15) + min(body.amount_cents / 1_000_000, 0.4))
    ctx = {"user_id": body.user_id, "order_id": body.order_id, "amount_cents": body.amount_cents}
    if body.card_last4 == "0000" or random.random() < _decline_rate():
        logger.warning("payment declined", extra=ctx)
        raise HTTPException(402, "card declined")
    payment_id = f"pay_{uuid.uuid4().hex[:16]}"
    logger.info("payment approved", extra=ctx)
    return {"payment_id": payment_id, "status": "approved", "amount_cents": body.amount_cents}


@app.post("/payments/refund")
def refund(body: Refund) -> dict:
    time.sleep(random.uniform(0.05, 0.1))
    return {"refund_id": f"ref_{uuid.uuid4().hex[:16]}", "payment_id": body.payment_id, "status": "refunded"}
