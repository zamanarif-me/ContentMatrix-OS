"""
Stage 4: Content Scorer (NeuronWriter-style)

Custom scoring formula — weights are tunable per-niche.

  score = term_coverage(50) + entity_coverage(20) + structure(15)
        + word_count_fit(10) + readability(5)

Returns a QualityReport that the Refiner uses to decide pass/fail.
"""

from __future__ import annotations

import re
from typing import Optional

from content_models import (
    GeneratedArticle,
    OutlineHeading,
    QualityReport,
    ScoringTarget,
    TermCoverageReport,
)
from stages.term_extractor import TermSet


# ── Term matching ─────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def _count_term(term: str, body: str) -> int:
    """Whole-word, case-insensitive count."""
    pattern = r"\b" + re.escape(term.lower()) + r"\b"
    return len(re.findall(pattern, body))


def compute_term_coverage(
    article_md: str,
    required: list[str],
    optional: list[str],
) -> TermCoverageReport:
    body = _normalize(article_md)
    matched_req: list[str] = []
    missing_req: list[str] = []
    for t in required:
        (matched_req if _count_term(t, body) > 0 else missing_req).append(t)

    matched_opt: list[str] = []
    missing_opt: list[str] = []
    for t in optional:
        (matched_opt if _count_term(t, body) > 0 else missing_opt).append(t)

    req_n = len(required) or 1
    opt_n = len(optional) or 1
    coverage = (len(matched_req) / req_n) * 0.7 + (len(matched_opt) / opt_n) * 0.3

    return TermCoverageReport(
        must_include_total=len(required),
        must_include_matched=len(matched_req),
        should_include_total=len(optional),
        should_include_matched=len(matched_opt),
        missing_must=missing_req,
        missing_should=missing_opt,
        coverage_score=round(coverage, 3),
    )


# ── Word count fit ────────────────────────────────────────────────────────────

def _word_count_score(actual: int, target: int, tolerance: float) -> tuple[float, bool]:
    if target <= 0:
        return 1.0, True
    low, high = target * (1 - tolerance), target * (1 + tolerance)
    if low <= actual <= high:
        return 1.0, True
    diff_ratio = abs(actual - target) / target
    return max(0.0, 1.0 - diff_ratio), False


# ── Readability (Flesch) ──────────────────────────────────────────────────────

def _flesch(text: str) -> Optional[float]:
    """Simple Flesch reading ease. Returns None if text too short."""
    sentences = max(len(re.split(r"[.!?]+", text)), 1)
    words_list = re.findall(r"\b\w+\b", text)
    words = max(len(words_list), 1)
    if words < 100:
        return None
    syllables = sum(_count_syllables(w) for w in words_list)
    return 206.835 - 1.015 * (words / sentences) - 84.6 * (syllables / words)


def _count_syllables(word: str) -> int:
    word = word.lower()
    vowels = "aeiouy"
    count, prev_vowel = 0, False
    for ch in word:
        if ch in vowels:
            if not prev_vowel:
                count += 1
            prev_vowel = True
        else:
            prev_vowel = False
    if word.endswith("e") and count > 1:
        count -= 1
    return max(count, 1)


def _flesch_grade(score: float) -> str:
    if score >= 70:  return "easy (grade 7-8)"
    if score >= 50:  return "intermediate (grade 9-12)"
    if score >= 30:  return "advanced (college)"
    return "expert (graduate)"


# ── Structure ────────────────────────────────────────────────────────────────

def _structure_score(article_md: str, outline_headings: list[OutlineHeading]) -> float:
    """Does the article actually contain the headings the outline promised?"""
    if not outline_headings:
        return 0.0
    body_lower = article_md.lower()
    hit = sum(1 for h in outline_headings if h.text.lower()[:40] in body_lower)
    return hit / len(outline_headings)


# ── Top-level ────────────────────────────────────────────────────────────────

def score_article(
    article: GeneratedArticle,
    term_set: TermSet,
    target: ScoringTarget,
) -> QualityReport:
    """Produce a full QualityReport for an assembled article."""
    body = article.final_md or "\n\n".join(s.content_md for s in article.sections)

    # Components
    term_cov = compute_term_coverage(body, term_set.required_terms, term_set.optional_terms)
    entity_cov = _entity_coverage(body, term_set.entities)
    wc = len(re.findall(r"\b\w+\b", body))
    wc_pct, wc_in_range = _word_count_score(wc, target.target_word_count, target.word_count_tolerance)
    structure = _structure_score(body, article.outline.headings)
    flesch = _flesch(body)
    readability_pct = 1.0 if flesch is None else min(1.0, max(0.0, flesch / 100))

    # Weighted overall (0-100)
    overall = round(
        term_cov.coverage_score * 50
        + entity_cov               * 20
        + structure                * 15
        + wc_pct                   * 10
        + readability_pct          * 5
    )

    issues: list[str] = []
    suggestions: list[str] = []
    if term_cov.missing_must:
        issues.append(f"Missing required terms: {', '.join(term_cov.missing_must[:5])}")
        suggestions.append("Inject missing terms into relevant H2 sections")
    if not wc_in_range:
        issues.append(f"Word count {wc} outside target {target.target_word_count} ± {int(target.word_count_tolerance * 100)}%")
        suggestions.append("Expand or trim body sections to meet target")
    if structure < 0.8:
        issues.append("Outline headings not all present in final article")

    passed = (
        overall                    >= target.min_content_score
        and term_cov.coverage_score >= target.min_term_coverage
        and entity_cov              >= target.min_entity_coverage
        and wc_in_range
    )

    return QualityReport(
        overall_score=overall,
        term_coverage=term_cov,
        entity_coverage=round(entity_cov, 3),
        word_count=wc,
        word_count_target=target.target_word_count,
        word_count_in_range=wc_in_range,
        readability_score=round(flesch, 1) if flesch is not None else None,
        readability_grade=_flesch_grade(flesch) if flesch is not None else None,
        issues=issues,
        suggestions=suggestions,
        passed_target=passed,
    )


def _entity_coverage(body: str, entities: list[str]) -> float:
    if not entities:
        return 1.0
    body_low = body.lower()
    hit = sum(1 for e in entities if e.lower() in body_low)
    return hit / len(entities)
