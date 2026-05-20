"""
Stage 3: Term Extractor — Phase 2C

Full competitor analysis pipeline:
  1. trafilatura.fetch_url  — scrape top N SERP URLs (cached 7 days per URL)
  2. scikit-learn TF-IDF    — rank terms across N competitor docs
  3. spaCy en_core_web_sm   — Named Entity Recognition (ORG, PRODUCT, GPE, …)
  4. merge_with_brief_terms — brief nlp_terms take precedence over SERP terms

Graceful degradation:
  - If trafilatura fails on a URL → skip that URL
  - If no URLs scraped        → fall back to snippet-frequency method
  - If scikit-learn absent    → fall back to simple word-frequency ranking
  - If spaCy absent/OSError   → entities = [] (score still works, just empty)

Caching:
  - Per-URL text:        cache key = hash(url)           TTL = 7 days
  - Whole TermSet:       cache key = hash(urls, top_n)   TTL = 3 days
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from stages import cache
from stages.serp_enrichment import SerpResult


# ── Stop word set (augmented English) ────────────────────────────────────────

_STOP = {
    "the", "and", "for", "that", "this", "with", "from", "are", "was", "were",
    "have", "has", "had", "been", "will", "would", "could", "should", "may",
    "can", "but", "not", "all", "also", "more", "than", "about", "into",
    "its", "your", "their", "our", "you", "they", "them", "what", "when",
    "how", "which", "who", "any", "each", "some", "most", "such", "only",
    "other", "use", "used", "using", "make", "made", "need", "needs",
    "just", "very", "get", "got", "like", "well", "even", "here", "there",
    "then", "than", "where", "does", "did", "one", "two", "three", "four",
    "five", "many", "much", "few", "new", "good", "best", "first", "last",
    "next", "same", "different", "great", "large", "small", "high", "low",
}


# ── Public data model ─────────────────────────────────────────────────────────

@dataclass
class TermSet:
    """
    Extracted term data fed to Stage 4 (scorer) and Stage 5 (section writer).

    required_terms  → must_include in scoring (from brief nlp_terms + top TF-IDF)
    optional_terms  → should_include in scoring
    entities        → NER-extracted proper nouns for entity_coverage scoring
    avg_word_count  → competitor average — used to calibrate target_word_count
    competitor_count → how many URLs were successfully scraped
    """
    required_terms:   list[str] = field(default_factory=list)
    optional_terms:   list[str] = field(default_factory=list)
    entities:         list[str] = field(default_factory=list)
    avg_word_count:   int = 0
    competitor_count: int = 0


# ── Public API ────────────────────────────────────────────────────────────────

def extract_terms_from_serp(
    serp: SerpResult,
    top_n: int = 5,
    use_cache: bool = True,
) -> TermSet:
    """
    Phase-2C: scrape top N competitor URLs → TF-IDF + NER → ranked TermSet.
    Falls back to snippet analysis if scraping yields nothing.
    """
    if not serp or not serp.organic:
        return TermSet()

    urls = [r.get("url", "") for r in serp.organic[:top_n] if r.get("url")]

    # Whole-TermSet cache
    ts_key = cache.make_cache_key("termset_v2", urls, top_n)
    if use_cache:
        hit = cache.get(ts_key)
        if hit:
            d = hit["termset"]
            return TermSet(
                required_terms=d.get("required_terms", []),
                optional_terms=d.get("optional_terms", []),
                entities=d.get("entities", []),
                avg_word_count=d.get("avg_word_count", 0),
                competitor_count=d.get("competitor_count", 0),
            )

    # Scrape
    docs, word_counts = _scrape_urls(urls, use_cache)

    if not docs:
        return _from_snippets(serp, top_n)

    required, optional = _tfidf_rank(docs)
    combined_text = " ".join(docs)
    entities = _extract_entities(combined_text)
    avg_wc = sum(word_counts) // max(len(word_counts), 1)

    termset = TermSet(
        required_terms=required,
        optional_terms=optional,
        entities=entities,
        avg_word_count=avg_wc,
        competitor_count=len(docs),
    )

    if use_cache:
        cache.put(ts_key, "term_index", {
            "termset": {
                "required_terms":   termset.required_terms,
                "optional_terms":   termset.optional_terms,
                "entities":         termset.entities,
                "avg_word_count":   termset.avg_word_count,
                "competitor_count": termset.competitor_count,
            }
        }, ttl_days=3)

    return termset


def merge_with_brief_terms(extracted: TermSet, brief_payload: dict) -> TermSet:
    """
    Merge live SERP terms with the brief's pre-defined NLP terms.
    Brief terms take precedence — they came from topical map analysis.
    """
    nlp = brief_payload.get("nlp_terms") or {}
    must_include = nlp.get("must_include", [])
    should_include = nlp.get("should_include", [])

    required = list(dict.fromkeys(must_include + extracted.required_terms))[:40]
    optional = list(dict.fromkeys(should_include + extracted.optional_terms))[:40]

    return TermSet(
        required_terms=required,
        optional_terms=optional,
        entities=extracted.entities,
        avg_word_count=extracted.avg_word_count,
        competitor_count=extracted.competitor_count,
    )


# ── URL scraping ─────────────────────────────────────────────────────────────

def _scrape_urls(urls: list[str], use_cache: bool) -> tuple[list[str], list[int]]:
    try:
        import trafilatura
    except ImportError:
        return [], []

    docs: list[str] = []
    word_counts: list[int] = []

    for url in urls:
        url_key = cache.make_cache_key("url_text_v1", url)
        if use_cache:
            hit = cache.get(url_key)
            if hit:
                text = hit.get("text", "")
            else:
                text = _fetch_one(url, trafilatura)
                cache.put(url_key, "term_index", {"text": text}, ttl_days=7)
        else:
            text = _fetch_one(url, trafilatura)

        if len(text) > 300:
            docs.append(text)
            word_counts.append(len(text.split()))

    return docs, word_counts


def _fetch_one(url: str, trafilatura) -> str:
    try:
        downloaded = trafilatura.fetch_url(url, timeout=10)
        if not downloaded:
            return ""
        text = trafilatura.extract(
            downloaded,
            include_tables=False,
            include_links=False,
            no_fallback=False,
            favor_recall=True,
        )
        return text or ""
    except Exception:
        return ""


# ── TF-IDF ranking ────────────────────────────────────────────────────────────

def _tfidf_rank(docs: list[str]) -> tuple[list[str], list[str]]:
    try:
        import numpy as np
        from sklearn.feature_extraction.text import TfidfVectorizer

        vec = TfidfVectorizer(
            max_features=300,
            stop_words="english",
            ngram_range=(1, 2),
            min_df=1,
            max_df=0.90,
            token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z]{2,}\b",
        )
        X = vec.fit_transform(docs)
        scores = np.asarray(X.mean(axis=0)).flatten()
        feature_names = vec.get_feature_names_out()

        ranked = sorted(
            zip(feature_names, scores),
            key=lambda x: x[1],
            reverse=True,
        )

        filtered: list[str] = []
        for term, _ in ranked:
            parts = term.split()
            if len(parts) == 1:
                if term not in _STOP and len(term) >= 4:
                    filtered.append(term)
            else:
                filtered.append(term)
            if len(filtered) >= 40:
                break

        return filtered[:20], filtered[20:40]

    except ImportError:
        return _frequency_rank(docs)


def _frequency_rank(docs: list[str]) -> tuple[list[str], list[str]]:
    freq: dict[str, int] = {}
    for doc in docs:
        seen_in_doc: set[str] = set()
        for raw in doc.split():
            w = raw.strip(".,!?:;()[]\"'").lower()
            if len(w) >= 4 and w.isalpha() and w not in _STOP and w not in seen_in_doc:
                freq[w] = freq.get(w, 0) + 1
                seen_in_doc.add(w)

    ranked = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    required = [t for t, _ in ranked[:20]]
    optional = [t for t, _ in ranked[20:40]]
    return required, optional


# ── Named Entity Recognition ─────────────────────────────────────────────────

_NLP = None


def _get_nlp():
    global _NLP
    if _NLP is not None:
        return _NLP
    try:
        import spacy
        try:
            _NLP = spacy.load("en_core_web_sm")
        except (OSError, Exception):
            _NLP = spacy.blank("en")
        return _NLP
    except ImportError:
        return None


def _extract_entities(text: str) -> list[str]:
    nlp = _get_nlp()
    if nlp is None:
        return []

    doc = nlp(text[:60_000])
    _WANTED = {"ORG", "PRODUCT", "GPE", "PERSON", "WORK_OF_ART", "LAW", "FAC"}
    seen: set[str] = set()
    entities: list[str] = []

    for ent in doc.ents:
        name = ent.text.strip()
        if (
            ent.label_ in _WANTED
            and len(name) > 2
            and name not in seen
            and not name.isnumeric()
        ):
            entities.append(name)
            seen.add(name)
        if len(entities) >= 30:
            break

    return entities


# ── Snippet fallback ─────────────────────────────────────────────────────────

def _from_snippets(serp: SerpResult, top_n: int) -> TermSet:
    snippets = " ".join(r.get("snippet", "") for r in serp.organic[:top_n])
    words = [w.strip(".,!?:;()[]") for w in snippets.split() if len(w) > 4]

    freq: dict[str, int] = {}
    for w in words:
        wl = w.lower()
        if wl.isalpha() and wl not in _STOP:
            freq[wl] = freq.get(wl, 0) + 1

    top = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:30]
    return TermSet(
        required_terms=[t for t, _ in top[:15]],
        optional_terms=[t for t, _ in top[15:]],
        entities=[],
        avg_word_count=0,
        competitor_count=len(serp.organic),
    )
