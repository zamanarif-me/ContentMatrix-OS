"""Sidebar — recent sessions + nav."""

import streamlit as st

from ui.session_manager import list_sessions


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### ContentMatrix OS")
        if st.button("Home",     use_container_width=True, key="nav_home"):
            st.session_state.page = "home"
            st.rerun()
        if st.button("Upload",   use_container_width=True, key="nav_upload"):
            st.session_state.page = "upload"
            st.rerun()
        if st.button("Generate", use_container_width=True, key="nav_generate"):
            st.session_state.page = "generate"
            st.rerun()
        if st.button("Preview",  use_container_width=True, key="nav_preview"):
            st.session_state.page = "preview"
            st.rerun()
        if st.button("Export",   use_container_width=True, key="nav_export"):
            st.session_state.page = "export"
            st.rerun()

        st.markdown("---")
        st.markdown("**Recent sessions**")
        sessions = list_sessions()
        if not sessions:
            st.caption("No sessions yet.")
            return
        for s in sessions[:10]:
            title = (s.get("page_title") or "Untitled")[:32]
            score = s.get("quality_score", 0)
            label = f"{title}  •  {score}"
            if st.button(label, key=f"sess_{s.get('session_id')}", use_container_width=True):
                st.session_state.selected_session = s.get("session_id")
                st.session_state.page = "preview"
                st.rerun()
