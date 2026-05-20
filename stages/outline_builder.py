"""
Stage 5: Outline Builder

Takes the brief's heading skeleton + SERP context + business voice,
asks the outline_model (default: Gemini Flash) to refine it into a
section-by-section plan with:
  - Per-heading word budget (sums to target_word_count)
  - Per-heading target entities
  - Semantic purpose hint
"""

from __future__ import annotations

import json
from pathlib import Path

from content_models import (
    ArticleOutline,
    ContentEngineInput,
    GenerationConfig,
    OutlineHeading,
)
from stages._client import call_structured
from stages.serp_enrichment import SerpResult
from stages.term_extractor import TermSet


PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")


def build_outline(
    input_: ContentEngineInput,
    config: GenerationConfig,
    serp: SerpResult | None = None,
    terms: TermSet | None = None,
) -> ArticleOutline:
    """
    Generate the article outline.

    Phase-1 stub strategy:
      - Take the brief's headings as the base
      - Distribute target_word_count proportionally across H2s
      - Attach target entities from terms.required_terms
      - Skip LLM call if brief already has detailed headings

    Phase-2 enhancement (TODO):
      - Call outline_model with brief + SERP PAA + competitor titles
      - Let the model propose additional H2s based on SERP gaps
      - Reorder for narrative flow
    """
    brief = input_.brief_payload
    headings_raw = brief.get("headings", [])
    title = brief.get("page_title", "Untitled")

    headings: list[OutlineHeading] = []
    h2_count = sum(1 for h in headings_raw if str(h.get("level", "")).upper().lstrip("H") == "2")
    body_budget = config.scoring_target.target_word_count
    intro_budget = 150 if config.include_intro else 0
    conclusion_budget = 150 if config.include_conclusion else 0
    per_h2 = max((body_budget - intro_budget - conclusion_budget) // max(h2_count, 1), 200)

    for h in headings_raw:
        lvl = h.get("level", "H2")
        is_h2 = str(lvl).upper().lstrip("H") == "2"
        headings.append(OutlineHeading(
            level=lvl,
            text=h.get("text", ""),
            semantic_purpose=h.get("semantic_purpose", ""),
            target_word_count=per_h2 if is_h2 else 0,
            target_entities=(terms.required_terms[:5] if terms else []),
            target_queries=[],
        ))

    meta = (
        f"{title} — practical guide for {input_.business.niche}."
    )[:160]

    return ArticleOutline(
        title=title,
        meta_description=meta,
        slug=_slugify(title),
        primary_keyword=input_.target_keyword or (brief.get("queries") or {}).get("primary_query", ""),
        estimated_word_count=config.scoring_target.target_word_count,
        headings=headings,
    )


def _slugify(text: str) -> str:
    import re
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:80]
