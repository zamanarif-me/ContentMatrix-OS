"""
ContentMatrix OS — Data Models

Generic, niche-agnostic Pydantic schemas for AI content generation.

DESIGNED TO CONSUME OUTPUT FROM:
  - topical-map-engine-pro/sessions/<id>/topical_map.json
  - topical-map-engine-pro/sessions/<id>/briefs/all_briefs.json

ALSO SUPPORTS:
  - Manual brief upload (JSON / form)
  - Single-article generation
  - Bulk batch generation

KEY DESIGN DECISIONS:
  1. BusinessCategory + free-text niche → replaces WordPress-only BusinessFocus
  2. brief_payload is a raw dict → loose coupling with existing ContentBrief schema
  3. ModelStrategy enum → hybrid LLM strategy (cheap drafts + premium refinement)
  4. ScoringTarget → NeuronWriter-style content score gating
  5. cache_key on every generated section → enables response cache lookup
  6. Forward-compatible: optional fields throughout, no enum lock-in
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ════════════════════════════════════════════════════════════════════
# ENUMS — Generic, niche-agnostic
# ════════════════════════════════════════════════════════════════════

class BusinessCategory(str, Enum):
    """
    Broad business categories. Pair with free-text `niche` for specificity.

    Replaces WordPress-specific BusinessFocus from topical-map-engine.
    Covers ~95% of real client scenarios.
    """
    SERVICE_BUSINESS  = "service_business"     # HVAC, cleaning, plumber, lawyer
    SOFTWARE_PRODUCT  = "software_product"     # SaaS, plugin, mobile app
    ECOMMERCE         = "ecommerce"            # online store, dropshipping
    AGENCY            = "agency"               # marketing/dev/SEO agency
    LOCAL_BUSINESS    = "local_business"       # restaurant, salon, gym
    CONTENT_SITE      = "content_site"         # blog, news, media
    EDUCATION         = "education"            # course, training, school
    HEALTHCARE        = "healthcare"           # clinic, telehealth
    FINANCE           = "finance"              # advisor, fintech
    REAL_ESTATE       = "real_estate"          # broker, prop-tech
    NONPROFIT         = "nonprofit"            # charity, foundation
    OTHER             = "other"


class SearchIntent(str, Enum):
    INFORMATIONAL  = "informational"
    COMMERCIAL     = "commercial"
    TRANSACTIONAL  = "transactional"
    NAVIGATIONAL   = "navigational"


class ContentFormat(str, Enum):
    """The shape of the article — drives outline structure + prompt selection."""
    HOW_TO         = "how_to"
    LISTICLE       = "listicle"
    GUIDE          = "guide"             # long-form pillar
    COMPARISON     = "comparison"        # X vs Y
    REVIEW         = "review"            # product review
    CASE_STUDY     = "case_study"
    LANDING_PAGE   = "landing_page"
    SERVICE_PAGE   = "service_page"
    DEFINITION     = "definition"        # "what is X" pages
    OPINION        = "opinion"           # editorial


class WritingTone(str, Enum):
    PROFESSIONAL    = "professional"
    CONVERSATIONAL  = "conversational"
    AUTHORITATIVE   = "authoritative"
    FRIENDLY        = "friendly"
    TECHNICAL       = "technical"
    PERSUASIVE      = "persuasive"


class POV(str, Enum):
    FIRST_PERSON_SINGULAR  = "first_person_singular"   # "I think..."
    FIRST_PERSON_PLURAL    = "first_person_plural"      # "We recommend..."
    SECOND_PERSON          = "second_person"            # "You should..."
    THIRD_PERSON           = "third_person"             # "They report..."


class ReadingLevel(str, Enum):
    BEGINNER       = "beginner"        # Flesch ~70+, grade 6-8
    INTERMEDIATE   = "intermediate"    # Flesch ~50-70, grade 9-12
    ADVANCED       = "advanced"        # Flesch ~30-50, college
    EXPERT         = "expert"          # Flesch <30, specialist


class WritingModel(str, Enum):
    """Available LLM models. Update IDs as providers release new versions."""
    GEMINI_FLASH    = "gemini-2.0-flash"
    GEMINI_PRO      = "gemini-2.5-pro"
    CLAUDE_HAIKU    = "claude-haiku-4-5"
    CLAUDE_SONNET   = "claude-sonnet-4-6"
    CLAUDE_OPUS     = "claude-opus-4-7"


class SectionType(str, Enum):
    INTRO          = "intro"
    BODY           = "body"
    FAQ            = "faq"
    CONCLUSION     = "conclusion"
    CTA            = "cta"


class ArticleStatus(str, Enum):
    DRAFT          = "draft"           # outline only
    GENERATING     = "generating"
    READY          = "ready"           # all sections done, not yet QA'd
    REFINING       = "refining"        # in refinement loop
    COMPLETE       = "complete"        # passed quality target
    FAILED         = "failed"


class BriefSource(str, Enum):
    """Where the brief came from — drives validation strictness."""
    UPLOADED        = "uploaded"               # manual JSON/CSV upload
    FROM_ENGINE     = "from_topical_engine"    # from topical-map-engine output
    GENERATED       = "generated"              # AI-generated on the fly
    MANUAL_FORM     = "manual_form"            # filled via UI form


class ExportFormat(str, Enum):
    MARKDOWN  = "markdown"
    DOCX      = "docx"
    HTML      = "html"
    JSON      = "json"
    PLAIN     = "plain"


# ════════════════════════════════════════════════════════════════════
# INPUT MODELS — what the user/system feeds in
# ════════════════════════════════════════════════════════════════════

class BusinessContext(BaseModel):
    """
    Generic business identity. Replaces WordPress-specific BusinessFocus enum
    from topical-map-engine. Pair `category` with free-text `niche`.

    Example:
        category=SERVICE_BUSINESS
        niche="WordPress security and malware removal"
        audience=["WP site owners", "agencies managing client sites"]
    """
    category:          BusinessCategory
    niche:             str = Field(..., min_length=2, description="Specific niche, free-text")
    audience:          list[str] = Field(default_factory=list)
    brand_name:        Optional[str] = None
    brand_voice_notes: Optional[str] = Field(
        default=None,
        description="Free-text style guidance (vocabulary, banned phrases, persona)"
    )
    reference_urls:    list[str] = Field(
        default_factory=list,
        description="2-3 existing brand articles for tone calibration (few-shot)"
    )
    language:          str = "en-US"


class TopicalMapRef(BaseModel):
    """
    Lightweight pointer to an existing topical map. Used for:
      - Internal linking suggestions
      - Sibling page awareness
      - Pillar/cluster context

    `pillars` and `geo_pages` are loaded as raw dicts to avoid importing
    topical-map-engine models (loose coupling).
    """
    source:    str = Field(..., description="File path OR session_id of topical_map.json")
    central_entity: Optional[str] = None
    pillars:   list[dict] = Field(default_factory=list)
    geo_pages: list[dict] = Field(default_factory=list)


class ContentEngineInput(BaseModel):
    """
    Top-level input to the engine. ONE article generation request.

    The `brief_payload` is a raw dict matching the ContentBrief schema from
    topical-map-engine-pro/stages/brief.py — we keep it loose to allow:
      - Schema evolution without breaking changes
      - Manual upload of partial briefs
      - Future brief formats
    """
    business:        BusinessContext
    brief_source:    BriefSource
    brief_payload:   dict = Field(
        ...,
        description="Raw ContentBrief dict. Required keys: page_id, page_title, "
                    "queries, headings, nlp_terms, content_specs"
    )
    topical_map_ref: Optional[TopicalMapRef] = None
    target_keyword:  Optional[str] = Field(
        default=None,
        description="Override — if not set, derived from brief_payload.queries.primary_query"
    )


# ════════════════════════════════════════════════════════════════════
# GENERATION CONFIG — user-tunable knobs
# ════════════════════════════════════════════════════════════════════

class ModelStrategy(BaseModel):
    """
    Which LLM does which job — enables hybrid cost saving.

    Approved model set for ContentMatrix OS:
      - gemini-2.0-flash   (bulk drafting, cheap)
      - claude-sonnet-4-6  (quality refinement, scoring)

    Other models remain in WritingModel enum for future flexibility,
    but the default + UI are restricted to these two.
    """
    outline_model:    WritingModel = WritingModel.GEMINI_FLASH
    section_model:    WritingModel = WritingModel.GEMINI_FLASH
    refine_model:     WritingModel = WritingModel.CLAUDE_SONNET
    qa_model:         WritingModel = WritingModel.CLAUDE_SONNET


# Approved model set — UI selectboxes use this list only.
APPROVED_MODELS: list["WritingModel"] = [
    WritingModel.GEMINI_FLASH,
    WritingModel.CLAUDE_SONNET,
]


class ScoringTarget(BaseModel):
    """
    NeuronWriter-style targets. Engine will refine until thresholds are met
    OR max_refine_passes is reached.
    """
    min_content_score:     int   = Field(default=70, ge=0, le=100)
    min_term_coverage:     float = Field(default=0.75, ge=0, le=1)
    min_entity_coverage:   float = Field(default=0.60, ge=0, le=1)
    target_word_count:     int   = Field(default=2000, ge=100)
    word_count_tolerance:  float = Field(default=0.20, ge=0, le=0.5)  # ±20%
    max_refine_passes:     int   = Field(default=2, ge=0, le=5)


class GenerationConfig(BaseModel):
    """All article-level configuration the user can adjust before generation."""
    content_format:           ContentFormat = ContentFormat.GUIDE
    tone:                     WritingTone = WritingTone.PROFESSIONAL
    pov:                      POV = POV.SECOND_PERSON
    reading_level:            ReadingLevel = ReadingLevel.INTERMEDIATE
    model_strategy:           ModelStrategy = Field(default_factory=ModelStrategy)
    scoring_target:           ScoringTarget = Field(default_factory=ScoringTarget)
    include_intro:            bool = True
    include_faq:              bool = True
    include_conclusion:       bool = True
    include_cta:              bool = True
    enable_internal_linking:  bool = True
    enable_humanization:      bool = True     # default ON — humanization pass after section writing
    use_serp_enrichment:      bool = True     # pull live SERP for fresh terms
    enforce_ymyl:             bool = True     # auto-detect YMYL niches and tighten E-E-A-T
    custom_instructions:      Optional[str] = None


# ════════════════════════════════════════════════════════════════════
# OUTLINE — built before any prose generation
# ════════════════════════════════════════════════════════════════════

class OutlineHeading(BaseModel):
    """One heading node in the article outline."""
    level: str = Field(..., description="H1, H2, H3, H4")
    text: str
    semantic_purpose:     str = Field(default="", description="What this section should accomplish")
    target_word_count:    int = 0
    target_entities:      list[str] = Field(default_factory=list)
    target_queries:       list[str] = Field(default_factory=list)
    parent_heading_id:    Optional[str] = None

    @field_validator("level", mode="before")
    @classmethod
    def normalize_level(cls, v: Any) -> str:
        """Accepts 'h2', 'H2', '2' → normalizes to 'H2'."""
        if isinstance(v, int):
            return f"H{v}"
        if isinstance(v, str):
            v = v.upper().strip()
            if not v.startswith("H"):
                v = "H" + v
        return v


class ArticleOutline(BaseModel):
    """The skeleton — generated by outline_model before section-by-section writing."""
    title:                  str
    meta_description:       str = ""
    slug:                   Optional[str] = None
    headings:               list[OutlineHeading]
    estimated_word_count:   int = 0
    primary_keyword:        str = ""


# ════════════════════════════════════════════════════════════════════
# SECTIONS & ARTICLE — generation output
# ════════════════════════════════════════════════════════════════════

class SectionDraft(BaseModel):
    """
    One generated chunk — typically an H2 plus its body (incl. nested H3s).

    `cache_key` allows the engine to skip regeneration if the same
    (prompt + model + config) hash has been seen before.
    """
    section_id:      str = Field(..., description="Stable ID, e.g. 's_001'")
    section_type:    SectionType
    heading:         OutlineHeading
    content_md:      str = ""
    word_count:      int = 0
    used_entities:   list[str] = Field(default_factory=list)
    matched_terms:   list[str] = Field(default_factory=list)
    model_used:      Optional[str] = None
    cache_key:       Optional[str] = None
    cache_hit:       bool = False
    refined:         bool = False
    refine_count:    int = 0


class TermCoverageReport(BaseModel):
    """How well does the article cover the brief's NLP terms?"""
    must_include_total:      int = 0
    must_include_matched:    int = 0
    should_include_total:    int = 0
    should_include_matched:  int = 0
    missing_must:            list[str] = Field(default_factory=list)
    missing_should:          list[str] = Field(default_factory=list)
    coverage_score:          float = Field(default=0.0, ge=0, le=1)


