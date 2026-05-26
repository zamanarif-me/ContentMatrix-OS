"""
Top-level pipeline orchestrator.

THIS VERSION fixes:
  - Duplicate H2 headings in outline (dedupe by lowercased text)
  - Conclusion picked from last outline heading (now synthetic "Conclusion" H2)
  - FAQ section never generated (now always added before conclusion)
  - Outline headings missing from final article (force heading preservation)
"""

from __future__ import annotations

import uuid
from pathlib import Path

from content_models import (
    ArticleStatus,
    ContentEngineInput,
    ExportFormat,
    GeneratedArticle,
    GenerationConfig,
    OutlineHeading,
    SectionType,
)
from stages import (
    content_scorer, exporter, link_injector, outline_builder,
    refiner, section_writer, serp_enrichment, term_extractor,
)
from stages.cost_tracker import tracker


def _log(msg: str) -> None:
    print(f"[pipeline] {msg}", flush=True)


def run_pipeline(
    input_: ContentEngineInput,
    config: GenerationConfig,
    output_dir: str | Path | None = None,
    progress_cb=None,
    *,
    dry_run: bool = False,
) -> GeneratedArticle:
    """Generate one article end-to-end."""
    tracker.reset()

    def _progress(stage: str, pct: float) -> None:
        _log(f"{stage} ({int(pct * 100)}%)")
        if progress_cb:
            progress_cb(stage, pct)

    # ── Stage 2: SERP enrichment ─────────────────────────────────────────────
    _progress("SERP enrichment", 0.1)
    serp = None
    if config.use_serp_enrichment and input_.target_keyword:
        serp = serp_enrichment.enrich_keyword(input_.target_keyword)
        _log(f"  organic={len(serp.organic)} | paa={len(serp.paa)} | related={len(serp.related_searches)}")

    # ── Stage 3: Term extraction ─────────────────────────────────────────────
    _progress("Term extraction", 0.2)
    terms = term_extractor.extract_terms_from_serp(serp) if serp else term_extractor.TermSet()
    terms = term_extractor.merge_with_brief_terms(terms, input_.brief_payload)
    _log(f"  required={len(terms.required_terms)} | optional={len(terms.optional_terms)}")

    # ── Stage 5: Outline ─────────────────────────────────────────────────────
    _progress("Outline build", 0.3)
    outline = outline_builder.build_outline(input_, config, serp=serp, terms=terms)
    outline = _dedupe_and_clean_outline(outline)
    _log(f"  headings={len(outline.headings)} (after dedupe) | est_words={outline.estimated_word_count}")

    # ── Stage 6: Section writing (intro → body → FAQ → conclusion) ───────────
    _progress("Section writing", 0.4)
    sections = []
    h2_body_headings = _body_h2_headings(outline)

    faq_heading        = _find_or_make_faq_heading(outline)
    conclusion_heading = _find_or_make_conclusion_heading(outline)

    total_steps = (
        len(h2_body_headings)
        + (1 if config.include_intro else 0)
        + (1 if config.include_faq else 0)
        + (1 if config.include_conclusion else 0)
    )
    done = 0

    def _tail(s) -> str:
        if not s or not s.content_md:
            return ""
        paras = [p for p in s.content_md.strip().split("\n\n") if p.strip()]
        return paras[-1] if paras else ""

    # Intro
    if config.include_intro:
        intro_heading = _find_or_make_intro_heading(outline)
        sections.append(section_writer.write_section(
            section_id="s_intro", heading=intro_heading,
            section_type=SectionType.INTRO, brief=input_.brief_payload,
            business=input_.business, config=config, dry_run=dry_run,
        ))
        done += 1
        _progress("Section writing", 0.4 + 0.4 * done / max(total_steps, 1))

    # Body H2s
    for i, h in enumerate(h2_body_headings):
        prev = sections[-1] if sections else None
        sections.append(section_writer.write_section(
            section_id=f"s_{i+1:03d}", heading=h, section_type=SectionType.BODY,
            brief=input_.brief_payload, business=input_.business, config=config,
            previous_tail=_tail(prev), dry_run=dry_run,
        ))
        done += 1
        _progress("Section writing", 0.4 + 0.4 * done / max(total_steps, 1))

    # FAQ (NEW)
    if config.include_faq:
        prev = sections[-1] if sections else None
        sections.append(section_writer.write_section(
            section_id="s_faq", heading=faq_heading,
            section_type=SectionType.FAQ, brief=input_.brief_payload,
            business=input_.business, config=config,
            previous_tail=_tail(prev), dry_run=dry_run,
        ))
        done += 1
        _progress("Section writing", 0.4 + 0.4 * done / max(total_steps, 1))

    # Conclusion (synthetic heading, not last H3)
    if config.include_conclusion:
        prev = sections[-1] if sections else None
        sections.append(section_writer.write_section(
            section_id="s_conclusion", heading=conclusion_heading,
            section_type=SectionType.CONCLUSION, brief=input_.brief_payload,
            business=input_.business, config=config,
            previous_tail=_tail(prev), dry_run=dry_run,
        ))
        done += 1

    # ── Stage 6.5: Humanization ──────────────────────────────────────────────
    if config.enable_humanization and not dry_run:
        _progress("Humanization", 0.75)
        humanized = []
        for s in sections:
            humanized.append(section_writer.humanize_section(s, config, dry_run=dry_run))
        sections = humanized
        _log(f"  humanized {len(sections)} sections")

    # ── Assembly ─────────────────────────────────────────────────────────────
    article = GeneratedArticle(
        article_id=f"art_{uuid.uuid4().hex[:12]}",
        page_id=input_.brief_payload.get("page_id", "unknown"),
        title=outline.title,
        meta_description=outline.meta_description,
        outline=outline,
        sections=sections,
        config_used=config,
        business_context=input_.business,
        status=ArticleStatus.READY,
    )
    article.final_md = exporter.assemble_markdown(article)

    # ── Stage 7B: Internal link injection ───────────────────────────────────
    if config.enable_internal_linking:
        _progress("Internal linking", 0.82)
        report = link_injector.inject_from_brief(
            article,
            bridges=input_.brief_payload.get("semantic_bridges") or [],
            next_destination=input_.brief_payload.get("next_destination"),
        )
        _log(
            f"  bridges: {report.bridges_wrapped} wrapped, "
            f"{report.bridges_appended} appended, "
            f"{report.bridges_skipped} skipped | "
            f"next_dest: {'yes' if report.next_dest_added else 'no'}"
        )

    # ── Stage 4: Score ───────────────────────────────────────────────────────
    _progress("Quality scoring", 0.85)
    quality = content_scorer.score_article(article, terms, config.scoring_target)
    article.quality = quality
    _log(f"  score={quality.overall_score}/100 | passed={quality.passed_target}")

    # ── Stage 7: Refine ──────────────────────────────────────────────────────
    if not quality.passed_target:
        _progress("Refinement", 0.9)
        article, quality = refiner.refine_until_target(
            article, quality, config,
            brief=input_.brief_payload,
            business=input_.business,
            terms=terms,
            dry_run=dry_run,
        )
        article.quality = quality
        _log(f"  after refine: score={quality.overall_score}/100 | passes={article.refine_passes}")

    article.status = ArticleStatus.COMPLETE if quality.passed_target else ArticleStatus.READY
    article.cost_usd = tracker.total_cost
    article.total_tokens = tracker.total_input_tokens + tracker.total_output_tokens

    # ── Stage 8: Export ──────────────────────────────────────────────────────
    if output_dir is not None:
        _progress("Export", 0.95)
        exporter.export_bundle(
            article,
            formats=[ExportFormat.MARKDOWN, ExportFormat.HTML, ExportFormat.JSON],
            out_dir=output_dir,
        )

    _progress("Done", 1.0)
    return article


