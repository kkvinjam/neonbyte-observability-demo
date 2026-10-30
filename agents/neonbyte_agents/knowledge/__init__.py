"""Local knowledge corpus (buying guides, policies, troubleshooting) with keyword retrieval.

Deliberately dependency-free: the reference demo uses a Bedrock Knowledge Base for
RAG; NeonByte keeps the corpus in-package so agents run locally with no extra infra.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

_DIR = Path(__file__).parent


@cache
def _chunks() -> list[tuple[str, str]]:
    """(source, section text) for every '## ' section of every markdown doc."""
    out = []
    for doc in sorted(_DIR.glob("*.md")):
        for section in re.split(r"\n(?=## )", doc.read_text()):
            if section.strip():
                out.append((doc.stem, section.strip()))
    return out


def search(query: str, k: int = 3) -> list[dict]:
    """Rank sections by query-term overlap (stem-ish prefix match)."""
    terms = {t[:5] for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2}
    scored = []
    for source, text in _chunks():
        words = re.findall(r"[a-z0-9]+", text.lower())
        score = sum(1 for w in words if w[:5] in terms)
        if score:
            scored.append((score, source, text))
    scored.sort(key=lambda s: -s[0])
    return [{"source": s, "text": t} for _, s, t in scored[:k]]
