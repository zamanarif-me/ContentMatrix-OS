"""Upload page — bring in a brief from various sources."""

import json
from pathlib import Path

import streamlit as st

from content_models import (
    BriefSource,
    BusinessCategory,
    BusinessContext,
    ContentEngineInput,
)
from stages import input_loader


def render_upload() -> None:
    st.header("Upload Input")
    st.caption("Choose how to load the Content Brief.")

    tab_engine, tab_json, tab_form = st.tabs([
        "From topical-map-engine session",
        "Upload JSON",
        "Manual form",
    ])

    with tab_engine:
        _render_engine_source()
    with tab_json:
        _render_json_upload()
    with tab_form:
        _render_manual_form()


# ── Tab 1: existing engine session ────────────────────────────────────────────

def _render_engine_source() -> None:
    st.markdown("Point to a `topical-map-engine-pro` session folder.")
    default = "../topical-map-engine-pro/sessions"
    session_root = st.text_input("Sessions root", value=default)

    sessions_dir = Path(session_root)
    if not sessions_dir.exists():
        st.warning(f"Folder not found: {sessions_dir.resolve()}")
        return

    folders = sorted([p.name for p in sessions_dir.iterdir() if p.is_dir()], reverse=True)
    if not folders:
        st.info("No session folders found.")
        return

    chosen = st.selectbox("Session", folders)
    pages = input_loader.list_pages_in_session(sessions_dir / chosen)
    if not pages:
        st.warning("No briefs found in this session (need briefs/all_briefs.json).")
        return

    labels = [f"{p['page_id']}  •  {p['page_title']}" for p in pages]
    pick = st.selectbox("Page", labels)
    page_id = pages[labels.index(pick)]["page_id"]

    st.markdown("**Business context**")
    business = _business_form()

    if st.button("Load brief"):
        try:
            ci = input_loader.load_from_engine_session(sessions_dir / chosen, page_id, business)
            st.session_state.content_input = ci.model_dump(mode="json")
            st.success(f"Loaded `{page_id}`. Go to Generate.")
        except Exception as e:
            st.error(f"Load failed: {e}")


# ── Tab 2: JSON upload ────────────────────────────────────────────────────────

def _render_json_upload() -> None:
    st.markdown("Upload a complete `ContentEngineInput` JSON (see `example_input.json`).")
    f = st.file_uploader("JSON file", type=["json"])
    if not f:
        return
    try:
        data = json.loads(f.read())
        ci = ContentEngineInput.model_validate(data)
        st.session_state.content_input = ci.model_dump(mode="json")
        st.success("Loaded. Go to Generate.")
    except Exception as e:
        st.error(f"Invalid JSON or schema: {e}")


# ── Tab 3: Manual form ────────────────────────────────────────────────────────

def _render_manual_form() -> None:
    st.info("Manual form: fills BusinessContext + a minimal ContentBrief. Full form coming in Phase 2.")
    business = _business_form()
    page_title = st.text_input("Page title", "")
    target_keyword = st.text_input("Target keyword", "")
    word_count = st.number_input("Target word count", 500, 8000, 2000)

    if st.button("Use this minimal brief"):
        minimal_brief = {
            "page_id": "manual_001",
            "page_title": page_title or "Untitled",
            "queries": {"primary_query": target_keyword, "secondary_queries": [], "question_queries": []},
            "headings": [
                {"level": "H1", "text": page_title or "Untitled"},
                {"level": "H2", "text": "Overview"},
                {"level": "H2", "text": "Key considerations"},
                {"level": "H2", "text": "Conclusion"},
            ],
            "nlp_terms": {"must_include": [], "should_include": [], "semantic_variants": []},
            "content_specs": {"recommended_word_count": word_count, "content_format": "guide",
                              "reading_level": "intermediate", "pov": "second_person", "e_e_a_t_signals": []},
        }
        ci = ContentEngineInput(
            business=business,
            brief_source=BriefSource.MANUAL_FORM,
            brief_payload=minimal_brief,
            target_keyword=target_keyword or None,
        )
        st.session_state.content_input = ci.model_dump(mode="json")
        st.success("Minimal brief loaded.")


# ── Shared business form ──────────────────────────────────────────────────────

def _business_form() -> BusinessContext:
    cat = st.selectbox(
        "Business category",
        list(BusinessCategory),
        format_func=lambda c: c.value.replace("_", " ").title(),
        key="biz_cat",
    )
    niche = st.text_input("Niche (specific)", "WordPress security and malware removal", key="biz_niche")
    audience = st.text_input("Target audience (comma-separated)", "WordPress site owners, agencies", key="biz_aud")
    brand = st.text_input("Brand name (optional)", "", key="biz_brand")
    voice = st.text_area("Brand voice notes (optional)", "", key="biz_voice")
    return BusinessContext(
        category=cat,
        niche=niche,
        audience=[a.strip() for a in audience.split(",") if a.strip()],
        brand_name=brand or None,
        brand_voice_notes=voice or None,
    )
