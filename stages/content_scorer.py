"""
Stage 4: Content Scorer (NeuronWriter-style)

Custom scoring formula — weights are tunable per-niche.
  score = term_coverage(50) + entity_coverage(20) + structure(15)
        + word_count_fit(10) + readability(5)

This version (improvements vs old scorer):
  - Noise-term filter — drops "services, trimming, provides, following" etc.
    from "required terms" check before scoring
  - Adaptive word-count tolerance — 30% instead of strict 20% for large articles
  - Smarter heading match — significant-word overlap, not just 40-char prefix
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


# ── Noise terms (skip from required terms) ──────────────────────────────────

_NOISE_TERMS = {
    "provide", "provides", "provided", "providing",
    "offer", "offers", "offered", "offering",
    "make", "makes", "making", "made",
    "use", "uses", "used", "using",
    "include", "includes", "included", "including",
    "consider", "considers", "considered", "considering",
    "follow", "follows", "followed", "following",
    "help", "helps", "helped", "helping",
    "ensure", "ensures", "ensured", "ensuring",
    "require", "requires", "required", "requiring",
    "allow", "allows", "allowed", "allowing",
    "create", "creates", "created", "creating",
    "give", "gives", "given", "giving",
    "find", "finds", "finding", "found",
    "know", "knows", "knowing", "known",
    "services", "service", "thing", "things", "way", "ways",
    "people", "person", "time", "times", "year", "years",
    "day", "days", "work", "works", "place", "places",
    "part", "parts", "type", "types", "kind", "kinds",
    "very", "really", "quite", "rather", "much", "many",
    "great", "good", "best", "better", "small", "large",
    "high", "higher", "low", "lower", "different", "same",
    "new", "old", "first", "last", "next", "previous",
    "trimming", "removing",
}


def _is_noise(term: str) -> bool:
    t = (term or "").strip().lower()
    if not t:
        return True
    if " " in t or "-" in t:
        return False
    return t in _NOISE_TERMS


def _filter_noise(terms: list[str]) -> list[str]:
    return [t for t in terms if not _is_noise(t)]


# ── Term matching ─────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def _count_term(term: str, body: str) -> int:
    pattern = r"\b" + re.escape(term.lower()) + r"\b"
    return len(re.findall(pattern, body))


def compute_term_coverage(
    article_md: str,
    required: list[str],
    optional: list[str],
) -> TermCoverageReport:
    required = _filter_noise(required)
    optional = _filter_noise(optional)

    body = _normalize(article_md)
    matched_req, missing_req = [], []
    for t in required:
        (matched_req if _count_term(t, body) > 0 else missing_req).append(t)

    matched_opt, missing_opt = [], []
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


# ── Word count fit (adaptive tolerance) ──────────────────────────────────────

def _word_count_score(actual: int, target: int, tolerance: float) -> tuple[float, bool]:
    if target <= 0:
        return 1.0, True
    effective_tol = tolerance + (0.10 if target >= 2000 else 0.05)
    low, high = target * (1 - effective_tol), target * (1 + effective_tol)
    if low <= actual <= high:
        return 1.0, True
    diff_ratio = abs(actual - target) / target
    return max(0.0, 1.0 - diff_ratio * 0.5), False


# ── Readability ──────────────────────────────────────────────────────────────

def _flesch(text: str) -> Optional[float]:
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


# ── Structure (smart heading match) ──────────────────────────────────────────

_STOP = {
    "the", "a", "an", "of", "to", "in", "for", "and", "or",
    "is", "are", "was", "were", "be", "been", "have", "has",
    "with", "from", "by", "on", "at", "as", "this", "that",
}


def _significant_words(text: str) -> set[str]:
    tokens = re.findall(r"[a-zA-Z]{3,}", text.lower())
    return {t for t in tokens if t not in _STOP}


def _structure_score(article_md: str, outline_headings: list[OutlineHeading]) -> float:
    if not outline_headings:
        return 0.0

    body_lower = article_md.lower()
    article_h2_lines = re.findall(r"^\s*##\s+(.+)$", article_md, flags=re.MULTILINE)
    article_h2_word_sets = [_significant_words(line) for line in article_h2_lines]

    hits = 0
    for h in outline_headings:
        text_low = h.text.lower().strip()
        if not text_low:
            continue
        if text_low[:40] in body_lower:
            hits += 1
            continue
        outline_words = _significant_words(h.text)
        if not outline_words:
            hits += 1
            continue
        for art_words in article_h2_word_sets:
            if not art_words:
                continue
            overlap = len(outline_words & art_words) / len(outline_words)
            if overlap >= 0.6:
                hits += 1
                break

    return hits / len(outline_headings)


# ── Top-level ────────────────────────────────────────────────────────────────

def score_article(
    article: GeneratedArticle,
    term_set: TermSet,
    target: ScoringTarget,
) -> QualityReport:
    body = article.final_md or "\n\n".join(s.content_md for s in article.sections)

    term_cov = compute_term_coverage(body, term_set.required_terms, term_set.optional_terms)
    entity_cov = _entity_coverage(body, term_set.entities)
    wc = len(re.findall(r"\b\w+\b", body))
    wc_pct, wc_in_range = _word_count_score(wc, target.target_word_count, target.word_count_tolerance)
    structure = _structure_score(body, article.outline.headings)
    flesch = _flesch(body)
    readability_pct = 1.0 if flesch is None else min(1.0, max(0.0, flesch / 100))

    overall = round(
        term_cov.coverage_score * 50
        + entity_cov               * 20
        + structure                * 15
        + wc_pct                   * 10
        + readability_pct          * 5
    )

    issues, suggestions = [], []
    if term_cov.missing_must:
        issues.append(f"Missing required terms: {', '.join(term_cov.missing_must[:5])}")
        suggestions.append("Inject missing terms into relevant H2 sections")
    if not wc_in_range:
        eff_tol = int((target.word_count_tolerance + (0.10 if target.target_word_count >= 2000 else 0.05)) * 100)
        issues.append(f"Word count {wc} outside target {target.target_word_count} ± {eff_tol}%")
        suggestions.append("Expand or trim body sections to meet target")
    if structure < 0.8:
        issues.append(f"Outline headings only {int(structure*100)}% present in final article")

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
