"""
Stage 6: Section Writer (chunk-by-chunk, real LLM)

For each H2 in the outline:
  1. Build a contextual prompt (brief + section spec + business voice)
  2. Compute cache key  ->  if cache HIT, reuse and skip the LLM
  3. Otherwise call section_model via stages._client.call_text
  4. Parse response: count words, detect entity mentions, detect term matches
  5. Cache the result
  6. Return SectionDraft

This is where 80% of LLM cost is spent — caching matters here MOST.
"""

from __future__ import annotations

import json
import re
from typing import Iterable, Optional

from content_models import (
    BusinessContext,
    GenerationConfig,
    OutlineHeading,
    SectionDraft,
    SectionType,
    WritingModel,
)
from stages import cache
from stages._client import call_text, load_prompt
from stages.ymyl import detect_ymyl, ymyl_directive


# ── Public API ────────────────────────────────────────────────────────────────

def write_section(
    section_id: str,
    heading: OutlineHeading,
    section_type: SectionType,
    brief: dict,
    business: BusinessContext,
    config: GenerationConfig,
    *,
    previous_tail: str = "",
    serp_context: str = "",
    use_cache: bool = True,
    dry_run: bool = False,
) -> SectionDraft:
    """
    Generate one section. Cached on a stable hash of all inputs that
    would meaningfully change the output.

    Args:
        section_id:    Stable ID e.g. "s_001"
        heading:       Outline heading (text, level, target word count, entities)
        section_type:  intro | body | faq | conclusion | cta
        brief:         Raw ContentBrief dict
        business:      BusinessContext (niche, voice, audience)
        config:        GenerationConfig (tone, pov, model strategy)
        previous_tail: Last paragraph of the previous section (for continuity)
        serp_context:  Optional SERP summary block
        use_cache:     If True, look up cache before calling LLM
        dry_run:       If True, return placeholder without calling LLM (for UI test)
    """
    model = _pick_model(section_type, config)

    cache_key = cache.make_cache_key(
        "section",
        brief.get("page_id"),
        heading.text,
        heading.target_word_count,
        section_type.value,
        model,
        business.niche,
        config.tone.value,
        config.pov.value,
        config.reading_level.value,
        # Include must-include terms so brief changes bust the cache
        sorted((brief.get("nlp_terms") or {}).get("must_include", [])),
        sorted(heading.target_entities or []),
    )

    if use_cache:
        hit = cache.get(cache_key)
        if hit:
            return SectionDraft(
                section_id=section_id,
                section_type=section_type,
                heading=heading,
                content_md=hit.get("content_md", ""),
                word_count=hit.get("word_count", 0),
                used_entities=hit.get("used_entities", []),
                matched_terms=hit.get("matched_terms", []),
                model_used=model,
                cache_key=cache_key,
                cache_hit=True,
            )

    if dry_run:
        body = _placeholder(heading, model)
    else:
        system_prompt = load_prompt(_prompt_name_for(section_type))
        user_message = _build_user_message(
            heading=heading,
            section_type=section_type,
            brief=brief,
            business=business,
            config=config,
            previous_tail=previous_tail,
            serp_context=serp_context,
        )
        body = call_text(
            system_prompt=system_prompt,
            user_message=user_message,
            model=model,
            max_tokens=_max_tokens_for(heading.target_word_count),
            stage=f"section_writer:{section_type.value}",
            temperature=_temperature_for(section_type),
        ).strip()

    # ── Post-process: count words, detect entities/terms ─────────────────────
    word_count    = _count_words(body)
    must_terms    = (brief.get("nlp_terms") or {}).get("must_include", [])
    should_terms  = (brief.get("nlp_terms") or {}).get("should_include", [])
    target_ents   = heading.target_entities or []
    matched_terms = _detect_present(body, must_terms + should_terms)
    used_entities = _detect_present(body, target_ents)

    draft = SectionDraft(
        section_id=section_id,
        section_type=section_type,
        heading=heading,
        content_md=body,
        word_count=word_count,
        used_entities=used_entities,
        matched_terms=matched_terms,
        model_used=model,
        cache_key=cache_key,
        cache_hit=False,
    )

    if use_cache:
        cache.put(
            cache_key, "llm",
            {
                "content_md":    draft.content_md,
                "word_count":    draft.word_count,
                "used_entities": draft.used_entities,
                "matched_terms": draft.matched_terms,
            },
            ttl_days=30,
        )
    return draft


