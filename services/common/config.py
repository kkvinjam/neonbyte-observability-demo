"""Shared configuration for the NeonByte microservices.

Every value resolves in the same order: environment variable -> SSM Parameter
Store (``{PARAMETER_STORE_PREFIX}/<name>``) -> local default. Locally nothing
needs SSM; on AWS the CloudFormation stack publishes the parameters.
"""

from __future__ import annotations

import os

AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")
PARAMETER_STORE_PREFIX: str = os.getenv("PARAMETER_STORE_PREFIX", "/neonbyte")
HTTP_TIMEOUT: float = float(os.getenv("HTTP_TIMEOUT", "10"))

# logical key -> (SSM short name, local default)
_SERVICE_URLS: dict[str, tuple[str, str]] = {
    "CATALOG_URL": ("catalogurl", "http://127.0.0.1:8081"),
    "CART_URL": ("carturl", "http://127.0.0.1:8082"),
    "ORDERS_URL": ("ordersurl", "http://127.0.0.1:8083"),
    "PAYMENTS_URL": ("paymentsurl", "http://127.0.0.1:8084"),
}


_ssm_cache: dict[str, str] = {}


def ssm_value(short_name: str, fresh: bool = False) -> str:
    """Fetch ``{PREFIX}/{short_name}`` from SSM; '' when absent or no credentials.

    Only found values are cached, so a parameter created after this process
    started (stack still deploying) is picked up on a later call.
    """
    if os.getenv("DISABLE_SSM", "").lower() == "true":
        return ""
    if not fresh and short_name in _ssm_cache:
        return _ssm_cache[short_name]
    try:
        import boto3

        resp = boto3.client("ssm", region_name=AWS_REGION).get_parameter(
            Name=f"{PARAMETER_STORE_PREFIX}/{short_name}"
        )
        _ssm_cache[short_name] = resp["Parameter"]["Value"]
        return _ssm_cache[short_name]
    except Exception:  # noqa: BLE001 - missing parameter / no credentials -> default
        return ""


def service_url(key: str) -> str:
    """Base URL of a sibling microservice: env override, else SSM, else localhost."""
    ssm_name, default = _SERVICE_URLS[key]
    return (os.getenv(key) or ssm_value(ssm_name) or default).rstrip("/")
