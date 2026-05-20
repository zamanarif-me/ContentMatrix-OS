"""
ContentMatrix OS — Streamlit entry point.

Run:
    streamlit run app.py

Same dark theme as topical-map-engine-pro for visual continuity.
"""

import streamlit as st

st.set_page_config(
    page_title="ContentMatrix OS",
    page_icon="✍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Theme (matches topical-map-engine-pro) ────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500;600&display=swap');

:root {
    --bg:       #0a0a0f;
    --surface:  #13131a;
    --border:   #1e1e2e;
    --accent:   #6c63ff;
    --accent2:  #ff6b6b;
    --accent3:  #43e97b;
    --text:     #e8e8f0;
    --muted:    #6b6b8a;
    --card:     #16161f;
}

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
    background: var(--bg);
    color: var(--text);
}

.stApp { background: var(--bg); }

h1, h2, h3 {
    font-family: 'DM Serif Display', serif;
    color: var(--text);
}

.stButton > button {
    background: var(--accent);
    color: white;
    border: none;
    border-radius: 8px;
    font-family: 'DM Sans', sans-serif;
    font-weight: 500;
    padding: 0.6rem 1.4rem;
    transition: all 0.2s;
}

.stButton > button:hover {
    background: #7c74ff;
    transform: translateY(-1px);
    box-shadow: 0 4px 20px rgba(108, 99, 255, 0.4);
}

.stTextInput > div > div > input,
.stTextArea > div > div > textarea,
.stSelectbox > div > div,
.stNumberInput > div > div > input {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    font-family: 'DM Sans', sans-serif;
}

.stProgress > div > div { background: var(--accent); }

.hero-title {
    font-family: 'DM Serif Display', serif;
    font-size: 3.5rem;
    line-height: 1.1;
    margin-bottom: 1rem;
}

.hero-subtitle {
    font-size: 1.15rem;
    color: var(--muted);
    max-width: 700px;
    line-height: 1.6;
}

[data-testid="stMetricValue"] {
    font-family: 'DM Mono', monospace;
    color: var(--accent);
}

[data-testid="stMetricLabel"] {
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-size: 0.75rem;
}
</style>
""", unsafe_allow_html=True)

# ── Router ────────────────────────────────────────────────────────────────────
from ui.home     import render_home
from ui.sessions import render_sessions
from ui.upload   import render_upload
from ui.generate import render_generate
from ui.preview  import render_preview
from ui.export   import render_export
from ui.sidebar  import render_sidebar

if "page" not in st.session_state:
    st.session_state.page = "home"

render_sidebar()

page = st.session_state.page
if   page == "home":     render_home()
elif page == "sessions": render_sessions()
elif page == "upload":   render_upload()
elif page == "generate": render_generate()
elif page == "preview":  render_preview()
elif page == "export":   render_export()
else:                    render_home()
