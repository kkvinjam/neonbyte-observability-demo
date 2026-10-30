"""Product Advisor sub-agent — LangGraph ReAct agent on Bedrock Claude."""

from __future__ import annotations

import json

from langchain_aws import ChatBedrockConverse
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from neonbyte_agents import knowledge
from neonbyte_agents.common import config, models, store

ADVISOR_PROMPT = """You are the Product Advisor for NeonByte Electronics.
Your job: recommend and compare electronics, grounded in the live catalog and the
NeonByte buying guides.

Process:
1. Use `buying_guide` to pull relevant guidance for the shopper's use case.
2. Use `search_products` (by category, keywords and/or max price in cents) to find
   candidates that are in stock. Categories: laptops, smartphones, audio, tvs,
   wearables, cameras, gaming, accessories, smart-home, tablets.
3. Use `get_product_details` or `compare_products` for specs when it matters.
4. Recommend 1-3 products. For each give the product_id (e.g. NB-0009), name, price
   in dollars and a one-line reason tied to the guidance or specs.

Only recommend products returned by the tools — never invent products, prices or
specs. Prices from tools are in cents; show them as dollars. Be concise."""


@tool
def search_products(query: str = "", category: str = "", max_price_dollars: float = 0) -> str:
    """Search the live NeonByte catalog. All args optional: free-text `query`
    (e.g. "noise cancelling"), `category` (laptops | smartphones | audio | tvs |
    wearables | cameras | gaming | accessories | smart-home | tablets) and a
    `max_price_dollars` budget. Returns JSON with price_cents and stock."""
    return json.dumps(
        store.search_products(
            q=query or None,
            category=category or None,
            max_price_cents=int(max_price_dollars * 100) if max_price_dollars else None,
        )
    )


@tool
def get_product_details(product_id: str) -> str:
    """Full details and specs for one product id (e.g. NB-0009). Returns JSON."""
    return json.dumps(store.get_product(product_id))


@tool
def compare_products(product_ids: list[str]) -> str:
    """Side-by-side specs for 2-4 product ids. Returns JSON."""
    return json.dumps([store.get_product(pid) for pid in product_ids[:4]])


@tool
def buying_guide(topic: str) -> str:
    """Search NeonByte's buying guides for advice on `topic` (use case, budget,
    product type). Returns cited passages."""
    hits = knowledge.search(topic, k=3)
    return json.dumps(hits or [{"note": "no matching guidance"}])


_llm_kwargs: dict = {
    "model": models.model_id("advisor"),
    "region_name": config.AWS_REGION,
    # No temperature: the Claude reasoning models reject anything but the default.
}
if config.guardrail_id():  # apply the Bedrock Guardrail when configured
    _llm_kwargs["guardrail_config"] = {
        "guardrailIdentifier": config.guardrail_id(),
        "guardrailVersion": config.guardrail_version(),
    }
_llm = ChatBedrockConverse(**_llm_kwargs)

_graph = create_react_agent(
    _llm,
    tools=[search_products, get_product_details, compare_products, buying_guide],
    prompt=ADVISOR_PROMPT,
)


def run(query: str, user_id: str | None = None, session_id: str | None = None) -> str:
    """Answer a product recommendation / comparison question and return plain text."""
    message = query if not user_id else f"[userId={user_id}] {query}"
    result = _graph.invoke({"messages": [("user", message)]})
    content = result["messages"][-1].content
    if isinstance(content, list):  # Converse can return content blocks
        content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content
