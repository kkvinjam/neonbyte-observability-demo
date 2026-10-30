"""Strands orchestrator — routes each request to the right sub-agent."""

from __future__ import annotations

from contextvars import ContextVar

from strands import Agent, tool
from strands.models import BedrockModel

from neonbyte_agents.common import config, models
from neonbyte_agents.orchestrator_strands.delegate import delegate

_current_user: ContextVar[str | None] = ContextVar("current_user", default=None)

ORCHESTRATOR_PROMPT = """You are Sparky, the orchestrator of the NeonByte Electronics shopping assistant.
You do not answer directly; you route each shopper request to a specialist tool:

- `product_advisor` -> recommendations, comparisons, "which X should I buy", specs.
- `order_desk`      -> add/remove cart items, view cart, check out / place an order.
- `customer_support`-> order status, order history, returns/refunds, warranty, troubleshooting.
- `concierge_chat`  -> general tech questions, store info and small talk.

Pick the best tool, pass the shopper's request (rephrased with useful context such
as product ids from earlier in the conversation), and return the specialist's
answer. If a request spans areas (e.g. "recommend earbuds AND add them to my
cart"), call the tools in sequence, passing the product_id from the first answer
to the next. Keep product ids like NB-0009 in your reply — the site links them.
Keep the final reply friendly and concise."""


@tool
def product_advisor(query: str) -> str:
    """Delegate to the Product Advisor (LangGraph) for product recommendations,
    comparisons and specs. Input: the shopper's question with budget/use case."""
    return delegate("advisor", query, user_id=_current_user.get())


@tool
def order_desk(query: str) -> str:
    """Delegate to the Order Desk (CrewAI) to add or remove cart items, review the
    cart and check out / place an order."""
    return delegate("orderdesk", query, user_id=_current_user.get())


@tool
def customer_support(query: str) -> str:
    """Delegate to Customer Support (LlamaIndex) for order status, order history,
    returns and refunds, warranty and troubleshooting."""
    return delegate("support", query, user_id=_current_user.get())


@tool
def concierge_chat(query: str) -> str:
    """Delegate to the Concierge (OpenAI Agents SDK) for general tech questions,
    store information and small talk."""
    return delegate("concierge", query, user_id=_current_user.get())


_model_kwargs: dict = {"model_id": models.model_id("orchestrator"), "region_name": config.AWS_REGION}
if config.guardrail_id():  # apply the Bedrock Guardrail when configured (SSM/env)
    _model_kwargs["guardrail_id"] = config.guardrail_id()
    _model_kwargs["guardrail_version"] = config.guardrail_version()
_model = BedrockModel(**_model_kwargs)

_TOOLS = [product_advisor, order_desk, customer_support, concierge_chat]


def _new_agent() -> Agent:
    # A fresh Agent per request: Strands agents keep conversation state, and
    # per-shopper context comes from AgentCore Memory instead.
    return Agent(model=_model, system_prompt=ORCHESTRATOR_PROMPT, tools=_TOOLS, callback_handler=None)


def _prompt(query: str, user_id: str | None, session_id: str | None) -> str:
    from neonbyte_agents.common import memory

    recalled = memory.recall(user_id, query, session_id=session_id)
    return f"{recalled}\n\n---\nCurrent shopper message: {query}" if recalled else query


def run(query: str, user_id: str | None = None, session_id: str | None = None) -> str:
    """Route a shopper message through the orchestrator and return plain text."""
    from neonbyte_agents.common import memory

    token = _current_user.set(user_id)
    try:
        answer = str(_new_agent()(_prompt(query, user_id, session_id)))
    finally:
        _current_user.reset(token)
    memory.record_turn(user_id, session_id, query, answer)
    return answer


async def stream_run(query: str, user_id: str | None = None, session_id: str | None = None):
    """Stream the orchestrator's answer as text chunks (async generator)."""
    from neonbyte_agents.common import memory

    token = _current_user.set(user_id)
    parts: list[str] = []
    try:
        async for event in _new_agent().stream_async(_prompt(query, user_id, session_id)):
            text = event.get("data") if isinstance(event, dict) else None
            if text:
                parts.append(text)
                yield text
    finally:
        _current_user.reset(token)
    memory.record_turn(user_id, session_id, query, "".join(parts))
