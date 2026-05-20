"""
YMYL (Your Money or Your Life) detection.

Google's quality guidelines apply a higher trust bar to topics that can
affect a person's health, financial stability, safety, or major life
decisions. ContentMatrix OS auto-detects YMYL niches and:
  - Injects a YMYL warning block into the LLM context
  - Surfaces a "YMYL: high trust required" badge in the UI
  - Lowers the refinement bar (more passes allowed for these articles)

Detection is keyword-based — fast, deterministic, no LLM call required.
"""

from __future__ import annotations

from content_models import BusinessCategory, BusinessContext


# ── Keyword sets ─────────────────────────────────────────────────────────────

_HEALTH_KW = {
    "health", "medical", "medicine", "doctor", "clinic", "hospital",
    "disease", "treatment", "diagnosis", "symptom", "drug", "medication",
    "pharmacy", "therapy", "mental health", "wellness", "nutrition", "diet",
    "supplement", "fitness", "pregnancy", "pediatric", "dental", "dentist",
    "cancer", "diabetes", "covid",
}

_FINANCE_KW = {
    "finance", "financial", "investment", "investing", "stock", "crypto",
    "cryptocurrency", "bitcoin", "loan", "mortgage", "insurance", "tax",
    "taxes", "retirement", "401k", "ira", "savings", "credit", "debit",
    "bank", "banking", "trading", "forex",
}

_LEGAL_KW = {
    "legal", "law", "lawyer", "attorney", "lawsuit", "contract", "patent",
    "trademark", "copyright", "litigation", "court", "settlement", "divorce",
    "custody", "immigration", "visa", "criminal", "felony",
}

_SAFETY_KW = {
    "safety", "emergency", "disaster", "hazard", "poison", "toxic",
    "first aid", "cpr", "fire safety", "child safety",
}

_LIFE_DECISION_KW = {
    "adoption", "fertility", "addiction", "rehab", "suicide", "abuse",
}


# ── Public API ────────────────────────────────────────────────────────────────

def detect_ymyl(business: BusinessContext, brief: dict) -> tuple[bool, list[str]]:
    """
    Returns (is_ymyl, matched_categories).

    Matches against the business niche, brief title, primary query,
    and central entity — i.e. anywhere the topic might surface.
    """
    haystacks = [
        business.niche or "",
        brief.get("page_title", ""),
        brief.get("central_entity", ""),
        (brief.get("queries") or {}).get("primary_query", ""),
    ]
    text = " ".join(haystacks).lower()

    matched: list[str] = []
    if business.category in (BusinessCategory.HEALTHCARE,):
        matched.append("health")
    if business.category in (BusinessCategory.FINANCE,):
        matched.append("finance")

    if any(k in text for k in _HEALTH_KW):       matched.append("health")
    if any(k in text for k in _FINANCE_KW):      matched.append("finance")
    if any(k in text for k in _LEGAL_KW):        matched.append("legal")
    if any(k in text for k in _SAFETY_KW):       matched.append("safety")
    if any(k in text for k in _LIFE_DECISION_KW): matched.append("life-decision")

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for c in matched:
        if c not in seen:
            seen.add(c)
            unique.append(c)

    return (len(unique) > 0, unique)


def ymyl_directive(categories: list[str]) -> str:
    """Build a YMYL directive block to inject into the LLM user message."""
    if not categories:
        return ""
    cats = ", ".join(categories)
    return (
        f"\n# YMYL NOTICE\n"
        f"This topic is classified as YMYL (Your Money or Your Life) — "
        f"categories: {cats}. Apply the highest trust standards:\n"
        f"- Recommend consulting a licensed {'/'.join(_advisor_for(categories))} for personal situations\n"
        f"- Cite primary sources for every factual claim\n"
        f"- Add disclaimers where appropriate (e.g. 'This is general "
        f"information, not personal advice')\n"
        f"- Avoid definitive predictions, prescriptions, or guarantees\n"
        f"- Note when something depends on jurisdiction, individual situation,\n"
        f"  or professional assessment\n"
    )


def _advisor_for(categories: list[str]) -> list[str]:
    mapping = {
        "health":         "doctor",
        "finance":        "financial advisor",
        "legal":          "attorney",
        "safety":         "qualified safety professional",
        "life-decision":  "qualified counselor",
    }
    return [mapping[c] for c in categories if c in mapping] or ["qualified professional"]
