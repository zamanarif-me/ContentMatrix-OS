"""
Sessions Browser — the chain-integration command center.

Lets the user:
  1. Load a topical-map session from local folder / ZIP / individual files
  2. Browse all pages (Pillars / Clusters / Supplementary) in that session
  3. See per-page status: pending / done / multiple drafts
  4. Generate one article OR bulk-generate all pending
  5. Jump to any generated article for preview/export
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import streamlit as st

from content_models import (
    BusinessCategory,
    BusinessContext,
    ContentFormat,
    GenerationConfig,
)
from pipeline import run_pipeline
from stages import bridge
from ui.session_manager import find_status_map, save_session


# ── Session-state helpers ─────────────────────────────────────────────────────

def _loaded_sessions() -> dict[str, bridge.MapSession]:
    if "map_sessions" not in st.session_state:
        st.session_state.map_sessions = {}
    return st.session_state.map_sessions


def _register_session(sess: bridge.MapSession) -> None:
    sessions = _loaded_sessions()
    sessions[sess.session_id] = sess
    st.session_state.map_sessions = sessions
    st.session_state.active_session_id = sess.session_id


# ── Top-level render ──────────────────────────────────────────────────────────

def render_sessions() -> None:
    st.header("Sessions Browser")
    st.caption("Bridge: topical-map-engine sessions -> ContentMatrix OS articles")

    with st.expander("Load a new session", expanded=not _loaded_sessions()):
        _render_loader()

    sessions = _loaded_sessions()
    if not sessions:
        st.info("No sessions loaded yet. Use the loader above.")
        return

    sid_options = list(sessions.keys())
    active_sid = st.session_state.get("active_session_id", sid_options[0])
    if active_sid not in sid_options:
        active_sid = sid_options[0]
    picked = st.selectbox(
        "Active session",
        sid_options,
        index=sid_options.index(active_sid),
        format_func=lambda s: f"{s}  ({sessions[s].source_label})",
    )
    st.session_state.active_session_id = picked
    active = sessions[picked]

    _render_session_summary(active)
    st.markdown("---")
    _render_business_block()
    st.markdown("---")
    _render_url_map(active)
    st.markdown("---")
    _render_page_table(active)


# ── URL Map editor ────────────────────────────────────────────────────────────

def _render_url_map(sess: bridge.MapSession) -> None:
    with st.expander("URL Map (internal-link destinations)", expanded=False):
        if sess.url_map is None:
            st.info("No URL map loaded.")
            return

        st.caption(
            "Configure how page_ids resolve to URLs in injected internal links. "
            "Auto-generated slugs are used unless you set an explicit override."
        )

        col1, col2 = st.columns([3, 1])
        sess.url_map.base_url = col1.text_input(
            "Base URL (origin + optional path prefix)",
            value=sess.url_map.base_url,
            placeholder="https://example.com",
            key=f"url_base_{sess.session_id}",
        )
        sess.url_map.append_slash = col2.checkbox(
            "Append /", value=sess.url_map.append_slash,
            key=f"url_slash_{sess.session_id}",
        )

        cov = sess.url_map.coverage([p.page_id for p in sess.pages])
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total",    cov["total"])
        c2.metric("Explicit", cov["explicit"])
        c3.metric("Slugged",  cov["slugged"])
        c4.metric("Fallback", cov["fallback"])

        st.markdown("**Override URLs** (leave blank to use slug)")
        for p in sess.pages[:25]:
            current = sess.url_map.explicit.get(p.page_id, "")
            resolved = sess.url_map.resolve(p.page_id, fallback_title=p.page_title)
            new_val = st.text_input(
                f"{p.page_id}  •  {p.page_title[:40]}",
                value=current,
                placeholder=resolved,
                key=f"url_ovr_{sess.session_id}_{p.page_id}",
            )
            if new_val and new_val != current:
                sess.url_map.set_url(p.page_id, new_val)
            elif not new_val and current:
                sess.url_map.explicit.pop(p.page_id, None)

        if len(sess.pages) > 25:
            st.caption(f"Showing first 25 of {len(sess.pages)} pages. Edit url_map.json directly for bulk changes.")


# ── Loader (3 sources) ────────────────────────────────────────────────────────

def _render_loader() -> None:
    tab_local, tab_zip, tab_files = st.tabs([
        "Local folder",
        "Upload ZIP",
        "Upload files",
    ])

    with tab_local:
        st.caption("Point to a topical-map-engine-pro/sessions/<id> folder.")
        path = st.text_input(
            "Session folder",
            value=st.session_state.get("last_local_path", "../topical-map-engine-pro/sessions"),
            key="local_session_input",
        )
        if st.button("Load from folder", key="btn_load_local"):
            try:
                p = Path(path)
                if p.is_dir() and (p / "topical_map.json").exists():
                    sess = bridge.load_from_local_folder(p)
                    _register_session(sess)
                    st.session_state.last_local_path = str(p.parent)
                    st.success(f"Loaded: {sess.session_id} ({len(sess.pages)} pages)")
                    st.rerun()
                else:
                    subs = sorted([x for x in p.iterdir() if x.is_dir()], reverse=True)
                    if not subs:
                        st.warning("No session folders found.")
                    else:
                        picked = st.selectbox("Pick a session folder", [x.name for x in subs])
                        if st.button("Confirm", key="btn_confirm_local"):
                            sess = bridge.load_from_local_folder(p / picked)
                            _register_session(sess)
                            st.success(f"Loaded: {sess.session_id}")
                            st.rerun()
            except Exception as e:
                st.error(f"Load failed: {e}")

    with tab_zip:
        st.caption("Upload a zipped session folder from topical-map-engine.")
        f = st.file_uploader("ZIP file", type=["zip"], key="upload_zip")
        if f and st.button("Load ZIP", key="btn_load_zip"):
            try:
                sess = bridge.load_from_zip(f, original_name=f.name)
                _register_session(sess)
                st.success(f"Loaded: {sess.session_id} ({len(sess.pages)} pages)")
                st.rerun()
            except Exception as e:
                st.error(f"Load failed: {e}")

    with tab_files:
        st.caption("Upload topical_map.json + all_briefs.json separately.")
        col1, col2 = st.columns(2)
        with col1:
            tm = st.file_uploader("topical_map.json", type=["json"], key="up_tm")
        with col2:
            br = st.file_uploader("all_briefs.json", type=["json"], key="up_br")
        label = st.text_input("Label (used for session id)", value="manual", key="up_label")
        if tm and br and st.button("Load files", key="btn_load_files"):
            try:
                sess = bridge.load_from_files(tm, br, session_label=label)
                _register_session(sess)
                st.success(f"Loaded: {sess.session_id} ({len(sess.pages)} pages)")
                st.rerun()
            except Exception as e:
                st.error(f"Load failed: {e}")


# ── Session summary ──────────────────────────────────────────────────────────

def _render_session_summary(sess: bridge.MapSession) -> None:
    status = find_status_map([p.page_id for p in sess.pages])
    total = len(sess.pages)
    done = sum(1 for p in sess.pages if status.get(p.page_id))
    pending = total - done

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Central entity",     (sess.central_entity or "—")[:25])
    col2.metric("Total pages",        total)
    col3.metric("Articles done",      done)
    col4.metric("Pending",            pending)


# ── Business context block ────────────────────────────────────────────────────

def _render_business_block() -> None:
    st.markdown("**Business context** (applied to every article in this session)")
    if "session_business" not in st.session_state:
        st.session_state.session_business = {
            "category": BusinessCategory.SERVICE_BUSINESS.value,
            "niche":    "",
            "audience": "",
            "brand_name": "",
            "brand_voice_notes": "",
        }
    b = st.session_state.session_business

    col1, col2 = st.columns(2)
    with col1:
        b["category"] = st.selectbox(
            "Category",
            [c.value for c in BusinessCategory],
            index=[c.value for c in BusinessCategory].index(b["category"]),
            key="sb_cat",
        )
        b["niche"] = st.text_input("Niche", value=b["niche"], key="sb_niche")
        b["audience"] = st.text_input("Audience (comma-sep)", value=b["audience"], key="sb_aud")
    with col2:
        b["brand_name"] = st.text_input("Brand", value=b["brand_name"], key="sb_brand")
        b["brand_voice_notes"] = st.text_area(
            "Voice notes", value=b["brand_voice_notes"], height=100, key="sb_voice"
        )
    st.session_state.session_business = b


def _build_business() -> BusinessContext:
    b = st.session_state.get("session_business", {})
    return BusinessContext(
        category=BusinessCategory(b.get("category", "service_business")),
        niche=b.get("niche") or "general",
        audience=[a.strip() for a in (b.get("audience", "") or "").split(",") if a.strip()],
        brand_name=b.get("brand_name") or None,
        brand_voice_notes=b.get("brand_voice_notes") or None,
    )


# ── Page table ────────────────────────────────────────────────────────────────

def _render_page_table(sess: bridge.MapSession) -> None:
    st.subheader("Pages")

    type_filter = st.multiselect(
        "Filter by page type",
        options=sorted({p.page_type for p in sess.pages}),
        default=sorted({p.page_type for p in sess.pages}),
        key="page_type_filter",
    )

    status = find_status_map([p.page_id for p in sess.pages])
    pending_ids = [p.page_id for p in sess.pages
                   if p.page_type in type_filter and not status.get(p.page_id)]

    col_a, col_b = st.columns([3, 1])
    col_a.caption(f"{len(pending_ids)} pending in current filter")
    if col_b.button(f"Generate all pending ({len(pending_ids)})",
                    disabled=len(pending_ids) == 0):
        _run_batch(sess, pending_ids)

    for p in sess.pages:
        if p.page_type not in type_filter:
            continue
        articles = status.get(p.page_id, [])
        with st.container(border=True):
            cols = st.columns([4, 1, 1, 1])
            badge = "DONE" if articles else "pending"
            score = articles[0]["quality_score"] if articles else ""
            cols[0].markdown(
                f"**{p.page_title}**  \n"
                f"_{p.page_type}_  •  `{p.page_id}`  •  intent: {p.primary_query or 'n/a'}"
            )
            cols[1].markdown(f"`{badge}`")
            cols[2].markdown(f"score: **{score}**" if score else "—")
            if cols[3].button("Generate", key=f"gen_{p.page_id}"):
                _run_one(sess, p.page_id)


# ── Generation runners ────────────────────────────────────────────────────────

def _run_one(sess: bridge.MapSession, page_id: str) -> None:
    try:
        business = _build_business()
        ci = bridge.make_engine_input(sess, page_id, business)
        cfg = GenerationConfig()
    except Exception as e:
        st.error(f"Setup failed: {e}")
        return

    progress = st.progress(0.0)
    status_text = st.empty()
    state = {"pct": 0.0, "stage": "", "done": False, "article": None, "error": None}

    def cb(stage: str, pct: float) -> None:
        state["stage"] = stage
        state["pct"] = pct

    def worker() -> None:
        try:
            article = run_pipeline(ci, cfg, output_dir=None, progress_cb=cb)
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
        status_text.text(f"{page_id}: {state['stage']}")
        time.sleep(0.4)
    progress.progress(1.0)

    if state["error"]:
        st.error(f"Failed: {state['error']}")
    else:
        st.success(f"Done — score {state['article'].quality.overall_score}/100")
        st.rerun()


def _run_batch(sess: bridge.MapSession, page_ids: list[str]) -> None:
    st.warning(f"Bulk generating {len(page_ids)} articles. Do not close the page.")
    business = _build_business()
    cfg = GenerationConfig()
    overall = st.progress(0.0)
    log = st.empty()
    results = []

    for i, pid in enumerate(page_ids):
        log.text(f"[{i+1}/{len(page_ids)}] {pid}")
        try:
            ci = bridge.make_engine_input(sess, pid, business)
            article = run_pipeline(ci, cfg, output_dir=None, progress_cb=lambda *a: None)
            save_session(article)
            results.append((pid, "OK", article.quality.overall_score))
        except Exception as e:
            results.append((pid, "FAIL", str(e)[:80]))
        overall.progress((i + 1) / len(page_ids))

    log.empty()
    overall.progress(1.0)
    st.success(f"Batch done. {sum(1 for r in results if r[1]=='OK')} ok, "
               f"{sum(1 for r in results if r[1]=='FAIL')} failed.")
    with st.expander("Batch results", expanded=True):
        for pid, status_, info in results:
            st.write(f"- `{pid}` — **{status_}** — {info}")
    st.rerun()
