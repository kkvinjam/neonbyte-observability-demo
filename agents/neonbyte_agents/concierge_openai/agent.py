"""Concierge sub-agent — OpenAI Agents SDK on Bedrock gpt-oss (via LiteLLM)."""

from __future__ import annotations

import json

from agents import Agent, Runner, function_tool, set_tracing_disabled
from agents.extensions.models.litellm_model import LitellmModel

from neonbyte_agents.common import models, store
from neonbyte_agents.common.asyncrun import run_coro_sync

# No OpenAI platform account here — disable the SDK's hosted tracing exporter.
set_tracing_disabled(True)

CONCIERGE_PROMPT = """You are Sparky, the friendly concierge of NeonByte Electronics.
Answer general questions about the store, technology concepts (what is OLED, what
does ANC mean, Wi-Fi vs Bluetooth...) and small talk. Keep it warm and concise.
Use `store_categories` when asked what NeonByte sells. For specific product
recommendations, cart/checkout, or order help, say you'll hand the shopper to a
specialist (the orchestrator routes)."""


@function_tool
def store_categories() -> str:
    """List NeonByte's product categories with product counts. Returns JSON."""
    return json.dumps(store.list_categories())


# LiteLLM bedrock provider -> SigV4 with the standard AWS credential chain.
_agent = Agent(
    name="NeonByte Concierge",
    instructions=CONCIERGE_PROMPT,
    model=LitellmModel(model=models.litellm_model("concierge")),
    tools=[store_categories],
)


def run(query: str, user_id: str | None = None, session_id: str | None = None) -> str:
    """Answer a general question and return plain text."""
    message = query if not user_id else f"[userId={user_id}] {query}"
    result = run_coro_sync(Runner.run(_agent, message))
    return result.final_output
