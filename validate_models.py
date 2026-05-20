"""
Validation script for content_models.py

Tests:
  1. All models load and validate against example_input.json
  2. GenerationConfig validates against example_generation_config.json
  3. End-to-end synthetic GeneratedArticle can be constructed
  4. JSON round-trip works (serialize → parse → equal)

Run:
    cd content-creation-engine
    pip install pydantic
    python validate_models.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from content_models import (
    ArticleOutline,
    ArticleStatus,
    BusinessCategory,
    BusinessContext,
    ContentEngineInput,
    ContentFormat,
    GeneratedArticle,
    GenerationConfig,
    OutlineHeading,
    POV,
    QualityReport,
    SectionDraft,
    SectionType,
    TermCoverageReport,
    WritingModel,
    WritingTone,
)


SCRIPT_DIR = Path(__file__).parent


def _ok(msg: str) -> None:
    print(f"  PASS  {msg}")


def _fail(msg: str, err: Exception) -> None:
    print(f"  FAIL  {msg}")
    print(f"        {type(err).__name__}: {err}")
    sys.exit(1)


# ── Test 1: Load example_input.json into ContentEngineInput ─────────────
def test_input_validates() -> ContentEngineInput:
    print("\n[TEST 1] example_input.json → ContentEngineInput")
    try:
        raw = json.loads((SCRIPT_DIR / "example_input.json").read_text())
        ci = ContentEngineInput.model_validate(raw)
        assert ci.business.category == BusinessCategory.SERVICE_BUSINESS
        assert "WordPress" in ci.business.niche
        assert ci.brief_payload["page_id"] == "cluster_malware_removal_001"
        assert ci.topical_map_ref is not None
        assert len(ci.topical_map_ref.pillars) == 3
        _ok("Loaded, all assertions passed")
        return ci
    except Exception as e:
        _fail("Input validation failed", e)


# ── Test 2: Load example_generation_config.json → GenerationConfig ──────
def test_config_validates() -> GenerationConfig:
    print("\n[TEST 2] example_generation_config.json → GenerationConfig")
    try:
        raw = json.loads((SCRIPT_DIR / "example_generation_config.json").read_text())
        cfg = GenerationConfig.model_validate(raw)
        assert cfg.content_format == ContentFormat.GUIDE
        assert cfg.model_strategy.section_model == WritingModel.GEMINI_FLASH
        assert cfg.model_strategy.refine_model == WritingModel.CLAUDE_SONNET
        assert cfg.scoring_target.min_content_score == 75
        assert cfg.scoring_target.target_word_count == 2500
        _ok("Loaded, all assertions passed")
        return cfg
    except Exception as e:
        _fail("Config validation failed", e)


# ── Test 3: Build a synthetic GeneratedArticle end-to-end ───────────────
def test_full_article_construct(ci: ContentEngineInput, cfg: GenerationConfig) -> None:
    print("\n[TEST 3] Synthetic GeneratedArticle end-to-end")
    try:
        outline = ArticleOutline(
            title=ci.brief_payload["page_title"],
            meta_description="Complete guide to WordPress malware removal.",
            slug="wordpress-malware-removal",
            primary_keyword=ci.target_keyword or "",
            estimated_word_count=cfg.scoring_target.target_word_count,
            headings=[
                OutlineHeading(level="H1", text="WordPress Malware Removal: Complete Guide",
                               semantic_purpose="Establish authority", target_word_count=0),
                OutlineHeading(level="H2", text="Signs Your Site Is Infected",
                               semantic_purpose="Symptom detection", target_word_count=400,
                               target_entities=["malware scanner", "Wordfence"]),
                OutlineHeading(level="H2", text="Step-by-Step Manual Removal",
                               semantic_purpose="Core how-to", target_word_count=800,
                               target_entities=["SSH access", "wp-content"]),
            ],
        )

        section1 = SectionDraft(
            section_id="s_001",
            section_type=SectionType.INTRO,
            heading=outline.headings[0],
            content_md="# WordPress Malware Removal: Complete Guide\n\nMalware infections affect...",
            word_count=120,
            used_entities=["malware"],
            matched_terms=["malware"],
            model_used=WritingModel.GEMINI_FLASH.value,
            cache_key="abc123def456",
        )

        section2 = SectionDraft(
            section_id="s_002",
            section_type=SectionType.BODY,
            heading=outline.headings[1],
            content_md="## Signs Your Site Is Infected\n\nWordfence and similar scanners detect...",
            word_count=420,
            used_entities=["Wordfence", "malware scanner"],
            matched_terms=["Wordfence", "malware scanner"],
            model_used=WritingModel.GEMINI_FLASH.value,
            cache_key="def456ghi789",
        )

        # Test heading level normalization
        h_lower = OutlineHeading(level="h3", text="Sub-heading test")
        assert h_lower.level == "H3", f"Level normalization failed: got {h_lower.level}"

        h_int = OutlineHeading(level=2, text="Integer level test")
        assert h_int.level == "H2", f"Integer level normalization failed: got {h_int.level}"

        quality = QualityReport(
            overall_score=78,
            term_coverage=TermCoverageReport(
                must_include_total=7,
                must_include_matched=6,
                should_include_total=5,
                should_include_matched=3,
                missing_must=["WAF"],
                coverage_score=0.75,
            ),
            entity_coverage=0.68,
            word_count=540,
            word_count_target=2500,
            word_count_in_range=False,
            readability_score=58.0,
            readability_grade="10th grade",
            issues=["Word count below target"],
            suggestions=["Expand body sections", "Add FAQ"],
            passed_target=False,
        )

        article = GeneratedArticle(
            article_id="art_test_001",
            page_id=ci.brief_payload["page_id"],
            title=outline.title,
            meta_description=outline.meta_description,
            outline=outline,
            sections=[section1, section2],
            final_md=section1.content_md + "\n\n" + section2.content_md,
            status=ArticleStatus.READY,
            quality=quality,
            config_used=cfg,
            business_context=ci.business,
            cost_usd=0.12,
            total_tokens=4500,
        )

        assert article.article_id == "art_test_001"
        assert len(article.sections) == 2
        assert article.quality.overall_score == 78
        assert article.business_context.category == BusinessCategory.SERVICE_BUSINESS
        _ok("All construction + heading normalization assertions passed")
        return article
    except Exception as e:
        _fail("Article construction failed", e)


# ── Test 4: JSON round-trip ─────────────────────────────────────────────
def test_round_trip(ci: ContentEngineInput) -> None:
    print("\n[TEST 4] JSON round-trip (model → JSON → model)")
    try:
        as_json = ci.model_dump_json()
        parsed = json.loads(as_json)
        ci2 = ContentEngineInput.model_validate(parsed)
        assert ci.business.niche == ci2.business.niche
        assert ci.brief_payload["page_id"] == ci2.brief_payload["page_id"]
        assert ci.brief_source == ci2.brief_source
        _ok("Round-trip preserves all fields")
    except Exception as e:
        _fail("Round-trip failed", e)


# ── Test 5: BusinessContext minimal construction ────────────────────────
def test_minimal_business_context() -> None:
    print("\n[TEST 5] Minimal BusinessContext (any niche works)")
    try:
        # Should work for ANY niche, not just WordPress
        cases = [
            (BusinessCategory.LOCAL_BUSINESS, "Italian restaurant in Brooklyn"),
            (BusinessCategory.HEALTHCARE, "Pediatric dental clinic"),
            (BusinessCategory.SOFTWARE_PRODUCT, "Project management SaaS"),
            (BusinessCategory.AGENCY, "B2B SEO agency"),
        ]
        for cat, niche in cases:
            bc = BusinessContext(category=cat, niche=niche)
            assert bc.category == cat
            assert bc.niche == niche
        _ok(f"Validated {len(cases)} diverse business types — no WordPress lock-in")
    except Exception as e:
        _fail("Minimal BusinessContext failed", e)


# ── Run all ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print(" content_models.py — Validation Suite")
    print("=" * 60)

    ci = test_input_validates()
    cfg = test_config_validates()
    article = test_full_article_construct(ci, cfg)
    test_round_trip(ci)
    test_minimal_business_context()

    print("\n" + "=" * 60)
    print("  ALL TESTS PASSED")
    print("=" * 60)