# ── Prompt assembly ──────────────────────────────────────────────────────────

def _build_user_message(
    heading: OutlineHeading,
    section_type: SectionType,
    brief: dict,
    business: BusinessContext,
    config: GenerationConfig,
    previous_tail: str,
    serp_context: str,
) -> str:
    nlp = brief.get("nlp_terms") or {}
    queries = brief.get("queries") or {}

    blocks: list[str] = []

    blocks.append("# Section Specification")
    blocks.append(json.dumps({
        "heading":            heading.text,
        "level":              heading.level,
        "semantic_purpose":   heading.semantic_purpose,
        "target_word_count":  heading.target_word_count,
        "target_entities":    heading.target_entities,
        "section_type":       section_type.value,
    }, indent=2))

    blocks.append("\n# Brief Context")
    blocks.append(json.dumps({
        "page_title":       brief.get("page_title"),
        "central_entity":   brief.get("central_entity"),
        "primary_query":    queries.get("primary_query"),
        "secondary_queries": queries.get("secondary_queries", [])[:5],
        "question_queries":  queries.get("question_queries", [])[:5],
        "must_include_terms":  nlp.get("must_include", []),
        "should_include_terms": nlp.get("should_include", []),
        "information_gain_angle": brief.get("information_gain_angle"),
    }, indent=2))

    blocks.append("\n# Business & Voice")
    blocks.append(json.dumps({
        "niche":         business.niche,
        "category":      business.category.value,
        "audience":      business.audience,
        "brand_name":    business.brand_name,
        "voice_notes":   business.brand_voice_notes,
        "language":      business.language,
        "tone":          config.tone.value,
        "pov":           config.pov.value,
        "reading_level": config.reading_level.value,
    }, indent=2))

    # ── E-E-A-T from brief ─────────────────────────────────────────────────
    eeat = brief.get("eeat_requirements") or {}
    if eeat:
        blocks.append("\n# E-E-A-T Requirements")
        blocks.append(json.dumps({
            "author_expertise":   eeat.get("author_expertise", ""),
            "experience_signals": eeat.get("experience_signals", []),
            "trust_signals":      eeat.get("trust_signals", []),
            "ymyl_considerations": eeat.get("ymyl_considerations"),
        }, indent=2))

    # ── YMYL auto-detection ────────────────────────────────────────────────
    if config.enforce_ymyl:
        is_ymyl, cats = detect_ymyl(business, brief)
        if is_ymyl:
            blocks.append(ymyl_directive(cats))

    # ── Internal linking targets from brief ────────────────────────────────
    bridges = brief.get("semantic_bridges") or []
    next_dest = brief.get("next_destination") or {}
    if config.enable_internal_linking and (bridges or next_dest):
        blocks.append("\n# Internal Linking Targets")
        link_data = {
            "semantic_bridges": [
                {
                    "anchor_text":  b.get("anchor_suggestion", ""),
                    "destination":  b.get("link_destination", ""),
                    "shared_entity": b.get("shared_entity", ""),
                    "bridge_point":  b.get("bridge_point", ""),
                }
                for b in bridges
            ],
            "next_destination": {
                "page_title":         next_dest.get("next_page_title", ""),
                "anchor":             next_dest.get("transition_anchor", ""),
                "reason":             next_dest.get("transition_reason", ""),
            } if next_dest else None,
        }
        blocks.append(json.dumps(link_data, indent=2))
        blocks.append(
            "When the section content naturally relates to a semantic bridge, "
            "weave the exact anchor_text into the prose as a markdown link "
            "[anchor_text](destination). Do NOT invent anchors."
        )

    if previous_tail:
        blocks.append("\n# Previous Section (last paragraph — for continuity, do NOT repeat)")
        blocks.append(previous_tail[:600])

    if serp_context:
        blocks.append("\n# SERP Context")
        blocks.append(serp_context[:1500])

    if config.custom_instructions:
        blocks.append("\n# Custom Instructions")
        blocks.append(config.custom_instructions)

    blocks.append("\n# Task")
    blocks.append(
        f"Write the body for this section in Markdown. "
        f"Target ~{heading.target_word_count} words. "
        f"Start with the H{heading.level.lstrip('H')} heading exactly matching "
        f"'{heading.text}'. No preamble, no commentary."
    )
    return "\n".join(blocks)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _pick_model(section_type: SectionType, config: GenerationConfig) -> str:
    """Section model for everything; intro/conclusion could later use a fancier model."""
    return config.model_strategy.section_model.value


