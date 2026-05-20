"""
Session Manager — persists generated articles to disk.

Layout:
  sessions/<session_id>/
    article.md
    article.html
    article.json   <- full GeneratedArticle dump (for reload)
    meta.json

  sessions/index.json  <- list of all sessions for the sidebar
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from content_models import (
    ArticleStatus,
    GeneratedArticle,
    SessionMeta,
)


SESSIONS_DIR = Path(__file__).parent.parent / "sessions"
INDEX_FILE   = SESSIONS_DIR / "index.json"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower().strip())[:40].strip("_")


def make_session_id(article: GeneratedArticle) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{ts}_{_slug(article.title)}"


def session_path(session_id: str) -> Path:
    return SESSIONS_DIR / session_id


# ── Save ──────────────────────────────────────────────────────────────────────

def save_session(article: GeneratedArticle, session_id: Optional[str] = None) -> Path:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    if session_id is None:
        session_id = make_session_id(article)
    out = session_path(session_id)
    out.mkdir(parents=True, exist_ok=True)

    # Full dump for reload
    (out / "article.json").write_text(
        json.dumps(article.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    # Convenience copies
    (out / "article.md").write_text(article.final_md or "", encoding="utf-8")

    meta = SessionMeta(
        session_id=session_id,
        article_id=article.article_id,
        business_niche=article.business_context.niche,
        page_title=article.title,
        target_keyword=article.outline.primary_keyword or None,
        status=article.status,
        created_at=article.generated_at,
        updated_at=datetime.now(timezone.utc),
        cost_usd=article.cost_usd,
        quality_score=article.quality.overall_score,
        word_count=article.quality.word_count,
    )
    (out / "meta.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    _update_index(meta)
    return out


def _update_index(meta: SessionMeta) -> None:
    items = list_sessions()
    items = [s for s in items if s.get("session_id") != meta.session_id]
    items.insert(0, meta.model_dump(mode="json"))
    items = items[:100]
    INDEX_FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")


def list_sessions() -> list[dict]:
    if not INDEX_FILE.exists():
        return []
    try:
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def load_session(session_id: str) -> Optional[GeneratedArticle]:
    p = session_path(session_id) / "article.json"
    if not p.exists():
        return None
    try:
        return GeneratedArticle.model_validate(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return None


def delete_session(session_id: str) -> bool:
    import shutil
    out = session_path(session_id)
    if out.exists():
        shutil.rmtree(out)
    items = [s for s in list_sessions() if s.get("session_id") != session_id]
    INDEX_FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")
    return True
