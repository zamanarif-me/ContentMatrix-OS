"""
Stage 5: Outline Builder — Phase 2D

Two-path outline generation:
  Path A (Phase 2D, default):
    Gemini Flash receives the brief skeleton + SERP PAA + competitor titles.
    It proposes a narrative-ordered heading list with gap H2s, word budgets,
    semantic_purpose, and target_entities per heading.

  Path B (stub fallback):
    If the LLM call fails for any reason (no API key, parse error, etc.),
    falls back to direct brief heading extraction with proportional word budgets.
    This ensures zero-crash resilience.

LLM call cost: ~0.001 USD per outline (Gemini Flash pricing).
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from content_models import (
    ArticleOutline,
    ContentEngineInput,
    GenerationConfig,
    OutlineHeading,
)
from stages._client import call_structured, load_prompt
from stages.serp_enrichment import SerpResult
from stages.term_extractor import TermSet


# ── Internal LLM response schema ─────────────────────────────────────────────

class _HeadingLLM(BaseModel):
    level:             str = "H2"
    text:              str
    semantic_purpose:  str = ""
    target_word_count: int = 300
    target_entities:   list[str] = Field(default_factory=list)


class _OutlineLLMResponse(BaseModel):
    title:            str
    meta_description: str = ""
    headings:         list[_HeadingLLM] = Field(default_factory=list)


# ── Public API ────────────────────────────────────────────────────────────────

def build_outline(
    input_: ContentEngineInput,
    config: GenerationConfig,
    serp: SerpResult | None = None,
    terms: TermSet | None = None,
) -> ArticleOutline:
    """
    Generate the article outline.
    Phase 2D: tries an LLM call first. Falls back to stub on any error.
    """
    try:
        return _build_with_llm(input_, config, serp, terms)
    except Exception as exc:
        print(
            f"[outline_builder] LLM outline failed ({type(exc).__name__}: {exc}), "
            "using brief-skeleton fallback.",
            flush=True,
        )
        return _build_stub(input_, config, terms)


# ── Path A: LLM-driven outline ────────────────────────────────────────────────

def _build_with_llm(
    input_: ContentEngineInput,
    config: GenerationConfig,
    serp: SerpResult | None,
    terms: TermSet | None,
) -> ArticleOutline:
    model = config.model_strategy.outline_model.value
    system_prompt = load_prompt("outline", include_house_rules=False)
    user_message = _build_outline_message(input_, config, serp, terms)

    response: _OutlineLLMResponse = call_structured(
        system_prompt=system_prompt,
        user_message=user_message,
        response_model=_OutlineLLMResponse,
        model=model,
        max_tokens=4000,
        stage="outline",
        temperature=0.3,
    )

    if not response.headings:
        raise ValueError("LLM returned zero headings — falling back to stub.")

    entity_fallback = (terms.required_terms[:5] if terms else [])

    headings = [
        OutlineHeading(
            level=h.level,
            text=h.text,
            semantic_purpose=h.semantic_purpose,
            target_word_count=_clamp_wc(h.target_word_count, config),
            target_entities=h.target_entities if h.target_entities else entity_fallback,
            target_queries=[],
        )
        for h in response.headings
        if h.text.strip()
    ]

    return ArticleOutline(
        title=response.title or input_.brief_payload.get("page_title", "Untitled"),
        meta_description=_safe_meta(response.meta_description, input_),
        slug=_slugify(response.title or input_.brief_payload.get("page_title", "")),
        primary_keyword=(
            input_.target_keyword
            or (input_.brief_payload.get("queries") or {}).get("primary_query", "")
        ),
        estimated_word_count=config.scoring_target.target_word_count,
        headings=headings,
    )


# ── Path B: Brief-skeleton stub (fallback) ────────────────────────────────────

def _build_stub(
    input_: ContentEngineInput,
    config: GenerationConfig,
    terms: TermSet | None,
) -> ArticleOutline:
    brief = input_.brief_payload
    headings_raw = brief.get("headings", [])
    title = brief.get("page_title", "Untitled")

    h2_count = sum(
        1 for h in headings_raw
        if str(h.get("level", "")).upper().lstrip("H") == "2"
    )
    body_budget = config.scoring_target.target_word_count
    intro_budget = 150 if config.include_intro else 0
    conclusion_budget = 150 if config.include_conclusion else 0
    per_h2 = max(
        (body_budget - intro_budget - conclusion_budget) // max(h2_count, 1),
        200,
    )

    entity_fallback = (terms.required_terms[:5] if terms else [])

    headings = [
        OutlineHeading(
            level=h.get("level", "H2"),
            text=h.get("text", ""),
            semantic_purpose=h.get("semantic_purpose", ""),
            target_word_count=(
                per_h2 if str(h.get("level", "")).upper().lstrip("H") == "2" else 0
            ),
            target_entities=entity_fallback,
            target_queries=[],
        )
        for h in headings_raw
        if h.get("text", "").strip()
    ]

    return ArticleOutline(
        title=title,
        meta_description=_safe_meta("", input_),
        slug=_slugify(title),
        primary_keyword=(
            input_.target_keyword
            or (brief.get("queries") or {}).get("primary_query", "")
        ),
        estimated_word_count=config.scoring_target.target_word_count,
        headings=headings,
    )


# ── User message builder ──────────────────────────────────────────────────────

def _build_outline_message(
    input_: ContentEngineInput,
    config: GenerationConfig,
    serp: SerpResult | None,
    terms: TermSet | None,
) -> str:
    brief = input_.brief_payload
    blocks: list[str] = []

    blocks.append("# Article Specification")
    queries = brief.get("queries") or {}
    blocks.append(json.dumps({
        "title":              brief.get("page_title", ""),
        "primary_keyword":    (input_.target_keyword or queries.get("primary_query", "")),
        "secondary_keywords": queries.get("secondary_queries", [])[:8],
        "page_type":          brief.get("page_type", ""),
        "content_format":     config.content_format.value,
        "target_word_count":  config.scoring_target.target_word_count,
        "audience":           input_.business.audience,
        "niche":              input_.business.niche,
        "tone":               config.tone.value,
    }, indent=2))

    brief_headings = brief.get("headings", [])
    if brief_headings:
        blocks.append(
            "\n# Brief Heading Skeleton\n"
            "(Preserve these; reorder for flow; add gap H2s from SERP where helpful.)"
        )
        blocks.append(json.dumps(brief_headings, indent=2))

    if serp:
        blocks.append("\n# SERP Evidence")
        if serp.organic:
            titles = [r.get("title", "").strip() for r in serp.organic[:10] if r.get("title", "").strip()]
            blocks.append("## Competitor Page Titles (top 10)")
            blocks.append("\n".join(f"- {t}" for t in titles))
        if serp.paa:
            blocks.append("\n## People Also Ask\n(Turn relevant PAA questions into H2 or H3 headings.)")
            blocks.append("\n".join(f"- {q}" for q in serp.paa[:12]))
        if serp.related_searches:
            blocks.append("\n## Related Searches")
            blocks.append("\n".join(f"- {q}" for q in serp.related_searches[:8]))
        if serp.featured_snippet:
            blocks.append(f"\n## Featured Snippet\n{serp.featured_snippet[:300]}")

    if terms:
        if terms.required_terms:
            blocks.append("\n# Required Terms\nDistribute these as target_entities across headings (2-4 per H2).")
            blocks.append(", ".join(terms.required_terms[:25]))
        if terms.entities:
            blocks.append("\n# Named Entities Found in Competitor Content")
            blocks.append(", ".join(terms.entities[:20]))

    intro_budget = 150 if config.include_intro else 0
    conclusion_budget = 150 if config.include_conclusion else 0
    body_budget = config.scoring_target.target_word_count - intro_budget - conclusion_budget

    blocks.append("\n# Word Budget")
    blocks.append(json.dumps({
        "total_target":   config.scoring_target.target_word_count,
        "intro":          intro_budget,
        "conclusion":     conclusion_budget,
        "body_available": body_budget,
        "note":           "Distribute body_available across H2s proportionally. Min 200 words per H2.",
    }, indent=2))

    if terms and terms.avg_word_count > 0:
        blocks.append(f"\n# Competitor Average Word Count\n{terms.avg_word_count} words — calibrate depth accordingly.")

    blocks.append("\n# Required Output Format (strict JSON — no markdown fences, no commentary)")
    blocks.append(json.dumps({
        "title": "Final article title (may refine the brief title for clarity/CTR)",
        "meta_description": "<=160 chars; primary keyword near the front",
        "headings": [{"level": "H2", "text": "Exact heading text", "semantic_purpose": "One sentence: what this section accomplishes for the reader", "target_word_count": 350, "target_entities": ["entity1", "entity2"]}],
    }, indent=2))

    return "\n".join(blocks)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clamp_wc(wc: int, config: GenerationConfig) -> int:
    return max(150, min(wc, config.scoring_target.target_word_count))


def _safe_meta(meta: str, input_: ContentEngineInput) -> str:
    if meta and len(meta.strip()) > 20:
        return meta.strip()[:160]
    title = input_.brief_payload.get("page_title", "")
    niche = input_.business.niche
    return f"{title} — practical guide for {niche}."[:160]


def _slugify(text: str) -> str:
    import re
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:80]
