"""Customer Support sub-agent — LlamaIndex FunctionAgent on Bedrock Llama 4 Maverick."""

from __future__ import annotations

import json

from llama_index.core.agent.workflow import FunctionAgent
from llama_index.core.tools import FunctionTool
from llama_index.llms.bedrock_converse import BedrockConverse

from neonbyte_agents import knowledge
from neonbyte_agents.common import config, models, store
from neonbyte_agents.common.asyncrun import run_coro_sync

SUPPORT_PROMPT = """You are Customer Support for NeonByte Electronics.
You help shoppers after they buy: order status, returns, warranty and troubleshooting.

- `list_orders` shows the shopper's recent orders; `get_order_status` shows one order
  including its fulfillment state (PROCESSING, SHIPPED, DELIVERED) or RETURNED.
- `start_return` refunds an order. Returns are allowed within 30 days. Confirm which
  order the shopper means and only start a return when they clearly asked for one.
- `search_help_center` searches store policies (returns, warranty, shipping, payment)
  and troubleshooting guides — use it instead of guessing policy.

The shopper's user_id is given as [userId=...] in the message; pass it to tools.
Prices from tools are in cents; report dollars. Be empathetic, precise and brief."""


def list_orders(user_id: str) -> str:
    """List the shopper's 10 most recent orders with status and items. Returns JSON."""
    return json.dumps(store.list_orders(user_id))


def get_order_status(user_id: str, order_id: str) -> str:
    """Status, fulfillment state, items and shipping address of one order (e.g. ORD-1A2B3C4D5E). Returns JSON."""
    return json.dumps(store.get_order(user_id, order_id))


def start_return(user_id: str, order_id: str, reason: str) -> str:
    """Return an order and refund the card. Only after the shopper confirmed. Returns JSON."""
    return json.dumps(store.request_return(user_id, order_id, reason))


def search_help_center(question: str) -> str:
    """Search NeonByte policies and troubleshooting guides. Returns cited passages as JSON."""
    return json.dumps(knowledge.search(question, k=3) or [{"note": "no matching article"}])


class _NonStreamingBedrockConverse(BedrockConverse):
    """BedrockConverse that never streams tool calls."""

    async def astream_chat_with_tools(self, *args, **kwargs):  # noqa: ANN002,ANN003
        response = await self.achat_with_tools(*args, **kwargs)

        async def _single():
            yield response

        return _single()


_llm = _NonStreamingBedrockConverse(model=models.model_id("support"), region_name=config.AWS_REGION)

_agent = FunctionAgent(
    tools=[
        FunctionTool.from_defaults(fn=list_orders),
        FunctionTool.from_defaults(fn=get_order_status),
        FunctionTool.from_defaults(fn=start_return),
        FunctionTool.from_defaults(fn=search_help_center),
    ],
    llm=_llm,
    system_prompt=SUPPORT_PROMPT,
)


async def _run_agent(message: str):
    # Deferred so _agent.run()'s create_task lands inside run_coro_sync's loop, not "no running event loop".
    return await _agent.run(message)


def run(query: str, user_id: str | None = None, session_id: str | None = None) -> str:
    """Answer/execute a support request and return plain text."""
    message = query if not user_id else f"[userId={user_id}] {query}"
    return str(run_coro_sync(_run_agent(message)))