class QualityReport(BaseModel):
    """Article-level quality assessment — drives refinement loop."""
    overall_score:         int = Field(default=0, ge=0, le=100)
    term_coverage:         TermCoverageReport = Field(default_factory=TermCoverageReport)
    entity_coverage:       float = Field(default=0.0, ge=0, le=1)
    word_count:            int = 0
    word_count_target:     int = 0
    word_count_in_range:   bool = False
    readability_score:     Optional[float] = None
    readability_grade:     Optional[str] = None
    issues:                list[str] = Field(default_factory=list)
    suggestions:           list[str] = Field(default_factory=list)
    passed_target:         bool = False


class GeneratedArticle(BaseModel):
    """The final assembled article + all metadata."""
    article_id:        str
    page_id:           str = Field(..., description="From the source ContentBrief")
    title:             str
    meta_description:  str = ""
    outline:           ArticleOutline
    sections:          list[SectionDraft]
    final_md:          str = ""
    final_html:        str = ""
    status:            ArticleStatus = ArticleStatus.DRAFT
    quality:           QualityReport = Field(default_factory=QualityReport)
    config_used:       GenerationConfig
    business_context:  BusinessContext
    generated_at:      datetime = Field(default_factory=datetime.utcnow)
    completed_at:      Optional[datetime] = None
    cost_usd:          float = 0.0
    total_tokens:      int = 0
    refine_passes:     int = 0