def _prompt_name_for(section_type: SectionType) -> str:
    return {
        SectionType.INTRO:      "intro",
        SectionType.BODY:       "section",
        SectionType.FAQ:        "faq",
        SectionType.CONCLUSION: "conclusion",
        SectionType.CTA:        "cta",
    }.get(section_type, "section")


def _temperature_for(section_type: SectionType) -> float:
    """Lower temp for structural sections, higher for prose."""
    return {
        SectionType.FAQ:        0.4,    # tight, factual
        SectionType.CTA:        0.5,
        SectionType.INTRO:      0.7,
        SectionType.BODY:       0.7,
        SectionType.CONCLUSION: 0.6,
    }.get(section_type, 0.7)


def _max_tokens_for(target_word_count: int) -> int:
    """Heuristic: ~1.5 tokens per word, with floor and ceiling."""
    if target_word_count <= 0:
        return 1500
    return max(500, min(8000, int(target_word_count * 2.0)))


def _count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _detect_present(body: str, terms: Iterable[str]) -> list[str]:
    """Return the subset of `terms` that appear whole-word in body (case-insensitive)."""
    body_low = body.lower()
    hit: list[str] = []
    for t in terms:
        t_clean = (t or "").strip()
        if not t_clean:
            continue
        if re.search(r"\b" + re.escape(t_clean.lower()) + r"\b", body_low):
            hit.append(t_clean)
    return hit


def _placeholder(heading: OutlineHeading, model: str) -> str:
    """Dry-run fallback so the pipeline runs without API keys."""
    return (
        f"## {heading.text}\n\n"
        f"_[Placeholder for '{heading.text}' — would be generated by {model}. "
        f"Target {heading.target_word_count} words. "
        f"Purpose: {heading.semantic_purpose}.]_\n"
    )


# ── Humanization pass ────────────────────────────────────────────────────────

def humanize_section(
    draft: SectionDraft,
    config: GenerationConfig,
    *,
    use_cache: bool = True,
    dry_run: bool = False,
) -> SectionDraft:
    """
    Run the humanize.txt prompt over a draft. Returns a new SectionDraft
    with humanized content_md. Preserves heading, entities, and term matches.

    Skipped if dry_run, if content_md is empty, or if config disables it.
    """
    if dry_run or not draft.content_md.strip() or not config.enable_humanization:
        return draft

    model = config.model_strategy.refine_model.value
    cache_key = cache.make_cache_key(
        "humanize", draft.cache_key or "", model, draft.content_md[:200]
    )

    if use_cache:
        hit = cache.get(cache_key)
        if hit:
            return draft.model_copy(update={
                "content_md":   hit["content_md"],
                "word_count":   hit["word_count"],
                "matched_terms": hit.get("matched_terms", draft.matched_terms),
                "used_entities": hit.get("used_entities", draft.used_entities),
                "refined":      True,
                "cache_hit":    True,
            })

    system_prompt = load_prompt("humanize")
    user_message = (
        "# Section to humanize\n\n"
        + draft.content_md
        + "\n\n# Reminder\n"
        + "Preserve EVERY heading, list, code block, link, and entity exactly.\n"
        + "Output the humanized section as plain markdown — no commentary."
    )
    humanized = call_text(
        system_prompt=system_prompt,
        user_message=user_message,
        model=model,
        max_tokens=_max_tokens_for(draft.word_count or 1000),
        stage="humanizer",
        temperature=0.6,
    ).strip()

    new_wc = _count_words(humanized)
    new_matched = _detect_present(
        humanized,
        [t for t in (draft.matched_terms or [])],
    )
    new_used = _detect_present(humanized, draft.used_entities or [])

    if use_cache:
        cache.put(cache_key, "llm", {
            "content_md":    humanized,
            "word_count":    new_wc,
            "matched_terms": new_matched,
            "used_entities": new_used,
        }, ttl_days=30)

    return draft.model_copy(update={
        "content_md":    humanized,
        "word_count":    new_wc,
        "matched_terms": new_matched,
        "used_entities": new_used,
        "refined":       True,
        "cache_hit":     False,
        "refine_count":  (draft.refine_count or 0) + 1,
    })
