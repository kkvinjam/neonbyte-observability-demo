"""Transport for orchestrator -> sub-agent delegation.

``AGENT_TRANSPORT`` selects how a sub-agent is reached:

* ``local``   — import and call the sub-agent in-process (one Python process, simplest dev loop)
* ``http``    — POST to each sub-agent's own local server (``<NAME>_AGENT_URL``), e.g. docker compose
* ``gateway`` — POST to the AgentCore Gateway HTTP target, SigV4-signed (the AWS deployment)
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from neonbyte_agents.common import config

TRANSPORT = os.getenv("AGENT_TRANSPORT", "local")

# logical agent -> Gateway HTTP runtime target name (overridable per env)
_TARGETS = {
    "advisor": os.getenv("ADVISOR_TARGET", "advisor"),
    "orderdesk": os.getenv("ORDERDESK_TARGET", "orderdesk"),
    "support": os.getenv("SUPPORT_TARGET", "support"),
    "concierge": os.getenv("CONCIERGE_TARGET", "concierge"),
}

# logical agent -> local sub-agent server (http transport)
_LOCAL_URLS = {
    "advisor": os.getenv("ADVISOR_AGENT_URL", "http://127.0.0.1:8091"),
    "orderdesk": os.getenv("ORDERDESK_AGENT_URL", "http://127.0.0.1:8092"),
    "support": os.getenv("SUPPORT_AGENT_URL", "http://127.0.0.1:8093"),
    "concierge": os.getenv("CONCIERGE_AGENT_URL", "http://127.0.0.1:8094"),
}

# logical agent -> Application Signals service name of the sub-agent runtime.
# Must match the node the sub-agent's own telemetry reports, which is its
# AgentCore runtime name plus the qualifier; a mismatch adds a node instead of an edge.
_SERVICE_NAMES = {
    "advisor": os.getenv("ADVISOR_SERVICE", "NeonByteAdvisor.DEFAULT"),
    "orderdesk": os.getenv("ORDERDESK_SERVICE", "NeonByteOrderDesk.DEFAULT"),
    "support": os.getenv("SUPPORT_SERVICE", "NeonByteSupport.DEFAULT"),
    "concierge": os.getenv("CONCIERGE_SERVICE", "NeonByteConcierge.DEFAULT"),
}

# Environment half of the dimension pair. Every AgentCore runtime reports this.
_REMOTE_ENVIRONMENT = os.getenv("AGENT_REMOTE_ENVIRONMENT", "bedrock-agentcore:default")

try:
    from opentelemetry import trace as _otel
    from opentelemetry.trace import SpanKind, Status, StatusCode

    _TRACER = _otel.get_tracer("neonbyte_agents.delegate")
except ImportError:  # OTel ships with the runtime image only; local dev works without it
    _TRACER = None


def delegate(agent: str, query: str, user_id: str | None = None) -> str:
    """Route a delegation to a sub-agent via the configured transport."""
    if TRANSPORT == "gateway":
        return _via_gateway(agent, query, user_id)
    if TRANSPORT == "http":
        return _via_http(agent, query, user_id)
    return _in_process(agent, query, user_id)


def _in_process(agent: str, query: str, user_id: str | None) -> str:
    # Lazy imports so the gateway-transport orchestrator container never needs sub-agent deps.
    if agent == "advisor":
        from neonbyte_agents.product_advisor_langgraph import run
    elif agent == "orderdesk":
        from neonbyte_agents.order_desk_crewai import run
    elif agent == "support":
        from neonbyte_agents.support_llamaindex import run
    elif agent == "concierge":
        from neonbyte_agents.concierge_openai import run
    else:
        raise ValueError(f"unknown agent '{agent}'")
    return run(query, user_id=user_id)


@contextmanager
def _delegation_span(agent: str, url: str) -> Iterator[Any]:
    """CLIENT span naming the sub-agent as the remote service.

    Application Signals keys a map edge on the RemoteService/RemoteEnvironment
    dimension pair, which it takes from these attributes. Without them the only
    CLIENT span for this hop is the auto-instrumented HTTP one, whose remote
    service is the gateway hostname — a dead-end node, since the gateway emits
    no server span of its own. AgentCore Runtime is managed and runs no
    CloudWatch agent, so the orchestrator sets the attributes itself.

    Yields None when OpenTelemetry is absent so local runs still work.
    """
    if _TRACER is None:
        yield None
        return
    with _TRACER.start_as_current_span(
        f"POST /{_TARGETS[agent]}/invocations",
        kind=SpanKind.CLIENT,
        attributes={
            "aws.remote.service": _SERVICE_NAMES[agent],
            "aws.remote.environment": _REMOTE_ENVIRONMENT,
            "aws.remote.operation": "POST /invocations",
            # Keep the real network hop visible for trace drill-down.
            "url.full": url,
            "http.request.method": "POST",
        },
    ) as span:
        yield span


def _unwrap(data: Any) -> str:
    if isinstance(data, dict):
        return data.get("output") or data.get("result") or json.dumps(data)
    return str(data)


def _via_http(agent: str, query: str, user_id: str | None) -> str:
    """POST to a sub-agent's own local AgentCore-compatible server (no auth: loopback / compose network)."""
    import httpx

    url = f"{_LOCAL_URLS[agent].rstrip('/')}/invocations"
    try:
        resp = httpx.post(url, json={"prompt": query, "userId": user_id or ""}, timeout=180)
        resp.raise_for_status()
        return _unwrap(resp.json())
    except Exception as exc:  # noqa: BLE001 - surface to the orchestrator
        return json.dumps({"error": f"local call to '{agent}' failed: {exc}"})


def _via_gateway(agent: str, query: str, user_id: str | None) -> str:
    """POST to the Gateway HTTP runtime target, signed with SigV4 (runtime role creds)."""
    gateway = config.gateway_url()
    if not gateway:
        return json.dumps({"error": "gateway URL not configured (env GATEWAY_URL or SSM)"})
    import boto3
    import httpx
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    url = f"{gateway}/{_TARGETS[agent]}/invocations"
    body = json.dumps({"prompt": query, "userId": user_id or ""})
    signed = AWSRequest(method="POST", url=url, data=body, headers={"Content-Type": "application/json"})
    SigV4Auth(boto3.Session().get_credentials(), "bedrock-agentcore", config.AWS_REGION).add_auth(signed)
    with _delegation_span(agent, url) as span:
        try:
            resp = httpx.post(url, content=body, headers=dict(signed.headers), timeout=180)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001 - surface to the orchestrator
            if span is not None:
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                span.record_exception(exc)
            return json.dumps({"error": f"gateway call to '{agent}' failed: {exc}"})
        if span is not None:
            span.set_attribute("http.response.status_code", resp.status_code)
    return _unwrap(data)
