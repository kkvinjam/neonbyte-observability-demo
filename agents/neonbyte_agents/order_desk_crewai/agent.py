"""Order Desk sub-agent — CrewAI crew on Bedrock Nova 2 Lite (via LiteLLM)."""

from __future__ import annotations

import json

from crewai import LLM, Agent, Crew, Process, Task
from crewai.tools import tool

from neonbyte_agents.common import models, store


@tool("find_products")
def find_products(query: str) -> str:
    """Search the catalog by keywords (e.g. "QuietPods" or "65W charger") to resolve
    a product NAME to its real `product_id`. ALWAYS use this before adding something
    to the cart by name — the cart rejects unknown ids with 404. Returns JSON."""
    return json.dumps(store.search_products(q=query))


@tool("add_to_cart")
def add_to_cart(user_id: str, product_id: str, quantity: int = 1) -> str:
    """Add `quantity` of `product_id` (e.g. NB-0009) to `user_id`'s cart. Returns the cart as JSON."""
    return json.dumps(store.add_to_cart(user_id, product_id, quantity))


@tool("view_cart")
def view_cart(user_id: str) -> str:
    """Return the current contents and total of `user_id`'s cart as JSON (prices in cents)."""
    return json.dumps(store.get_cart(user_id))


@tool("remove_from_cart")
def remove_from_cart(user_id: str, product_id: str) -> str:
    """Remove `product_id` from `user_id`'s cart. Returns the cart as JSON."""
    return json.dumps(store.remove_from_cart(user_id, product_id))


@tool("checkout")
def checkout(user_id: str) -> str:
    """Check out `user_id`'s cart: reserves stock, charges the card on file and ships
    to the address on file. Returns the order (or the payment/stock error) as JSON."""
    return json.dumps(store.checkout(user_id))


_llm = LLM(model=models.litellm_model("orderdesk"))


def run(query: str, user_id: str | None = None, session_id: str | None = None) -> str:
    """Execute a cart / checkout request and return plain text."""
    clerk = Agent(
        role="NeonByte Order Desk Clerk",
        goal="Manage the shopper's cart and place orders accurately.",
        backstory=(
            "You run the NeonByte order desk. You add and remove items, review the "
            "cart and place orders via checkout. When a shopper names a product, you "
            "FIRST call find_products to get its real product_id (format NB-0000), then "
            "use that id — you never guess an id. Checkout charges a real card, so only "
            "check out when the shopper explicitly asked to buy, order or check out. "
            "Prices from tools are in cents; report them in dollars. Always confirm "
            "exactly what you did and surface any errors (out of stock, card declined)."
        ),
        llm=_llm,
        tools=[find_products, add_to_cart, view_cart, remove_from_cart, checkout],
        verbose=False,
        allow_delegation=False,
    )

    task = Task(
        description=(
            f"Shopper request: {query}\n"
            f"user_id to act on: {user_id or 'UNKNOWN — ask the shopper to pick a profile before any cart action'}\n"
            "Use tools to actually perform the action. Report exactly what happened."
        ),
        expected_output="A short confirmation of the cart/order action taken and its result.",
        agent=clerk,
    )

    crew = Crew(agents=[clerk], tasks=[task], process=Process.sequential, verbose=False)
    return str(crew.kickoff())
