#!/usr/bin/env python3
"""Generate product photos for the NeonByte catalog with an Amazon Bedrock image model.

The catalog is fictional, so every image is generated (no stock or brand photography):
a studio-style shot per product, prompted from its category, description and specs,
with brand names left out so no fake logos or text appear. Output is a 640x640 WebP per
product in services/storefront/static/products/<product_id>.webp, bundled into the
storefront image and cached by CloudFront.

    python tools/generate_product_images.py --only NB-0001,NB-0009     # samples
    python tools/generate_product_images.py                            # all missing images
    python tools/generate_product_images.py --force --only NB-0013     # regenerate one

Needs AWS credentials with bedrock:InvokeModel on the model (default: Stability Stable Image
Core in us-west-2, ~USD 0.04/image) and Pillow.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import time
from pathlib import Path

import boto3
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "services/catalog/products.json"
OUT_DIR = ROOT / "services/storefront/static/products"

# What the object physically is, per category (the catalog's names are invented brands).
SUBJECTS = {
    "laptops": "a modern laptop computer, lid open at an angle, screen glowing softly",
    "smartphones": "a modern smartphone, slightly angled, screen on with a subtle abstract wallpaper",
    "audio": "consumer audio equipment",
    "tvs": "a slim flat-screen television on a minimal stand, screen showing a soft abstract landscape",
    "wearables": "a wearable fitness device",
    "cameras": "a photography device",
    "gaming": "a video game device",
    "accessories": "a tech accessory",
    "smart-home": "a smart home device",
    "tablets": "a modern tablet computer, slightly angled, screen glowing softly",
}
STYLE = (
    "professional e-commerce product photograph, single product centered, three-quarter view, "
    "soft studio lighting, subtle reflection, smooth dark slate-blue gradient background, "
    "sharp focus, photorealistic, high detail, minimal, clean composition"
)
NEGATIVE = (
    "text, words, letters, logo, brand name, watermark, label, signature, people, hands, fingers, "
    "multiple products, clutter, cartoon, illustration, blurry, distorted, low quality, frame, border, "
    "Windows logo, Microsoft logo, Apple logo, Xbox, PlayStation buttons, triangle circle square cross symbols, ABXY letters, Nintendo, Samsung, Google logo"
)
# Hand-tuned subjects where the generic prompt drifted (wrong form factor or look-alike trademarks).
OVERRIDES = {
    "NB-0002": "a large 16 inch creator laptop, lid open, screen showing a soft abstract purple and blue gradient",
    "NB-0003": "a compact budget 13 inch laptop, lid open, screen showing a plain soft abstract teal gradient",
    "NB-0004": "a gaming laptop with an RGB backlit keyboard, lid open, screen showing an abstract neon gradient, plain unmarked lid",
    "NB-0008": "a foldable smartphone unfolded half-open like a book at 90 degrees, large inner screen with an abstract wallpaper",
    "NB-0022": "a minimalist matte white and charcoal home video game console box standing upright, plain unbranded, glowing thin blue light strip, no controller",
    "NB-0024": "a sleek matte navy wireless game controller with two analog sticks, a d-pad and four plain round buttons that are completely blank (no symbols, no letters, no icons), no touchpad",
}


def prompt_for(p: dict) -> str:
    if p["product_id"] in OVERRIDES:
        return f"{STYLE}. Product: {OVERRIDES[p['product_id']]}"
    name = p["name"].replace(p["brand"], "").strip()  # drop the fictional brand to avoid fake text
    specs = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in list(p.get("specs", {}).items())[:3])
    return f"{STYLE}. Product: {SUBJECTS.get(p['category'], 'a consumer electronics device')}: {name}, {p['description']} ({specs})"


def generate(client, model_id: str, prompt: str, seed: int) -> Image.Image:
    body = {"prompt": prompt[:2000], "negative_prompt": NEGATIVE, "aspect_ratio": "1:1", "output_format": "png", "seed": seed}
    resp = client.invoke_model(modelId=model_id, body=json.dumps(body), contentType="application/json", accept="application/json")
    data = json.loads(resp["body"].read())
    reasons = [r for r in data.get("finish_reasons", []) if r]
    if reasons:
        raise RuntimeError(f"generation filtered/failed: {reasons}")
    return Image.open(io.BytesIO(base64.b64decode(data["images"][0]))).convert("RGB")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="comma-separated product ids")
    ap.add_argument("--force", action="store_true", help="overwrite existing images")
    ap.add_argument("--model-id", default="stability.stable-image-core-v1:1")
    ap.add_argument("--region", default="us-west-2")
    ap.add_argument("--profile")
    ap.add_argument("--size", type=int, default=640)
    args = ap.parse_args()

    products = json.loads(CATALOG.read_text())
    if args.only:
        wanted = {x.strip() for x in args.only.split(",")}
        products = [p for p in products if p["product_id"] in wanted]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    client = session.client("bedrock-runtime")

    failures = 0
    for p in products:
        out = OUT_DIR / f"{p['product_id']}.webp"
        if out.exists() and not args.force:
            print(f"skip   {p['product_id']} (exists)")
            continue
        seed = int(p["product_id"].split("-")[1]) * 7919  # deterministic per product
        for attempt in range(3):
            try:
                img = generate(client, args.model_id, prompt_for(p), seed + attempt)
                break
            except Exception as exc:  # noqa: BLE001 - retry with a new seed / after throttling
                print(f"retry  {p['product_id']}: {exc}", file=sys.stderr)
                time.sleep(3 * (attempt + 1))
        else:
            failures += 1
            continue
        img.resize((args.size, args.size), Image.LANCZOS).save(out, "WEBP", quality=82, method=6)
        print(f"wrote  {out.relative_to(ROOT)}  {out.stat().st_size // 1024} KB  ({p['name']})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
