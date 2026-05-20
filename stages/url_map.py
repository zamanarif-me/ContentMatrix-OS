"""
URL Map — resolves page_id → live URL for internal link injection.

Resolution order (per page_id):
  1. explicit[page_id]          — user-set override (exact URL)
  2. base_url + slugs[page_id]  — auto-generated slug
  3. page_id as-is              — fallback (shows in links, not ideal)

URLMap is stored in MapSession and passed to link_injector via ContentEngineInput._url_map.
It is also persisted as url_map.json inside the session folder.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class URLMap:
    base_url:     str = ""
    explicit:     dict[str, str] = field(default_factory=dict)   # user overrides
    slugs:        dict[str, str] = field(default_factory=dict)   # auto-generated
    append_slash: bool = True

    # ── Resolution ────────────────────────────────────────────────────────────

    def resolve(self, page_id: str, fallback_title: str = "") -> str:
        """Return the best URL for page_id."""
        # 1. Explicit user override
        if page_id in self.explicit:
            return self.explicit[page_id]

        # 2. base_url + slug
        slug = self.slugs.get(page_id) or _slugify(fallback_title or page_id)
        if self.base_url:
            base = self.base_url.rstrip("/")
            sep = "/" if self.append_slash else ""
            return f"{base}/{slug}{sep}"

        # 3. Fallback: raw page_id
        return page_id

    def set_url(self, page_id: str, url: str) -> None:
        """Set an explicit URL override for a page."""
        self.explicit[page_id] = url.strip()

    # ── Slug auto-population ──────────────────────────────────────────────────

    def autopopulate_from_pages(self, pages: list[dict]) -> int:
        """
        Fill missing slugs from page titles.
        pages: list of {"page_id": str, "page_title": str}
        Returns number of new slugs added.
        """
        added = 0
        for p in pages:
            pid = p.get("page_id", "")
            if pid and pid not in self.slugs:
                title = p.get("page_title", pid)
                self.slugs[pid] = _slugify(title)
                added += 1
        return added

    # ── Coverage stats ────────────────────────────────────────────────────────

    def coverage(self, page_ids: list[str]) -> dict:
        """Return coverage breakdown for a list of page_ids."""
        total    = len(page_ids)
        explicit = sum(1 for p in page_ids if p in self.explicit)
        slugged  = sum(1 for p in page_ids if p not in self.explicit and p in self.slugs)
        fallback = total - explicit - slugged
        return {
            "total":    total,
            "explicit": explicit,
            "slugged":  slugged,
            "fallback": fallback,
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "base_url":     self.base_url,
            "append_slash": self.append_slash,
            "explicit":     self.explicit,
            "slugs":        self.slugs,
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def from_file(cls, path: str | Path) -> "URLMap":
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            base_url=data.get("base_url", ""),
            append_slash=data.get("append_slash", True),
            explicit=data.get("explicit", {}),
            slugs=data.get("slugs", {}),
        )


# ── Session loader ────────────────────────────────────────────────────────────

def load_for_session(session_dir: str | Path) -> Optional[URLMap]:
    """
    Load url_map.json from session folder if it exists.
    Returns None if not found — caller should create a fresh URLMap().
    """
    path = Path(session_dir) / "url_map.json"
    if path.exists():
        try:
            return URLMap.from_file(path)
        except Exception:
            pass
    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:80] or "page"
