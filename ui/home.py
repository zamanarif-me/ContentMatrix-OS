"""Home page — landing + quick-start."""

import streamlit as st


def render_home() -> None:
    st.markdown("<h1 class='hero-title'>ContentMatrix OS</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p class='hero-subtitle'>"
        "Turn a Topical Map and Content Brief into a publication-ready, "
        "SEO-optimized article — chunk by chunk, cached, score-gated."
        "</p>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**1. Upload**")
        st.caption("Load a brief from a topical-map-engine session or upload your own JSON.")
        if st.button("Go to Upload", use_container_width=True, key="home_upload"):
            st.session_state.page = "upload"
            st.rerun()
    with col2:
        st.markdown("**2. Generate**")
        st.caption("Pick a model strategy, tune the scoring target, and generate the article.")
        if st.button("Go to Generate", use_container_width=True, key="home_generate"):
            st.session_state.page = "generate"
            st.rerun()
    with col3:
        st.markdown("**3. Export**")
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
