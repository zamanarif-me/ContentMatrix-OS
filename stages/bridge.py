"""
Bridge — connects ContentMatrix OS to topical-map-engine-pro output.

Supports THREE input sources (production-ready for Streamlit Cloud):

  1. Local sibling folder    — for local development
  2. Uploaded ZIP archive    — for production (export session from
                               topical-map-engine, upload here)
  3. Individual file pair    — for ad-hoc loading
                               (topical_map.json + all_briefs.json)

All three normalize to a MapSession object that the UI and pipeline
consume identically.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Optional

from content_models import BriefSource, BusinessContext, ContentEngineInput, TopicalMapRef
from stages.url_map import URLMap, load_for_session


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class MapSessionPage:
    """One page within a loaded topical-map session."""
    page_id:    str
    page_title: str
    page_type:  str = "unknown"
    parent_pillar: Optional[str] = None
    primary_query: Optional[str] = None


@dataclass
class MapSession:
    """A loaded topical-map-engine session, ready for ContentMatrix consumption."""
    session_id:      str
    source_label:    str
    central_entity:  Optional[str]
    topical_map_raw: dict
    briefs:          dict[str, dict]
    pages:           list[MapSessionPage] = field(default_factory=list)
    created_at:      Optional[str] = None
    url_map:         Optional["URLMap"] = None


# ── Loader 1: Local folder ────────────────────────────────────────────────────

def load_from_local_folder(session_dir: str | Path) -> MapSession:
    session_dir = Path(session_dir)
    if not session_dir.is_dir():
        raise FileNotFoundError(f"Not a directory: {session_dir}")

    tm_path     = session_dir / "topical_map.json"
    briefs_path = session_dir / "briefs" / "all_briefs.json"
    meta_path   = session_dir / "session_meta.json"

    if not tm_path.exists():
        raise FileNotFoundError(f"Missing topical_map.json in {session_dir}")
    if not briefs_path.exists():
        raise FileNotFoundError(f"Missing briefs/all_briefs.json in {session_dir}")

    tm_raw  = json.loads(tm_path.read_text(encoding="utf-8"))
    briefs  = json.loads(briefs_path.read_text(encoding="utf-8"))
    meta    = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    sess = _build_session(
        session_id=session_dir.name,
        source_label=f"local: {session_dir.name}",
        tm_raw=tm_raw,
        briefs=briefs,
        meta=meta,
    )
    sess.url_map = load_for_session(session_dir)
    _ensure_url_coverage(sess)
    return sess


# ── Loader 2: Uploaded ZIP ────────────────────────────────────────────────────

def load_from_zip(uploaded_file: IO, original_name: str = "session.zip") -> MapSession:
    tmpdir = Path(tempfile.mkdtemp(prefix="cmos_session_"))
    try:
        with zipfile.ZipFile(uploaded_file) as zf:
            zf.extractall(tmpdir)

        candidate = _find_session_root(tmpdir)
        if candidate is None:
            raise ValueError(
                "Zip does not contain a valid session "
                "(need topical_map.json + briefs/all_briefs.json)"
            )

        sess = load_from_local_folder(candidate)
        sess.session_id = candidate.name
        sess.source_label = f"zip: {original_name}"
        return sess
    finally:
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


def _find_session_root(root: Path) -> Optional[Path]:
    for candidate in [root] + [p for p in root.rglob("*") if p.is_dir()]:
        if (candidate / "topical_map.json").exists() and \
           (candidate / "briefs" / "all_briefs.json").exists():
            return candidate
    return None


# ── Loader 3: Individual file uploads ─────────────────────────────────────────

def load_from_files(
    topical_map_json: IO | str | bytes,
    briefs_json:      IO | str | bytes,
    session_label:    str = "upload",
) -> MapSession:
    tm_raw  = _read_json(topical_map_json)
    briefs  = _read_json(briefs_json)
    sess = _build_session(
        session_id=_slugify(session_label),
        source_label=f"files: {session_label}",
        tm_raw=tm_raw,
        briefs=briefs,
        meta={},
    )
    _ensure_url_coverage(sess)
    return sess


def _read_json(payload) -> dict:
    if hasattr(payload, "read"):
        return json.loads(payload.read())
    if isinstance(payload, bytes):
        return json.loads(payload.decode("utf-8"))
    if isinstance(payload, str):
        return json.loads(payload)
    raise TypeError(f"Cannot read JSON from {type(payload)}")


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower())[:40].strip("_") or "upload"


# ── URL coverage helper ──────────────────────────────────────────────────────

def _ensure_url_coverage(sess: MapSession) -> None:
    if sess.url_map is None:
        sess.url_map = URLMap()
    pages_for_slug = [
        {"page_id": p.page_id, "page_title": p.page_title}
        for p in sess.pages
    ]
    sess.url_map.autopopulate_from_pages(pages_for_slug)


# ── Shared builder ────────────────────────────────────────────────────────────

def _build_session(
    session_id: str,
    source_label: str,
    tm_raw: dict,
    briefs: dict,
    meta: dict,
) -> MapSession:
    tm = tm_raw.get("topical_map", tm_raw)

    pages: list[MapSessionPage] = []
    for page_id, brief in briefs.items():
        pages.append(MapSessionPage(
            page_id=page_id,
            page_title=brief.get("page_title", "Untitled"),
            page_type=brief.get("page_type", "unknown"),
            parent_pillar=brief.get("parent_pillar"),
            primary_query=(brief.get("queries") or {}).get("primary_query"),
        ))

    central = _resolve_central_entity(tm, briefs)

    return MapSession(
        session_id=session_id,
        source_label=source_label,
        central_entity=central,
        topical_map_raw=tm_raw,
        briefs=briefs,
        pages=sorted(pages, key=lambda p: (p.page_type, p.page_title)),
        created_at=meta.get("created_at"),
    )


def _resolve_central_entity(tm: dict, briefs: dict) -> Optional[str]:
    """
    Resolve the session's central entity using a layered approach.

    Briefs are authoritative — they describe the actual pages being generated.
    The topical_map's stored central_entity can be stale (e.g. reused topical
    map file from a previous session), so we cross-check against brief data.

    Resolution order:
      1. Majority central_entity across all briefs (most authoritative —
         every brief carries its own canonical entity)
      2. Majority parent_pillar across all briefs (derived authority)
      3. topical_map.central_entity.primary (legacy / static field)
      4. topical_map.central_entity as string
      5. First brief's primary_query (last-ditch derivation)
    """
    from collections import Counter

    # 1. Majority central_entity from briefs
    brief_entities = [
        b.get("central_entity", "").strip()
        for b in briefs.values()
        if isinstance(b.get("central_entity"), str) and b.get("central_entity", "").strip()
    ]
    if brief_entities:
        most_common = Counter(brief_entities).most_common(1)[0][0]
        if most_common:
            return most_common

    # 2. Majority parent_pillar from briefs
    pillars = [
        b.get("parent_pillar", "").strip()
        for b in briefs.values()
        if isinstance(b.get("parent_pillar"), str) and b.get("parent_pillar", "").strip()
    ]
    if pillars:
        most_common = Counter(pillars).most_common(1)[0][0]
        if most_common:
            # If the pillar looks like an id (e.g. "pillar_xxx_001"), try to
            # find its title from topical_map.pillars[]
            for p in tm.get("pillars", []):
                if p.get("id") == most_common and p.get("title"):
                    return p["title"]
            return most_common

    # 3. topical_map nested form
    ce = tm.get("central_entity")
    if isinstance(ce, dict):
        primary = ce.get("primary")
        if primary:
            return primary
    # 4. topical_map flat string
    if isinstance(ce, str) and ce.strip():
        return ce.strip()

    # 5. First brief's primary_query as fallback
    for b in briefs.values():
        q = (b.get("queries") or {}).get("primary_query")
        if q:
            return q.title()

    return None


# ── Helper: build a ContentEngineInput for one page ──────────────────────────

def make_engine_input(
    session: MapSession,
    page_id: str,
    business: BusinessContext,
) -> ContentEngineInput:
    if page_id not in session.briefs:
        raise KeyError(f"page_id '{page_id}' not in session {session.session_id}")

    brief = session.briefs[page_id]
    tm = session.topical_map_raw.get("topical_map", session.topical_map_raw)

    tm_ref = TopicalMapRef(
        source=session.source_label,
        central_entity=session.central_entity,
        pillars=[{"id": p.get("id"), "title": p.get("title")} for p in tm.get("pillars", [])],
        geo_pages=[{"id": g.get("id"), "title": g.get("title")} for g in tm.get("geo_pages", [])],
    )

    ci = ContentEngineInput(
        business=business,
        brief_source=BriefSource.FROM_ENGINE,
        brief_payload=brief,
        topical_map_ref=tm_ref,
        target_keyword=(brief.get("queries") or {}).get("primary_query"),
    )
    ci._url_map = session.url_map  # type: ignore[attr-defined]
    ci._page_titles = {p.page_id: p.page_title for p in session.pages}  # type: ignore[attr-defined]
    return ci
