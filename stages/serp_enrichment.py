"""
Stage 2: SERP Enrichment (Serper.dev + cache)

For the target keyword, pulls:
  - Top 10 organic results
  - People Also Ask
  - Related searches
  - Featured snippet (if any)

Every Serper call goes through stages.cache first. 30-day TTL by default —
SERP for the same keyword usually stays stable that long, and refreshing
on each run would burn the 1000 free Serper credits fast.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

from stages import cache


SERPER_ENDPOINT = "https://google.serper.dev/search"
DEFAULT_TTL_DAYS = 30


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class SerpResult:
    query: str
    organic: list[dict] = field(default_factory=list)
    paa: list[str] = field(default_factory=list)
    related_searches: list[str] = field(default_factory=list)
    featured_snippet: str = ""
    raw: dict = field(default_factory=dict)


# ── Public API ────────────────────────────────────────────────────────────────

def enrich_keyword(
    keyword: str,
    geo: str = "us",
    lang: str = "en",
    num: int = 10,
    use_cache: bool = True,
    ttl_days: int = DEFAULT_TTL_DAYS,
) -> SerpResult:
    """
    Pull SERP data for one keyword. Cached by (keyword, geo, lang, num).
    """
    key = cache.make_cache_key("serp", keyword.lower().strip(), geo, lang, num)

    if use_cache:
        cached = cache.get(key)
        if cached:
            return _parse(keyword, cached)

    raw = _call_serper(keyword, geo, lang, num)
    cache.put(key, "serp", raw, ttl_days=ttl_days)
    return _parse(keyword, raw)


# ── HTTP call ─────────────────────────────────────────────────────────────────

def _call_serper(keyword: str, geo: str, lang: str, num: int) -> dict:
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key:
        raise RuntimeError("SERPER_API_KEY not set in environment")
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    payload = {"q": keyword, "gl": geo, "hl": lang, "num": num}
    resp = requests.post(SERPER_ENDPOINT, headers=headers, json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ── Parser ────────────────────────────────────────────────────────────────────

def _parse(keyword: str, raw: dict) -> SerpResult:
    sr = SerpResult(query=keyword, raw=raw)

    for item in raw.get("organic", []):
        sr.organic.append({
            "position": item.get("position", 0),
            "title":    item.get("title", ""),
            "url":      item.get("link", ""),
            "snippet":  item.get("snippet", ""),
        })

    for item in raw.get("peopleAlsoAsk", []):
        q = (item.get("question") or "").strip()
        if q:
            sr.paa.append(q)

    for item in raw.get("relatedSearches", []):
        q = (item.get("query") or "").strip()
        if q:
            sr.related_searches.append(q)

    if "answerBox" in raw:
        ab = raw["answerBox"]
        sr.featured_snippet = ab.get("answer", "") or ab.get("snippet", "")

    return sr
