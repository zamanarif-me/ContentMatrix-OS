"""
Stage 7: Refiner (score-gated rewrite loop)

If QualityReport.passed_target is False, identify the worst section by its
contribution to the score gap and rewrite it with the refine_model
(default: Claude Sonnet).

Loop terminates when:
  - quality.passed_target becomes True, OR
  - article.refine_passes >= config.scoring_target.max_refine_passes, OR
  - no candidate section is found (all sections already strong)

Each refinement pass is bounded — picks ONE section per pass, rewrites,
re-scores. This keeps cost predictable and gives the loop a clear exit.
"""

from __future__ import annotations

import json
from typing import Optional

from content_models import (
    GeneratedArticle,
    GenerationConfig,
    QualityReport,
    SectionDraft,
    SectionType,
)
from stages import cache, content_scorer
from stages._client import call_text, load_prompt
from stages.section_writer import _count_words, _detect_present, _max_tokens_for
from stages.term_extractor import TermSet


# ── Public API ────────────────────────────────────────────────────────────────

def refine_until_target(
    article: GeneratedArticle,
    quality: QualityReport,
    config: GenerationConfig,
    *,
    brief: dict | None = None,
    business=None,
    terms: TermSet | None = None,
    dry_run: bool = False,
) -> tuple[GeneratedArticle, QualityReport]:
    """
    Iterate refinement until quality target is met or pass budget is exhausted.
    Mutates article.sections / article.final_md / article.quality / article.refine_passes.
    """
    if dry_run or quality.passed_target:
        return article, quality
    if brief is None or terms is None:
        # Without brief + terms we can't build a useful fix prompt
        return article, quality

    max_passes = config.scoring_target.max_refine_passes
    while article.refine_passes < max_passes and not quality.passed_target:
        target_idx = _identify_worst_section(article, quality, terms)
        if target_idx is None:
            break

        section = article.sections[target_idx]
        fix_instructions = _build_fix_instructions(article, quality, terms, section)
        missing_for_section = _terms_for_this_section(section, quality)

        refined = _refine_one_section(
            section=section,
            fix_instructions=fix_instructions,
            missing_terms=missing_for_section,
            brief=brief,
            business=business,
            config=config,
        )
        article.sections[target_idx] = refined
        article.refine_passes += 1

        # Reassemble final_md and re-score
        from stages.exporter import assemble_markdown
        article.final_md = assemble_markdown(article)
        quality = content_scorer.score_article(article, terms, config.scoring_target)
        article.quality = quality

    return article, quality


# ── Worst-section identification ─────────────────────────────────────────────

def _identify_worst_section(
    article: GeneratedArticle,
    quality: QualityReport,
    terms: TermSet,
) -> Optional[int]:
    """
    Pick the section that, if improved, would lift the article score the most.
    Heuristic:
      - +5 per missing required term that would naturally fit here
      - +3 if section word count is < 50% of target
      - +1 if section word count is < 80% of target
      - +2 if section has zero matched terms
      - -10 if section is intro / conclusion (refine these last)
      - -4 if this section was already refined once (avoid loops)
    """
    if not article.sections:
        return None

    missing_required = set(quality.term_coverage.missing_must)
    best_idx, best_score = None, -10**9

    for i, s in enumerate(article.sections):
        score = 0
        affinity = _section_term_affinity(s, missing_required)
        score += 5 * len(affinity)

        if s.heading and s.heading.target_word_count > 0:
            ratio = s.word_count / max(s.heading.target_word_count, 1)
            if ratio < 0.5:
                score += 3
            elif ratio < 0.8:
                score += 1

        if not s.matched_terms:
            score += 2

        if s.section_type in (SectionType.INTRO, SectionType.CONCLUSION):
            score -= 10

        if (s.refine_count or 0) > 0:
            score -= 4

        if score > best_score:
            best_score, best_idx = score, i

    return best_idx if best_score > 0 else None


def _section_term_affinity(section: SectionDraft, missing: set[str]) -> list[str]:
    """Terms from `missing` that have lexical overlap with this section."""
    haystack = (
        section.heading.text + " "
        + (section.heading.semantic_purpose or "") + " "
        + " ".join(section.heading.target_entities or [])
    ).lower()
    return [t for t in missing if any(part in haystack for part in t.lower().split())]


def _terms_for_this_section(section: SectionDraft, quality: QualityReport) -> list[str]:
    missing = (
        set(quality.term_coverage.missing_must)
        | set(quality.term_coverage.missing_should)
    )
    affinity = _section_term_affinity(section, missing)
    return affinity[:6]


# ── Fix instruction builder ───────────────────────────────────────────────────

