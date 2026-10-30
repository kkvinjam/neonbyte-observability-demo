"""Central configuration for the NeonByte agents.

Resolution order for every value: env var -> SSM Parameter Store
(``{PARAMETER_STORE_PREFIX}/...``, published by the CloudFormation stack) -> ''.
A ``.env`` file next to the ``neonbyte_agents`` package overrides for local work.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    # Explicit path: load_dotenv() searches cwd upward, never into subdirs. override=True: .env wins for dev.
    _ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"  # agents/.env
    load_dotenv(dotenv_path=_ENV_PATH, override=True)
except ImportError:  # dotenv is optional; env vars still work without it
    pass


AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")

# Bedrock auth is the standard AWS credential chain via SigV4 — no API keys. Clients need the region.
os.environ.setdefault("AWS_DEFAULT_REGION", AWS_REGION)
os.environ.setdefault("AWS_REGION_NAME", AWS_REGION)  # LiteLLM's bedrock provider

# --- Models: ids must be ENABLED in your Bedrock account/region; per-agent mapping in models.py.
CLAUDE_MODEL_ID: str = os.getenv("BEDROCK_CLAUDE_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
# gpt-oss powers the OpenAI Agents SDK concierge (via LiteLLM's Bedrock provider).
GPT_OSS_MODEL_ID: str = os.getenv("BEDROCK_GPT_OSS_MODEL_ID", "openai.gpt-oss-120b-1:0")

PARAMETER_STORE_PREFIX: str = os.getenv("PARAMETER_STORE_PREFIX", "/neonbyte")
HTTP_TIMEOUT: float = float(os.getenv("HTTP_TIMEOUT", "15"))

# logical key -> (SSM short name under the prefix, local default)
_BACKENDS: dict[str, tuple[str, str]] = {
    "CATALOG_URL": ("catalogurl", "http://127.0.0.1:8081"),
    "CART_URL": ("carturl", "http://127.0.0.1:8082"),
    "ORDERS_URL": ("ordersurl", "http://127.0.0.1:8083"),
}


_ssm_cache: dict[str, str] = {}


def _ssm_value(short_name: str) -> str:
    """Fetch {PREFIX}/{short_name} from SSM; return '' on any failure.

    Only found values are cached: on first boot the runtime can start before the
    stack has published e.g. the gateway URL, and must pick it up later.
    """
    if os.getenv("DISABLE_SSM", "").lower() == "true":
        return ""
    if short_name in _ssm_cache:
        return _ssm_cache[short_name]
    try:
        import boto3

        resp = boto3.client("ssm", region_name=AWS_REGION).get_parameter(Name=f"{PARAMETER_STORE_PREFIX}/{short_name}")
        _ssm_cache[short_name] = resp["Parameter"]["Value"].rstrip("/")
        return _ssm_cache[short_name]
    except Exception:  # noqa: BLE001 - missing param / no creds -> tools report "not configured"
        return ""


def backend_url(key: str) -> str:
    """Base URL of a NeonByte microservice: env override, else SSM, else localhost."""
    ssm_name, default = _BACKENDS[key]
    return (os.getenv(key) or _ssm_value(ssm_name) or default).rstrip("/")


def gateway_url() -> str:
    """AgentCore Gateway base URL for delegation: env override, else SSM, else ''."""
    return os.getenv("GATEWAY_URL", "").rstrip("/") or _ssm_value("agents/gatewayurl")


def memory_id() -> str:
    """AgentCore Memory id: env override, else SSM, else '' (memory is best-effort no-op)."""
    return os.getenv("MEMORY_ID", "") or _ssm_value("agents/memoryid")


def guardrail_id() -> str:
    """Bedrock Guardrail id: env override, else SSM, else '' (no guardrail applied)."""
    return os.getenv("GUARDRAIL_ID", "") or _ssm_value("agents/guardrailid")


def guardrail_version() -> str:
    """Bedrock Guardrail version: env override, else SSM, else 'DRAFT'."""
    return os.getenv("GUARDRAIL_VERSION", "") or _ssm_value("agents/guardrailversion") or "DRAFT"
