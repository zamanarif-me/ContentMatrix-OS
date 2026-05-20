"""
Stage 7: Refiner (score-gated loop)

If QualityReport.passed_target is False, identify the worst sections and
rewrite them with the refine_model (default: Claude Sonnet).

Refinement strategies:
  - Missing required term  -> inject naturally into most relevant section
  - Word count too low     -> expand body sections proportionally
  - Word count too high    -> tighten verbose sections
  - Structure mismatch     -> regenerate the section with stricter outline adherence

Hard limit: ScoringTarget.max_refine_passes prevents infinite loops.
"""

from __future__ import annotations

from content_models import (
    GeneratedArticle,
    GenerationConfig,
    QualityReport,
    SectionDraft,
)


def refine_until_target(
    article: GeneratedArticle,
    quality: QualityReport,
    config: GenerationConfig,
) -> tuple[GeneratedArticle, QualityReport]:
    """
    Phase-1 stub: no-op. Returns the article and quality unchanged.

    Phase-2 implementation:
      while not quality.passed_target and article.refine_passes < max:
          identify worst section by score contribution
          build refinement prompt with explicit fix instructions
          call refine_model
          re-score
          increment refine_passes
    """
    article.refine_passes = 0
    return article, quality