def _build_fix_instructions(
    article: GeneratedArticle,
    quality: QualityReport,
    terms: TermSet,
    section: SectionDraft,
) -> str:
    parts: list[str] = []
    n = 1

    sec_missing = _terms_for_this_section(section, quality)
    if sec_missing:
        parts.append(
            f"{n}. Inject these missing terms naturally (whole-word, in the prose, "
            f"not in a list): {', '.join(sec_missing)}"
        )
        n += 1

    if section.heading and section.heading.target_word_count > 0:
        delta = section.heading.target_word_count - section.word_count
        if abs(delta) > section.heading.target_word_count * 0.15:
            direction = "expand" if delta > 0 else "tighten"
            parts.append(
                f"{n}. Word count: {direction} by ~{abs(delta)} words "
                f"(current: {section.word_count}, target: {section.heading.target_word_count})"
            )
            n += 1

    target_ents = section.heading.target_entities or []
    missing_ents = [e for e in target_ents if e not in (section.used_entities or [])]
    if missing_ents:
        parts.append(f"{n}. Add coverage of these entities: {', '.join(missing_ents)}")
        n += 1

    if not parts:
        parts.append(
            "1. Improve specificity. Add concrete examples, tool/version names, "
            "real numbers. Strengthen the information gain angle. "
            "Cut any fluff sentences that don't add new information."
        )

    return "\n".join(parts)


# ── Section rewriter ─────────────────────────────────────────────────────────

def _refine_one_section(
    section: SectionDraft,
    fix_instructions: str,
    missing_terms: list[str],
    brief: dict,
    business,
    config: GenerationConfig,
) -> SectionDraft:
    """Call refine_model with the fix prompt. Cached on (section + instructions)."""
    model = config.model_strategy.refine_model.value

    cache_key = cache.make_cache_key(
        "refine",
        section.cache_key or section.section_id,
        section.content_md[:200],
        fix_instructions,
        sorted(missing_terms),
        model,
    )
    hit = cache.get(cache_key)
    if hit:
        rewritten = hit["content_md"]
    else:
        system_prompt = load_prompt("refine")
        user_message = _build_refine_message(
            section=section,
            fix_instructions=fix_instructions,
            missing_terms=missing_terms,
            brief=brief,
            business=business,
            config=config,
        )
        rewritten = call_text(
            system_prompt=system_prompt,
            user_message=user_message,
            model=model,
            max_tokens=_max_tokens_for(section.heading.target_word_count or section.word_count or 800),
            stage="refiner",
            temperature=0.5,
        ).strip()
        cache.put(cache_key, "llm", {"content_md": rewritten}, ttl_days=30)

    must_terms = (brief.get("nlp_terms") or {}).get("must_include", [])
    should_terms = (brief.get("nlp_terms") or {}).get("should_include", [])

    return section.model_copy(update={
        "content_md":    rewritten,
        "word_count":    _count_words(rewritten),
        "matched_terms": _detect_present(rewritten, must_terms + should_terms),
        "used_entities": _detect_present(rewritten, section.heading.target_entities or []),
        "model_used":    model,
        "cache_key":     cache_key,
        "cache_hit":     hit is not None,
        "refined":       True,
        "refine_count":  (section.refine_count or 0) + 1,
    })


def _build_refine_message(
    section: SectionDraft,
    fix_instructions: str,
    missing_terms: list[str],
    brief: dict,
    business,
    config: GenerationConfig,
) -> str:
    target_wc = section.heading.target_word_count or section.word_count or 800
    delta = target_wc - section.word_count

    blocks: list[str] = []
    blocks.append("# Current Section\n")
    blocks.append(section.content_md)

    blocks.append("\n# Fix Instructions\n")
    blocks.append(fix_instructions)

    blocks.append("\n# Required Term Injections (must appear in rewrite)\n")
    blocks.append(", ".join(missing_terms) if missing_terms else "(none)")

    blocks.append("\n# Word-Count Target\n")
    blocks.append(json.dumps({
        "current":   section.word_count,
        "target":    target_wc,
        "delta":     delta,
        "tolerance": "+/- 10%",
    }, indent=2))

    blocks.append("\n# Voice & Constraints\n")
    biz = business.model_dump(mode="json") if business is not None else {}
    blocks.append(json.dumps({
        "niche":         biz.get("niche"),
        "audience":      biz.get("audience"),
        "tone":          config.tone.value,
        "pov":           config.pov.value,
        "reading_level": config.reading_level.value,
    }, indent=2))

    eeat = brief.get("eeat_requirements") or {}
    if eeat:
        blocks.append("\n# E-E-A-T Signals to Reinforce\n")
        blocks.append(json.dumps(eeat, indent=2))

    blocks.append(
        "\n# Reminder\n"
        "Return only the rewritten section as markdown. Start with the H2 heading. "
        "No commentary, no diff, no preamble."
    )
    return "\n".join(blocks)
