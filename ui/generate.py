"""Generate page — configure + run the pipeline."""

import threading
import time

import streamlit as st

from content_models import (
    APPROVED_MODELS,
    ContentEngineInput,
    ContentFormat,
    GenerationConfig,
    POV,
    ReadingLevel,
    ScoringTarget,
    WritingModel,
    WritingTone,
)
from pipeline import run_pipeline
from ui.session_manager import save_session


def render_generate() -> None:
    st.header("Generate Article")

    raw_input = st.session_state.get("content_input")
    if not raw_input:
        st.warning("No brief loaded. Go to Upload first.")
        return

    ci = ContentEngineInput.model_validate(raw_input)
    st.caption(f"Loaded: **{ci.brief_payload.get('page_title')}** ({ci.brief_payload.get('page_id')})")

    with st.expander("Content config", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            content_format = st.selectbox("Format", list(ContentFormat),
                                          format_func=lambda x: x.value, index=2)
            tone = st.selectbox("Tone", list(WritingTone),
                                format_func=lambda x: x.value, index=0)
            pov = st.selectbox("POV", list(POV),
                               format_func=lambda x: x.value, index=2)
        with col2:
            reading = st.selectbox("Reading level", list(ReadingLevel),
                                   format_func=lambda x: x.value, index=1)
            include_faq = st.checkbox("Include FAQ", True)
            include_cta = st.checkbox("Include CTA", True)

    with st.expander("Model strategy"):
        st.caption("Approved models: gemini-2.0-flash (bulk) + claude-sonnet-4-6 (quality)")
        col1, col2 = st.columns(2)
        with col1:
            outline_m = st.selectbox("Outline model", APPROVED_MODELS,
                                     format_func=lambda x: x.value, index=0)
            section_m = st.selectbox("Section model", APPROVED_MODELS,
                                     format_func=lambda x: x.value, index=0)
        with col2:
            refine_m  = st.selectbox("Refine model", APPROVED_MODELS,
                                     format_func=lambda x: x.value, index=1)
            qa_m      = st.selectbox("QA model", APPROVED_MODELS,
                                     format_func=lambda x: x.value, index=1)

    with st.expander("Scoring target"):
        col1, col2 = st.columns(2)
        with col1:
            min_score = st.slider("Min content score", 0, 100, 70)
            min_terms = st.slider("Min term coverage", 0.0, 1.0, 0.75, 0.05)
        with col2:
            target_wc = st.number_input("Target word count", 500, 8000, 2000, 100)
            max_passes = st.slider("Max refine passes", 0, 5, 2)

    config = GenerationConfig(
        content_format=content_format,
        tone=tone, pov=pov, reading_level=reading,
        include_faq=include_faq, include_cta=include_cta,
        model_strategy={
            "outline_model": outline_m,
            "section_model": section_m,
            "refine_model":  refine_m,
            "qa_model":      qa_m,
        },
        scoring_target=ScoringTarget(
            min_content_score=min_score,
            min_term_coverage=min_terms,
            target_word_count=target_wc,
            max_refine_passes=max_passes,
        ),
    )

    st.markdown("---")
    dry_run = st.checkbox(
        "Dry run (skip LLM calls, use placeholders)",
        value=False,
        help="Fast end-to-end test without spending API credits.",
    )
    if st.button("Generate article", type="primary", use_container_width=True):
        _run_with_progress(ci, config, dry_run=dry_run)


def _run_with_progress(ci: ContentEngineInput, config: GenerationConfig, dry_run: bool = False) -> None:
    progress = st.progress(0.0)
    status = st.empty()
    state = {"pct": 0.0, "stage": "", "done": False, "article": None, "error": None}

    def cb(stage: str, pct: float) -> None:
        state["stage"] = stage
        state["pct"] = pct

    def worker() -> None:
        try:
            article = run_pipeline(ci, config, output_dir=None, progress_cb=cb, dry_run=dry_run)
            save_session(article)
            state["article"] = article
        except Exception as e:
            state["error"] = str(e)
        finally:
            state["done"] = True

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    while not state["done"]:
        progress.progress(min(state["pct"], 1.0))
        status.text(state["stage"])
        time.sleep(0.4)

    progress.progress(1.0)
    if state["error"]:
        st.error(state["error"])
        return
    article = state["article"]
    st.session_state.last_article = article.model_dump(mode="json")
    st.success(f"Done. Score {article.quality.overall_score}/100 — {article.quality.word_count} words.")
    if st.button("Open preview"):
        st.session_state.page = "preview"
        st.rerun()
