"""Client for the "Sparky" shopping assistant (the Strands orchestrator agent).

On AWS the orchestrator runs on Amazon Bedrock AgentCore Runtime and is invoked
with ``InvokeAgentRuntime`` (SigV4, the task role's credentials) - the same way
the reference PetSite calls Waggle. Locally it is a plain HTTP server, so set
``ORCHESTRATOR_URL`` (e.g. ``http://127.0.0.1:8090``) instead of an ARN.
"""

from __future__ import annotations

import json
import os
import uuid

from common.config import AWS_REGION, ssm_value
from common.http import client

_agentcore = None


def _runtime_arn() -> str:
    return os.getenv("ORCHESTRATOR_RUNTIME_ARN") or ssm_value("agents/orchestratorarn")


def session_id_for(user_id: str, session: str | None) -> str:
    """AgentCore requires runtime session ids of at least 33 characters."""
    session = session or uuid.uuid4().hex
    return f"{user_id}-{session}".ljust(33, "0")[:100]


def _collect(body: bytes, content_type: str) -> str:
    """Flatten either an SSE stream (streaming entrypoint) or a JSON body into text."""
    text = body.decode("utf-8", errors="replace")
    if "text/event-stream" in content_type:
        parts = []
        for line in text.splitlines():
            if line.startswith("data:"):
                chunk = line[5:].strip()
                try:
                    chunk = json.loads(chunk)
                except ValueError:
                    pass
                parts.append(chunk if isinstance(chunk, str) else json.dumps(chunk))
        return "".join(parts)
    try:
        data = json.loads(text)
    except ValueError:
        return text
    if isinstance(data, dict):
        return data.get("output") or data.get("result") or json.dumps(data)
    return data if isinstance(data, str) else json.dumps(data)


def ask(message: str, user_id: str, session: str | None) -> dict:
    session = session or uuid.uuid4().hex
    payload = {"prompt": message, "userId": user_id, "sessionId": session_id_for(user_id, session)}
    local_url = os.getenv("ORCHESTRATOR_URL", "").rstrip("/")
    if local_url:
        resp = client.post(f"{local_url}/invocations", json=payload, timeout=180)
        resp.raise_for_status()
        return {"reply": _collect(resp.content, resp.headers.get("content-type", "")), "session": session, "session_id": payload["sessionId"]}

    arn = _runtime_arn()
    if not arn:
        return {"reply": "The assistant is not configured (set ORCHESTRATOR_URL or ORCHESTRATOR_RUNTIME_ARN).", "session": session, "session_id": payload["sessionId"]}

    global _agentcore
    if _agentcore is None:
        import boto3
        from botocore.config import Config

        _agentcore = boto3.client(
            "bedrock-agentcore", region_name=AWS_REGION, config=Config(read_timeout=180, retries={"max_attempts": 2})
        )
    resp = _agentcore.invoke_agent_runtime(
        agentRuntimeArn=arn,
        runtimeSessionId=payload["sessionId"],
        payload=json.dumps(payload).encode(),
        contentType="application/json",
        accept="application/json, text/event-stream",
    )
    body = resp["response"].read()
    return {"reply": _collect(body, resp.get("contentType", "")), "session": session, "session_id": payload["sessionId"]}