# ── Outline helpers ──────────────────────────────────────────────────────────

def _dedupe_and_clean_outline(outline):
    """Remove duplicate headings (case-insensitive) and strip empty ones."""
    seen = set()
    kept = []
    for h in outline.headings:
        text = (h.text or "").strip()
        if not text:
            continue
        norm = text.lower().rstrip(".:;!?")
        if norm in seen:
            continue
        seen.add(norm)
        kept.append(h)
    outline.headings = kept
    return outline


def _body_h2_headings(outline) -> list:
    """Return H2 headings suitable for the BODY (excludes intro/FAQ/conclusion-like)."""
    body = []
    for h in outline.headings:
        if h.level != "H2":
            continue
        if _is_intro_like(h.text):
            continue
        if _is_faq_like(h.text):
            continue
        if _is_conclusion_like(h.text):
            continue
        body.append(h)
    return body


def _find_or_make_intro_heading(outline):
    for h in outline.headings:
        if h.level == "H2" and _is_intro_like(h.text):
            return h
    return OutlineHeading(
        level="H2",
        text="Introduction",
        semantic_purpose="Hook the reader and preview the article scope",
        target_word_count=150,
        target_entities=[],
        target_queries=[],
    )


def _find_or_make_faq_heading(outline):
    for h in outline.headings:
        if _is_faq_like(h.text):
            return h
    return OutlineHeading(
        level="H2",
        text="Frequently Asked Questions",
        semantic_purpose="Answer common reader questions with concise paragraphs",
        target_word_count=350,
        target_entities=[],
        target_queries=[],
    )


def _find_or_make_conclusion_heading(outline):
    for h in outline.headings:
        if h.level == "H2" and _is_conclusion_like(h.text):
            return h
    return OutlineHeading(
        level="H2",
        text="Conclusion",
        semantic_purpose="Summarize key takeaways and present a clear next step",
        target_word_count=180,
        target_entities=[],
        target_queries=[],
    )


# ── Heading type detection ───────────────────────────────────────────────────

_INTRO_TOKENS = ("intro", "introduction", "overview", "getting started")
_FAQ_TOKENS = ("faq", "frequently asked", "common questions", "questions answered")
_CONCLUSION_TOKENS = (
    "conclusion", "final thought", "wrapping up", "wrap up",
    "key takeaways", "summary", "bottom line",
)


def _is_intro_like(text: str) -> bool:
    t = (text or "").lower().strip()
    return any(tok in t for tok in _INTRO_TOKENS)


def _is_faq_like(text: str) -> bool:
    t = (text or "").lower().strip()
    return any(tok in t for tok in _FAQ_TOKENS)


def _is_conclusion_like(text: str) -> bool:
    t = (text or "").lower().strip()
    return any(tok in t for tok in _CONCLUSION_TOKENS)