# ════════════════════════════════════════════════════════════════════
# CACHE & SESSION — persistence
# ════════════════════════════════════════════════════════════════════

class CacheType(str, Enum):
    SERP        = "serp"          # Serper.dev responses
    LLM         = "llm"           # LLM completion responses
    EMBEDDING   = "embedding"     # sentence embeddings
    TERM_INDEX  = "term_index"    # extracted term sets per URL


class CacheEntry(BaseModel):
    """One row in the cache store (SQLite local OR Turso cloud)."""
    cache_key:    str             # SHA-256 hash of canonical input
    cache_type:   CacheType
    payload:      dict            # serialized response (JSON-safe)
    created_at:   datetime
    expires_at:   Optional[datetime] = None
    ttl_days:     int = 30
    hits:         int = 0
    bytes_size:   int = 0


class SessionMeta(BaseModel):
    """Persisted session record — powers sidebar history + analytics."""
    session_id:        str
    article_id:        str
    business_niche:    str
    page_title:        str
    target_keyword:    Optional[str] = None
    status:            ArticleStatus
    created_at:        datetime
    updated_at:        datetime
    cost_usd:          float = 0.0
    quality_score:     int = 0
    word_count:        int = 0


# ════════════════════════════════════════════════════════════════════
# COST TRACKING
# ════════════════════════════════════════════════════════════════════

class APICallRecord(BaseModel):
    """One API call entry — feeds cost_tracker."""
    timestamp:     datetime = Field(default_factory=datetime.utcnow)
    stage:         str                       # "outline" | "section" | "qa" | "serp" | "embedding"
    provider:      str                       # "anthropic" | "google" | "serper"
    model:         str
    input_tokens:  int = 0
    output_tokens: int = 0
    cost_usd:      float = 0.0
    cache_hit:     bool = False
    section_id:    Optional[str] = None


# ════════════════════════════════════════════════════════════════════
# EXPORT
# ════════════════════════════════════════════════════════════════════

class ExportBundle(BaseModel):
    """What gets packaged for download."""
    article_id:             str
    formats:                list[ExportFormat]
    include_metadata:       bool = False
    include_outline:        bool = False
    include_quality_report: bool = False
    include_brief:          bool = False
