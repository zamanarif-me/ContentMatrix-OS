"""
Stage 3: Term Extractor

Given SERP results, scrape the top N pages and extract:
  - Required terms (TF-IDF across competitor set)
  - Named entities (spaCy NER)
  - Co-occurring keywords (KeyBERT)

Output feeds:
  - Stage 4: Content Scorer (term coverage check)
  - Stage 5: Section Writer (entity injection)

NOTE: This is a STUB. Full implementation requires:
  pip install trafilatura spacy keybert sentence-transformers
  python -m spacy download en_core_web_lg
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from stages import cache
from stages.serp_enrichment import SerpResult


@dataclass
class TermSet:
    required_terms:    list[str] = field(default_factory=list)
    optional_terms:    list[str] = field(default_factory=list)
    entities:          list[str] = field(default_factory=list)
    avg_word_count:    int = 0
    competitor_count:  int = 0


def extract_terms_from_serp(
    serp: SerpResult,
    top_n: int = 5,
    use_cache: bool = True,
) -> TermSet:
    """
    Scrape top N URLs from a SerpResult and extract terms.

    TODO Phase 2 implementation:
      1. trafilatura.fetch_url + extract for each URL
      2. KeyBERT.extract_keywords on combined text
      3. spaCy ner_pipeline for entity extraction
      4. TF-IDF ranking across the N documents
      5. Return ranked TermSet
    """
    # Phase-1 stub: derive from SERP snippets only (no scraping yet)
    snippets = " ".join(r.get("snippet", "") for r in serp.organic[:top_n])
    words = [w.strip(".,!?:;()[]") for w in snippets.split() if len(w) > 4]

    seen: dict[str, int] = {}
    for w in words:
        wl = w.lower()
        if wl.isalpha():
            seen[wl] = seen.get(wl, 0) + 1

    top = sorted(seen.items(), key=lambda x: x[1], reverse=True)[:30]
    return TermSet(
        required_terms=[t for t, _ in top[:15]],
        optional_terms=[t for t, _ in top[15:]],
        entities=[],            # populated in Phase 2 via spaCy
        avg_word_count=0,
        competitor_count=len(serp.organic),
    )


def merge_with_brief_terms(extracted: TermSet, brief_payload: dict) -> TermSet:
    """
    Merge live SERP terms with the brief's pre-defined NLP terms.
    Brief terms take precedence (they came from the topical map analysis).
    """
    nlp = brief_payload.get("nlp_terms") or {}
    must_include = nlp.get("must_include", [])
    should_include = nlp.get("should_include", [])

    required = list(dict.fromkeys(must_include + extracted.required_terms))
    optional = list(dict.fromkeys(should_include + extracted.optional_terms))

    return TermSet(
        required_terms=required,
        optional_terms=optional,
        entities=extracted.entities,
        avg_word_count=extracted.avg_word_count,
        competitor_count=extracted.competitor_count,
    )
