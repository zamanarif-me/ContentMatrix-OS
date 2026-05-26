"""Home page — landing + quick-start + global tone trainer."""

import streamlit as st

from stages.tone_loader import extract_text_from_upload


def render_home() -> None:
    st.markdown("<h1 class='hero-title'>ContentMatrix OS</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p class='hero-subtitle'>"
        "Turn a Topical Map and Content Brief into a publication-ready, "
        "SEO-optimized article — chunk by chunk, cached, score-gated."
        Created By "Zaman Arif"
        "</p>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    # ── Section 1: Train Tone (NEW) ──────────────────────────────────────────
    _render_train_tone()

    st.markdown("---")

    # ── Sections 2-4: Existing workflow shortcuts ────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown("**2. Sessions**")
        st.caption("Bulk-friendly. Load a topical-map and generate all pages.")
        if st.button("Go to Sessions", use_container_width=True, key="home_sessions"):
            st.session_state.page = "sessions"
            st.rerun()
    with col2:
        st.markdown("**3. Upload**")
        st.caption("Single-brief mode. Upload a ContentEngineInput JSON.")
        if st.button("Go to Upload", use_container_width=True, key="home_upload"):
            st.session_state.page = "upload"
            st.rerun()
    with col3:
        st.markdown("**4. Generate**")
        st.caption("Tune the model strategy and scoring target.")
        if st.button("Go to Generate", use_container_width=True, key="home_generate"):
            st.session_state.page = "generate"
            st.rerun()
    with col4:
        st.markdown("**5. Export**")
        st.caption("Preview, download as Markdown / DOCX / HTML / JSON.")
        if st.button("Go to Export", use_container_width=True, key="home_export"):
            st.session_state.page = "export"
            st.rerun()

    st.markdown("---")
    st.markdown("### How it works")
    st.markdown(
        "- **Cached**: same brief = no re-billing. Cache stored in `cache/engine_cache.db`.\n"
        "- **Hybrid models**: Gemini Flash for bulk drafting + Claude Sonnet for refinement.\n"
        "- **Scored**: NeuronWriter-style content score gating before export.\n"
        "- **Compatible**: consumes `topical-map-engine-pro` session output directly."
    )


# ── Section 1: Global Tone Trainer ────────────────────────────────────────────

def _render_train_tone() -> None:
    """
    Upload sample writing (md / docx / zip) to set a GLOBAL brand voice.
    Persists in st.session_state.global_tone_text and is used for every
    session UNLESS the Sessions page overrides it with its own tone file.
    """
    st.markdown("### 1. Train Tone <span style='color:#6b6b8a; font-size:0.85rem'>(optional — global voice training)</span>", unsafe_allow_html=True)
    st.caption(
        "Upload 1-3 sample articles in your brand's voice (markdown, docx, or zip). "
        "Every article generated afterward will mimic this tone. "
        "Session-level tone (set on Sessions page) will override this."
    )

    # Counter key so we can reset the uploader
    if "tone_ver" not in st.session_state:
        st.session_state.tone_ver = 0
    if "global_tone_text" not in st.session_state:
        st.session_state.global_tone_text = ""
    if "global_tone_filename" not in st.session_state:
        st.session_state.global_tone_filename = ""

    col_upload, col_status = st.columns([2, 1])

    with col_upload:
        tone_key = f"home_tone_upload_{st.session_state.tone_ver}"
        uploaded = st.file_uploader(
            "Voice sample (md / docx / zip)",
            type=["md", "markdown", "txt", "docx", "zip"],
            key=tone_key,
            help="Upload a representative article. The engine extracts the text and uses it as voice reference.",
        )

        if uploaded is not None:
            try:
                text = extract_text_from_upload(uploaded, filename=uploaded.name)
                if not text.strip():
                    st.warning(f"⚠ No readable text found in {uploaded.name}")
                else:
                    st.session_state.global_tone_text = text
                    st.session_state.global_tone_filename = uploaded.name
                    st.success(f"✓ Loaded: **{uploaded.name}** ({len(text):,} chars)")
            except Exception as e:
                st.error(f"Failed to read file: {e}")

    with col_status:
        st.markdown("see tone status")
        if st.session_state.global_tone_text:
            st.metric(
                "Tone active",
                f"{len(st.session_state.global_tone_text):,} chars",
                delta=st.session_state.global_tone_filename[:18],
            )
            if st.button("✕ Clear tone", use_container_width=True, key="home_clear_tone"):
                st.session_state.global_tone_text = ""
                st.session_state.global_tone_filename = ""
                st.session_state.tone_ver += 1
                st.rerun()
        else:
            st.info("No global tone set")

    # Preview accordion
    if st.session_state.global_tone_text:
        with st.expander("📖 Preview loaded tone sample"):
            st.markdown(st.session_state.global_tone_text[:3000])
            if len(st.session_state.global_tone_text) > 3000:
                st.caption(f"... and {len(st.session_state.global_tone_text) - 3000:,} more characters")
