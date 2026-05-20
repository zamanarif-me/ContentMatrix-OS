"""Preview page — show the generated article + quality report."""

import streamlit as st

from content_models import GeneratedArticle
from ui.session_manager import load_session


def render_preview() -> None:
    st.header("Preview")

    article = _resolve_article()
    if not article:
        st.info("No article available. Generate one first.")
        return

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Score",      f"{article.quality.overall_score}/100")
    col2.metric("Words",      article.quality.word_count)
    col3.metric("Sections",   len(article.sections))
    col4.metric("Cost (USD)", f"${article.cost_usd:.3f}")

    if article.quality.issues:
        with st.expander("Issues", expanded=True):
            for i in article.quality.issues:
                st.warning(i)

    st.markdown("---")
    st.markdown(article.final_md or "_no body_")


def _resolve_article() -> GeneratedArticle | None:
    # Priority 1: just-generated article in session
    raw = st.session_state.get("last_article")
    if raw:
        return GeneratedArticle.model_validate(raw)

    # Priority 2: sidebar-selected session
    sid = st.session_state.get("selected_session")
    if sid:
        return load_session(sid)

    return None
