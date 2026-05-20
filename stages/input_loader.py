"""
Stage 1: Input Loader

Reads inputs from multiple sources and produces a validated ContentEngineInput:
  - From topical-map-engine-pro session folders (auto-detect topical_map.json + briefs/)
  - From single JSON upload (one full ContentEngineInput)
  - From manual form payload (UI builds the dict)

This is the ONLY stage that knows about the existing engine's file layout.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from content_models import (
    BriefSource,
    BusinessCategory,
    BusinessContext,
    ContentEngineInput,
    TopicalMapRef,
)


# ── From existing engine session ──────────────────────────────────────────────

def load_from_engine_session(
    session_dir: str | Path,
    page_id: str,
    business: BusinessContext,
) -> ContentEngineInput:
    """
    Load a single page's brief from a topical-map-engine-pro session.

    Expected layout:
        session_dir/
          topical_map.json
          briefs/all_briefs.json
    """
    session_dir = Path(session_dir)
    tm_path = session_dir / "topical_map.json"
    briefs_path = session_dir / "briefs" / "all_briefs.json"

    if not tm_path.exists():
        raise FileNotFoundError(f"Missing {tm_path}")
    if not briefs_path.exists():
        raise FileNotFoundError(f"Missing {briefs_path}")

    all_briefs = json.loads(briefs_path.read_text(encoding="utf-8"))
    if page_id not in all_briefs:
        raise KeyError(f"page_id '{page_id}' not in {briefs_path}")

    brief_payload = all_briefs[page_id]
    tm_raw = json.loads(tm_path.read_text(encoding="utf-8"))

    tm = tm_raw.get("topical_map", {})
    central = (tm.get("central_entity") or {}).get("primary")

    topical_map_ref = TopicalMapRef(
        source=str(tm_path),
        central_entity=central,
        pillars=[
            {"id": p.get("id"), "title": p.get("title")}
            for p in tm.get("pillars", [])
        ],
        geo_pages=[
            {"id": g.get("id"), "title": g.get("title")}
            for g in tm.get("geo_pages", [])
        ],
    )

    primary_q = (brief_payload.get("queries") or {}).get("primary_query")

    return ContentEngineInput(
        business=business,
        brief_source=BriefSource.FROM_ENGINE,
        brief_payload=brief_payload,
        topical_map_ref=topical_map_ref,
        target_keyword=primary_q,
    )


# ── From single JSON upload ───────────────────────────────────────────────────

def load_from_json(path: str | Path) -> ContentEngineInput:
    """Load a complete ContentEngineInput from a JSON file."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return ContentEngineInput.model_validate(data)


def load_from_dict(data: dict) -> ContentEngineInput:
    """Load from an in-memory dict (e.g. parsed by a UI file_uploader)."""
    return ContentEngineInput.model_validate(data)


# ── List available pages from an engine session ───────────────────────────────

def list_pages_in_session(session_dir: str | Path) -> list[dict]:
    """
    Return list of {page_id, page_title, page_type} for the UI dropdown.
    """
    briefs_path = Path(session_dir) / "briefs" / "all_briefs.json"
    if not briefs_path.exists():
        return []
    all_briefs = json.loads(briefs_path.read_text(encoding="utf-8"))
    return [
        {
            "page_id": pid,
            "page_title": b.get("page_title", "Untitled"),
            "page_type": b.get("page_type", "unknown"),
        }
        for pid, b in all_briefs.items()
    ]
