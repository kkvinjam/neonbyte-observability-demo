#!/usr/bin/env python3
"""NeonByte traffic generator — simulated shoppers for the storefront and the agents.

Each virtual shopper loops over a realistic journey: browse a category, search,
open product pages, add items, view the cart, sometimes check out (a few with a
declined card), look at order history, occasionally return an order, hit a
missing product (404s for the error charts), and — with ``--chat-probability`` —
ask the Sparky assistant a question, which exercises the whole multi-agent chain.

Runs anywhere: on a laptop against ``http://127.0.0.1:8080``, or as the
``loadgen`` ECS service against the CloudFront URL. Configure with flags or the
matching env vars (``TARGET_URL``, ``USERS``, ``DURATION``, ...).

    python traffic/loadgen.py --target http://127.0.0.1:8080 --users 5 --duration 300
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import signal
import sys
import time
import uuid
from collections import Counter

import httpx

CATEGORIES = ["laptops", "smartphones", "audio", "tvs", "wearables", "cameras", "gaming", "accessories", "smart-home", "tablets"]
SEARCHES = ["oled", "noise cancelling", "gaming", "charger", "4k", "watch", "wireless", "drone", "chromebook", "soundbar"]
DEMO_USERS = [f"user{i:03d}" for i in range(1, 11)]

# Prompts chosen to hit every sub-agent through the orchestrator.
CHAT_PROMPTS = [
    # product advisor (LangGraph)
    "What are the best noise cancelling headphones for long flights?",
    "I need a laptop for video editing under $2500, what do you recommend?",
    "Compare the Nimbus X12 and the Pixelon 9a for photography.",
    "Which TV is best for a bright living room?",
    "Recommend a fitness tracker with long battery life.",
    # order desk (CrewAI)
    "Add the Ampere 65W GaN Charger to my cart.",
    "What's in my cart right now?",
    "Add a Glide Wireless Mouse to my cart please.",
    # support (LlamaIndex)
    "Where is my most recent order?",
    "What is your return policy?",
    "My earbuds won't pair with my phone, can you help?",
    "Does the warranty cover accidental damage?",
    # concierge (OpenAI Agents SDK)
    "What's the difference between OLED and QLED?",
    "What kinds of products does NeonByte sell?",
    "Hi Sparky! What can you help me with?",
]


def env(name: str, default: str) -> str:
    return os.getenv(name, default)


class Stats:
    def __init__(self) -> None:
        self.codes: Counter = Counter()
        self.latency: dict[str, list[float]] = {}
        self.started = time.time()

    def record(self, name: str, status: int, seconds: float) -> None:
        self.codes[(name, status)] += 1
        self.latency.setdefault(name, []).append(seconds)

    def report(self) -> str:
        lines = [f"--- {time.strftime('%H:%M:%S')} | {sum(self.codes.values())} requests in {time.time() - self.started:.0f}s"]
        for name in sorted(self.latency):
            lat = sorted(self.latency[name])
            p50, p95 = lat[len(lat) // 2], lat[min(len(lat) - 1, int(len(lat) * 0.95))]
            codes = ", ".join(f"{s}:{n}" for (k, s), n in sorted(self.codes.items()) if k == name)
            lines.append(f"  {name:<14} n={len(lat):<5} p50={p50 * 1000:6.0f}ms p95={p95 * 1000:6.0f}ms  [{codes}]")
        return "\n".join(lines)


class Shopper:
    def __init__(self, idx: int, client: httpx.AsyncClient, stats: Stats, args: argparse.Namespace):
        # Mostly the 10 demo profiles (pre-filled addresses), plus some anonymous guests.
        self.user = random.choice(DEMO_USERS) if random.random() < 0.7 else f"guest-{uuid.uuid4().hex[:8]}"
        self.client, self.stats, self.args = client, stats, args
        self.headers = {"X-User-Id": self.user, "User-Agent": f"neonbyte-loadgen/1.0 shopper-{idx}"}
        self.chat_session = uuid.uuid4().hex

    async def call(self, name: str, method: str, path: str, **kwargs) -> httpx.Response | None:
        start = time.perf_counter()
        try:
            resp = await self.client.request(method, path, headers=self.headers, **kwargs)
            self.stats.record(name, resp.status_code, time.perf_counter() - start)
            return resp
        except httpx.HTTPError as exc:
            self.stats.record(name, 0, time.perf_counter() - start)
            if self.args.verbose:
                print(f"{name}: {type(exc).__name__}: {exc}", file=sys.stderr)
            return None

    async def think(self) -> None:
        await asyncio.sleep(random.uniform(self.args.think_min, self.args.think_max))

    async def journey(self) -> None:
        await self.call("home", "GET", "/")
        await self.think()
        category = random.choice(CATEGORIES)
        await self.call("category_page", "GET", "/", params={"category": category})
        products = await self.call("api_products", "GET", "/api/products", params={"category": category})
        items = products.json() if products is not None and products.status_code == 200 else []
        await self.think()

        if random.random() < 0.5:
            await self.call("search", "GET", "/", params={"q": random.choice(SEARCHES)})
            await self.think()

        for product in random.sample(items, k=min(len(items), random.randint(1, 3))):
            await self.call("product_page", "GET", f"/product/{product['product_id']}")
            await self.think()
            if random.random() < 0.6 and product.get("stock", 0) > 0:
                await self.call("add_to_cart", "POST", "/api/cart/items", json={"product_id": product["product_id"], "quantity": random.choice([1, 1, 1, 2])})

        if random.random() < 0.05:  # broken bookmark -> 404 in the error charts
            await self.call("product_page", "GET", f"/product/NB-{random.randint(5000, 9999)}")

        await self.call("cart_page", "GET", "/cart")
        if random.random() < self.args.checkout_probability:
            await self.call("checkout_page", "GET", "/checkout")
            await self.think()
            card = "0000" if random.random() < 0.05 else "4242"
            await self.call("checkout", "POST", "/api/checkout", json={"card_last4": card})

        if random.random() < 0.4:
            orders = await self.call("orders_page", "GET", "/api/orders")
            if orders is not None and orders.status_code == 200 and random.random() < 0.1:
                confirmed = [o for o in orders.json() if o["status"] == "CONFIRMED"]
                if confirmed:
                    await self.call("return", "POST", f"/api/orders/{confirmed[0]['order_id']}/return", json={"reason": "loadgen"})

        if random.random() < self.args.chat_probability:
            await self.call(
                "assistant_chat",
                "POST",
                "/api/assistant/chat",
                json={"message": random.choice(CHAT_PROMPTS), "session": self.chat_session},
                timeout=180,
            )


async def shopper_loop(idx: int, client: httpx.AsyncClient, stats: Stats, args, stop: asyncio.Event) -> None:
    await asyncio.sleep(random.uniform(0, args.think_max * 2))  # stagger the ramp-up
    while not stop.is_set():
        try:
            await Shopper(idx, client, stats, args).journey()
        except Exception as exc:  # noqa: BLE001 - one bad journey must not kill the generator
            print(f"shopper {idx} journey error: {exc!r}", file=sys.stderr)
        await asyncio.sleep(random.uniform(args.think_min, args.think_max))


async def main(args: argparse.Namespace) -> None:
    stats, stop = Stats(), asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    print(f"NeonByte loadgen -> {args.target} | users={args.users} duration={args.duration or 'forever'}s chat_p={args.chat_probability}")
    limits = httpx.Limits(max_connections=args.users * 4)
    async with httpx.AsyncClient(base_url=args.target, timeout=30, limits=limits, follow_redirects=True) as client:
        tasks = [asyncio.create_task(shopper_loop(i, client, stats, args, stop)) for i in range(args.users)]
        deadline = time.time() + args.duration if args.duration else None
        next_report = time.time() + args.report_every
        while not stop.is_set():
            wake = min(next_report, deadline or next_report)
            try:
                await asyncio.wait_for(stop.wait(), timeout=max(wake - time.time(), 0.1))
            except asyncio.TimeoutError:
                pass
            if deadline and time.time() >= deadline:
                stop.set()
            elif time.time() >= next_report:
                print(stats.report(), flush=True)
                next_report += args.report_every
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    print(stats.report())


def parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target", default=env("TARGET_URL", "http://127.0.0.1:8080"), help="storefront base URL")
    p.add_argument("--users", type=int, default=int(env("USERS", "5")), help="concurrent virtual shoppers")
    p.add_argument("--duration", type=int, default=int(env("DURATION", "0")), help="seconds to run, 0 = until stopped")
    p.add_argument("--think-min", type=float, default=float(env("THINK_MIN", "0.5")))
    p.add_argument("--think-max", type=float, default=float(env("THINK_MAX", "3")))
    p.add_argument("--checkout-probability", type=float, default=float(env("CHECKOUT_PROBABILITY", "0.35")))
    p.add_argument("--chat-probability", type=float, default=float(env("CHAT_PROBABILITY", "0.1")),
                   help="chance per journey of an assistant chat (each one invokes several LLM calls)")
    p.add_argument("--report-every", type=int, default=int(env("REPORT_EVERY", "60")))
    p.add_argument("--verbose", action="store_true", default=env("VERBOSE", "") == "true")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse()))
