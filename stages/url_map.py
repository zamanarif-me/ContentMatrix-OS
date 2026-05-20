"""
URL Map — production-ready internal link destinations.

Problem: topical-map-engine outputs `page_id` strings (e.g. `pillar_wp_security_001`).
ContentMatrix OS needs real URLs (e.g. `https://example.com/wordpress-security/`)
to inject valid markdown links into generated articles.

Resolution order for a given page_id:
  1. Explicit override in url_map.json (user-curated)
  2. Auto-generated slug + configured base_url
  3. Raw page_id as fallback (so links still exist, even if broken)

URL maps live alongside the topical-map session:
    sessions/<id>/
      topical_map.json
      briefs/all_briefs.json
      url_map.json          <- NEW, optional
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class URLMap:
    """
    Maps topical-map page_ids to real URLs.

    Fields:
      base_url       Origin + optional path prefix, e.g. "https://example.com/blog"
                     Always normalized to NO trailing slash.
      explicit       page_id -> absolute or relative URL (takes precedence over slug)
      slugs          page_id -> slug (used if not in explicit). Auto-generated
                     from page_title at load time if missing.
      append_slash   Append trailing slash to generated URLs (WordPress default)
    """
    base_url:     str = ""
    explicit:     dict[str, str] = field(default_factory=dict)
    slugs:        dict[str, str] = field(default_factory=dict)
    append_slash: bool = True

    # ── Resolution ─────────────────────────────────────────────────────────────

    def resolve(self, page_id: str, fallback_title: str = "") -> str:
        """
        Return the best available URL for a page_id. Never raises — falls back
        to the page_id itself so generated articles always have a string.
        """
        if not page_id:
            return ""

        # 1. Explicit override wins
        if page_id in self.explicit:
            return self._normalize(self.explicit[page_id])

        # 2. Slug + base_url
        slug = self.slugs.get(page_id) or _slugify(fallback_title) or _slugify(page_id)
        if slug:
            return self._build(slug)

        # 3. Last-resort fallback
        return page_id

    def _build(self, slug: str) -> str:
        slug = slug.strip("/").strip()
        if self.base_url:
            url = f"{self.base_url.rstrip('/')}/{slug}"
        else:
            url = f"/{slug}"
        if self.append_slash and not url.endswith("/"):
            url += "/"
        return url

    def _normalize(self, url: str) -> str:
        """If a URL looks bare-relative, prefix with base_url."""
        url = url.strip()
        if not url:
            return url
        if url.startswith(("http://", "https://", "//", "mailto:", "tel:")):
            return url
        if not self.base_url:
            return url if url.startswith("/") else f"/{url}"
        return f"{self.base_url.rstrip('/')}/{url.lstrip('/')}"

    # ── Persistence ────────────────────────────────────────────────────────────

    @classmethod
    def from_file(cls, path: str | Path) -> "URLMap":
        path = Path(path)
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                base_url=    data.get("base_url", ""),
                explicit=    dict(data.get("explicit", {})),
                slugs=       dict(data.get("slugs", {})),
                append_slash=bool(data.get("append_slash", True)),
            )
        except Exception:
            return cls()

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(asdict(self), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    # ── Population helpers ─────────────────────────────────────────────────────

    def autopopulate_from_pages(self, pages: list[dict]) -> int:
        """
        Walk a list of {page_id, page_title} dicts and fill missing slugs.
        Returns the number of slugs added.
        """
        added = 0
        for p in pages:
            pid = p.get("page_id") or p.get("id")
            title = p.get("page_title") or p.get("title") or ""
            if not pid or pid in self.slugs or pid in self.explicit:
                continue
            slug = _slugify(title) or _slugify(pid)
            if slug:
                self.slugs[pid] = slug
                added += 1
        return added

    def set_url(self, page_id: str, url: str) -> None:
        """User-curated override."""
        self.explicit[page_id] = url

    def coverage(self, page_ids: list[str]) -> dict:
        """Stats for the UI dashboard."""
        total = len(page_ids)
        explicit = sum(1 for p in page_ids if p in self.explicit)
        slugged = sum(1 for p in page_ids if p in self.slugs and p not in self.explicit)
        fallback = total - explicit - slugged
        return {
            "total":    total,
            "explicit": explicit,
            "slugged":  slugged,
            "fallback": fallback,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    if not text:
        return ""
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return s[:80]


# ── Session integration ───────────────────────────────────────────────────────

def load_for_session(session_dir: str | Path) -> URLMap:
    """
    Load `url_map.json` from a topical-map session folder.
    Missing or invalid file -> returns an empty URLMap.
    """
    return URLMap.from_file(Path(session_dir) / "url_map.json")
