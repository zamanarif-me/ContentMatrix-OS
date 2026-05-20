"""Export page — download buttons for all formats."""

import streamlit as st

from content_models import ExportFormat, GeneratedArticle
from stages import exporter
from ui.session_manager import load_session


def render_export() -> None:
    st.header("Export")

    article = _resolve_article()
    if not article:
        st.info("No article available. Generate one first.")
        return

    st.caption(f"**{article.title}** — {article.quality.word_count} words")

    md_bytes   = exporter.to_markdown(article)
    html_bytes = exporter.to_html(article)
    json_bytes = exporter.to_json(article)

    col1, col2, col3, col4 = st.columns(4)
    col1.download_button("Markdown", md_bytes,   file_name=f"{article.outline.slug or 'article'}.md",   mime="text/markdown")
    col2.download_button("HTML",     html_bytes, file_name=f"{article.outline.slug or 'article'}.html", mime="text/html")
    col3.download_button("JSON",     json_bytes, file_name=f"{article.outline.slug or 'article'}.json", mime="application/json")
    try:
        docx_bytes = exporter.to_docx(article)
        col4.download_button("DOCX", docx_bytes,
                             file_name=f"{article.outline.slug or 'article'}.docx",
                             mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    except Exception as e:
        col4.caption(f"DOCX unavailable: {e}")


def _resolve_article() -> GeneratedArticle | None:
    raw = st.session_state.get("last_article")
    if raw:
        return GeneratedArticle.model_validate(raw)
    sid = st.session_state.get("selected_session")
    if sid:
        return load_session(sid)
    return None
