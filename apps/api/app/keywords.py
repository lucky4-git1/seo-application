"""Keyword domain logic: normalization, intent, difficulty, opportunity.

All scores are the platform's transparent estimates computed from real data —
never presented as vendor/Google metrics. Formulas live here (not in the UI).
"""
from __future__ import annotations

import re
import unicodedata

INTENTS = ("INFORMATIONAL", "NAVIGATIONAL", "COMMERCIAL", "TRANSACTIONAL", "LOCAL")

# Deterministic heuristics (spec §20). Order matters: first match wins, with
# transactional/commercial checked before informational.
INTENT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("TRANSACTIONAL", ("buy", "price", "pricing", "order", "cheap", "discount",
                       "coupon", "deal", "cost", "quote", "hire", "book now",
                       "for sale", "purchase")),
    ("LOCAL", ("near me", "nearby", "open now", "address", "phone number",
               "directions", "locations", "opening hours", "map")),
    ("COMMERCIAL", ("best", "top", "review", "reviews", "vs", "versus", "compare",
                    "comparison", "alternative", "alternatives", "ranked", "pros and cons")),
    ("NAVIGATIONAL", ("login", "sign in", "official site", ".com", "homepage")),
    ("INFORMATIONAL", ("how to", "how do", "what is", "what are", "guide", "tutorial",
                       "tips", "ideas", "learn", "why", "when", "examples", "meaning",
                       "definition")),
]


def normalize_keyword(raw: str) -> str:
    """case/whitespace/unicode/punctuation-insensitive canonical form."""
    s = unicodedata.normalize("NFKC", raw or "")
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = s.strip(" .,;:!?\"'()[]{}")
    return s


def classify_intent(keyword: str) -> tuple[str, float]:
    """Heuristic intent + confidence. Returns (intent, 0..1)."""
    text = f" {(keyword or '').lower()} "
    for intent, markers in INTENT_RULES:
        for m in markers:
            if m in text:
                # longer/more specific markers → higher confidence
                return intent, min(0.95, 0.55 + 0.05 * len(m.split()))
    # question-form default
    if re.match(r"^(who|what|where|when|why|how|which|can|does|is|are)\b", text.strip()):
        return "INFORMATIONAL", 0.6
    return "INFORMATIONAL", 0.35


def keyword_difficulty(*, serp_results: list[dict] | None = None,
                       competition: float | None = None,
                       search_volume: int | None = None) -> tuple[float, str]:
    """Platform Keyword Difficulty 0–100 + explanation.

    Inputs: normalized SERP results ([{domain, ...}] top-10), vendor
    competition 0..1. Heuristic weights (documented):
      40% big-domain saturation (how many top-10 hosts look authoritative),
      35% vendor competition signal, 25% demand (high volume = contested).
    """
    results = serp_results or []
    strong = sum(1 for r in results[:10]
                 if len((r.get("domain") or "").split(".")) <= 2
                 and len(r.get("domain") or "") <= 20)
    saturation = (strong / max(1, min(10, len(results)))) if results else 0.5
    comp = max(0.0, min(1.0, competition if competition is not None else 0.5))
    vol = search_volume or 0
    demand = 0.9 if vol >= 100000 else 0.7 if vol >= 10000 else 0.5 if vol >= 1000 else 0.3
    score = round(100 * (0.40 * saturation + 0.35 * comp + 0.25 * demand), 1)
    note = (f"top-10 saturation {saturation:.0%}, vendor competition {comp:.0%}, "
            f"demand tier {demand:.0%}")
    return score, note


def opportunity_score(*, search_volume: int | None, difficulty: float | None,
                      intent: str | None, current_rank: int | None = None) -> float:
    """Platform Opportunity Score 0–100.

    demand (log volume) × achievability (1 − difficulty) × intent value ×
    proximity bonus (already ranking just off page one scores higher).
    """
    import math
    vol = search_volume or 0
    demand = min(1.0, math.log10(vol + 1) / 5.0)  # 100k+/mo → 1.0
    diff = max(0.0, min(100.0, difficulty if difficulty is not None else 50.0))
    achievability = 1.0 - diff / 100.0
    intent_value = {"TRANSACTIONAL": 1.0, "COMMERCIAL": 0.9, "LOCAL": 0.85,
                    "NAVIGATIONAL": 0.5, "INFORMATIONAL": 0.7}.get(intent or "", 0.6)
    proximity = 1.0
    if current_rank:
        proximity = 1.2 if 4 <= current_rank <= 15 else (0.7 if current_rank <= 3 else 1.0)
    # proximity is a bonus (never a penalty): normalize by 1.0, clamp 0–100
    return round(max(0.0, min(100.0, 100 * demand * achievability * intent_value
                              * min(proximity, 1.2))), 1)
