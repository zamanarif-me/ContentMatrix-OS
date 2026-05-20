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

    # Recommended workflow (chain)
    st.markdown("### Recommended workflow")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown("**1. Sessions**")
        st.caption("Load a topical-map-engine session (folder / ZIP / files).")
        if st.button("Open Sessions", use_container_width=True, key="home_sessions"):
            st.session_state.page = "sessions"
            st.rerun()
    with col2:
        st.markdown("**2. Generate**")
        st.caption("Pick one page or bulk-generate all pending articles.")
        if st.button("Open Generate", use_container_width=True, key="home_generate"):
            st.session_state.page = "generate"
            st.rerun()
    with col3:
        st.markdown("**3. Preview**")
        st.caption("Inspect the article + quality report.")
        if st.button("Open Preview", use_container_width=True, key="home_preview"):
            st.session_state.page = "preview"
            st.rerun()
    with col4:
        st.markdown("**4. Export**")
        st.caption("Download as Markdown / DOCX / HTML / JSON.")
        if st.button("Open Export", use_container_width=True, key="home_export"):
            st.session_state.page = "export"
            st.rerun()

    st.markdown("---")
    st.markdown("### Alternative input paths")
    st.markdown(
        "- **Sessions** (recommended): bulk-friendly, status tracking, one click per brief\n"
        "- **Upload**: single-brief upload via JSON or manual form (no topical map context)\n"
    )

    st.markdown("---")
    st.markdown("### How it works")
    st.markdown(
        "- **Chained**: consumes `topical-map-engine-pro` session output directly\n"
        "- **Cached**: same brief = no re-billing. SQLite at `cache/engine_cache.db`\n"
        "- **Hybrid models**: Gemini Flash drafts + Claude Sonnet refinement\n"
        "- **Compliant**: house rules enforce US English, no emoji, no AI jargon, "
        "  8-12 grade level, E-E-A-T, YMYL detection, internal linking injection"
    )
