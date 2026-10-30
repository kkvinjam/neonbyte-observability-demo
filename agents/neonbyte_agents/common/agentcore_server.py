"""Wrap an agent's ``run()`` as a Bedrock AgentCore Runtime app.

The same app serves ``POST /invocations`` + ``GET /ping`` on AgentCore Runtime
(port 8080) and locally (``PORT`` env var, loopback unless inside a container).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable

from bedrock_agentcore.runtime import BedrockAgentCoreApp


def _extract(payload: dict) -> tuple[str | None, str | None, str | None]:
    inner = payload.get("input") if isinstance(payload.get("input"), dict) else {}
    prompt = payload.get("prompt") or inner.get("prompt")
    user_id = payload.get("userId") or payload.get("actorId") or inner.get("userId") or inner.get("actorId")
    session_id = payload.get("sessionId") or payload.get("runtimeSessionId") or inner.get("sessionId")
    return prompt, user_id, session_id


def build_app(run: Callable[..., str]) -> BedrockAgentCoreApp:
    """Return a BedrockAgentCoreApp whose entrypoint delegates to ``run``."""
    app = BedrockAgentCoreApp()

    @app.entrypoint
    def handler(payload):  # noqa: ANN001 - AgentCore passes a dict
        prompt, user_id, session_id = _extract(payload or {})
        if not prompt:
            return "Error: no 'prompt' provided in the request."
        return run(prompt, user_id=user_id, session_id=session_id)

    return app


def build_streaming_app(stream: Callable[..., AsyncIterator[str]]) -> BedrockAgentCoreApp:
    """Return a BedrockAgentCoreApp that streams text chunks from ``stream``."""
    app = BedrockAgentCoreApp()

    @app.entrypoint
    async def handler(payload):  # noqa: ANN001 - AgentCore passes a dict
        prompt, user_id, session_id = _extract(payload or {})
        if not prompt:
            yield "Error: no 'prompt' provided in the request."
            return
        async for chunk in stream(prompt, user_id=user_id, session_id=session_id):
            if chunk:
                yield chunk

    return app


def serve(app: BedrockAgentCoreApp) -> None:
    """Run the app. Host auto-detects: 0.0.0.0 in a container, 127.0.0.1 otherwise."""
    app.run(port=int(os.getenv("PORT", "8080")))
