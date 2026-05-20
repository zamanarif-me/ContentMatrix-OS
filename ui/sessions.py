"""
Sessions Browser — the chain-integration command center.

Workflow (visible in UI):
  Step 1: Load a session (topical_map.json + all_briefs.json)
  Step 2: Fill business context (niche, audience, brand)
  Step 3: Generate articles (one at a time OR bulk)
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


def _business_is_ready() -> bool:
    b = st.session_state.get("session_business", {})
    return bool(b.get("niche", "").strip()) and bool(b.get("audience", "").strip())


# ── Top-level render ──────────────────────────────────────────────────────────

def render_sessions() -> None:
    st.header("Sessions Browser")
    st.caption("Topical-map sessions → ContentMatrix OS articles")

    has_session = bool(_loaded_sessions())
    biz_ready = _business_is_ready()

    # ── Workflow progress strip ───────────────────────────────────────────────
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            f"### {'✅' if has_session else '①'} Load session"
            f"\n{'_session loaded_' if has_session else '_upload files below_'}"
        )
    with c2:
        st.markdown(
            f"### {'✅' if biz_ready else '②'} Business context"
            f"\n{'_niche + audience set_' if biz_ready else '_required before generate_'}"
        )
    with c3:
        ready = has_session and biz_ready
        st.markdown(
            f"### {'🚀' if ready else '③'} Generate"
            f"\n{'_pick a page below_' if ready else '_complete steps 1 & 2_'}"
        )

    st.markdown("---")

    # ── Step 1: Loader ────────────────────────────────────────────────────────
    with st.expander(
        "📁 Step 1 — Load a session",
        expanded=not has_session,
    ):
        _render_loader()

    if not has_session:
        st.info(
            "👆 **Start here:** Upload your topical_map.json + all_briefs.json above. "
            "Once loaded, Business Context and Pages will appear."
        )
        return

    # Session picker (if multiple loaded)
    sessions = _loaded_sessions()
    sid_options = list(sessions.keys())
    active_sid = st.session_state.get("active_session_id", sid_options[0])
    if active_sid not in sid_options:
        active_sid = sid_options[0]

    if len(sid_options) > 1:
        picked = st.selectbox(
            "Active session",
            sid_options,
            index=sid_options.index(active_sid),
            format_func=lambda s: f"{s}  ({sessions[s].source_label})",
        )
        st.session_state.active_session_id = picked
    else:
        picked = active_sid
    active = sessions[picked]

    _render_session_summary(active)
    st.markdown("---")

    # ── Step 2: Business context ──────────────────────────────────────────────
    with st.expander(
        "🏢 Step 2 — Business context (applied to every article)",
        expanded=not biz_ready,
    ):
        _render_business_block()

    if not biz_ready:
        st.warning(
            "⚠️ **Fill Business Context above first.** Niche and audience are required."
        )

    st.markdown("---")

    # ── Step 3: URL Map (optional) + Pages ───────────────────────────────────
    _render_url_map(active)
    st.markdown("---")
    _render_page_table(active, biz_ready=biz_ready)


# ── Step 1: Loader ────────────────────────────────────────────────────────────

def _render_loader() -> None:
    tab_files, tab_zip, tab_local = st.tabs([
        "📄 Upload files (recommended)",
        "🗜 Upload ZIP",
        "💻 Local folder",
    ])

    with tab_files:
        st.markdown(
            "**Upload BOTH files from your topical-map-engine-pro session:**\n"
            "- `topical_map.json` (your topical map structure)\n"
            "- `all_briefs.json` (all content briefs)"
        )
        col1, col2 = st.columns(2)
        with col1:
            tm = st.file_uploader(
                "1️⃣ topical_map.json",
                type=["json"],
                key="up_tm",
                help="Found in: topical-map-engine-pro/sessions/<id>/topical_map.json",
            )
        with col2:
            br = st.file_uploader(
                "2️⃣ all_briefs.json",
                type=["json"],
                key="up_br",
                help="Found in: topical-map-engine-pro/sessions/<id>/briefs/all_briefs.json",
            )

        label = st.text_input(
            "Session label",
            value="session-1",
            key="up_label",
            help="Used as session id — pick something memorable",
        )

        # Status feedback
        if tm and not br:
            st.warning("⏳ Now upload **all_briefs.json** in slot 2 →")
        elif br and not tm:
            st.warning("⏳ Now upload **topical_map.json** in slot 1 ←")
        elif tm and br:
            st.success("✅ Both files ready. Click **Load files** below.")

        if st.button(
            "🚀 Load files",
            key="btn_load_files",
            type="primary",
            disabled=not (tm and br),
        ):
            try:
                sess = bridge.load_from_files(tm, br, session_label=label)
                _register_session(sess)
                st.success(f"Loaded: {sess.session_id} ({len(sess.pages)} pages)")
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

    with tab_local:
        st.caption("Local development only — point to topical-map-engine-pro/sessions/<id>")
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
                    st.success(f"Loaded: {sess.session_id}")
                    st.rerun()
                else:
                    st.warning("Path is not a valid session folder.")
            except Exception as e:
                st.error(f"Load failed: {e}")


# ── Session summary ──────────────────────────────────────────────────────────

def _render_session_summary(sess: bridge.MapSession) -> None:
    status = find_status_map([p.page_id for p in sess.pages])
    total = len(sess.pages)
    done = sum(1 for p in sess.pages if status.get(p.page_id))
    pending = total - done

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Central entity", (sess.central_entity or "—")[:25])
    col2.metric("Total pages",    total)
    col3.metric("Articles done",  done)
    col4.metric("Pending",        pending)


# ── Step 2: Business context block ────────────────────────────────────────────

def _render_business_block() -> None:
    if "session_business" not in st.session_state:
        st.session_state.session_business = {
            "category": BusinessCategory.AGENCY.value,
            "niche":    "",
            "audience": "",
            "brand_name": "Zaman Arif",
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
        b["niche"] = st.text_input(
            "Niche *",
            value=b["niche"],
            placeholder="e.g. WordPress security and malware removal",
            key="sb_niche",
        )
        b["audience"] = st.text_input(
            "Audience * (comma-separated)",
            value=b["audience"],
            placeholder="e.g. WP site owners, agencies, e-commerce stores",
            key="sb_aud",
        )
    with col2:
        b["brand_name"] = st.text_input(
            "Brand",
            value=b["brand_name"],
            placeholder="Zaman Arif",
            key="sb_brand",
        )
        b["brand_voice_notes"] = st.text_area(
            "Voice notes (optional)",
            value=b["brand_voice_notes"],
            height=100,
            placeholder="Direct, expert tone. No fluff. Use concrete examples.",
            key="sb_voice",
        )
    st.session_state.session_business = b
    st.caption("* required fields")


def _build_business() -> BusinessContext:
    b = st.session_state.get("session_business", {})
    return BusinessContext(
        category=BusinessCategory(b.get("category", "service_business")),
        niche=b.get("niche") or "general",
        audience=[a.strip() for a in (b.get("audience", "") or "").split(",") if a.strip()],
        brand_name=b.get("brand_name") or None,
        brand_voice_notes=b.get("brand_voice_notes") or None,
    )


# ── URL Map editor (optional, collapsed) ─────────────────────────────────────

def _render_url_map(sess: bridge.MapSession) -> None:
    with st.expander("🔗 URL Map (optional — for internal link destinations)", expanded=False):
        if sess.url_map is None:
            st.info("No URL map loaded.")
            return

        st.caption(
            "Configure how page_ids resolve to URLs in injected internal links. "
            "Auto-generated slugs are used unless you set an explicit override."
        )

        col1, col2 = st.columns([3, 1])
        sess.url_map.base_url = col1.text_input(
            "Base URL",
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


# ── Step 3: Page table ────────────────────────────────────────────────────────

def _render_page_table(sess: bridge.MapSession, *, biz_ready: bool) -> None:
    st.subheader("📝 Step 3 — Pages")

    if not biz_ready:
        st.error(
            "🛑 **Business context not filled.** "
            "Go back to Step 2 above and set niche + audience before generating."
        )
        # Still show the list (read-only preview)

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
    col_a.caption(f"📊 {len(pending_ids)} pending in current filter")
    if col_b.button(
        f"⚡ Bulk generate ({len(pending_ids)})",
        disabled=(len(pending_ids) == 0 or not biz_ready),
        type="primary" if biz_ready else "secondary",
    ):
        _run_batch(sess, pending_ids)

    for p in sess.pages:
        if p.page_type not in type_filter:
            continue
        articles = status.get(p.page_id, [])
        with st.container(border=True):
            cols = st.columns([4, 1, 1, 1])
            badge = "✅ DONE" if articles else "⏳ pending"
            score = articles[0]["quality_score"] if articles else ""
            cols[0].markdown(
                f"**{p.page_title}**  \n"
                f"_{p.page_type}_ • `{p.page_id}` • intent: {p.primary_query or 'n/a'}"
            )
            cols[1].markdown(f"`{badge}`")
            cols[2].markdown(f"score: **{score}**" if score else "—")
            if cols[3].button(
                "Generate",
                key=f"gen_{p.page_id}",
                disabled=not biz_ready,
                type="primary" if biz_ready else "secondary",
            ):
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
    st.success(
        f"Batch done. {sum(1 for r in results if r[1]=='OK')} ok, "
        f"{sum(1 for r in results if r[1]=='FAIL')} failed."
    )
    with st.expander("Batch results", expanded=True):
        for pid, status_, info in results:
            st.write(f"- `{pid}` — **{status_}** — {info}")
    st.rerun()
