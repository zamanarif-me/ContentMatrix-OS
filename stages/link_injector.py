"""
Stage 7B: Internal Link Injector

Post-generation, scans the final markdown for the best place to inject each
brief.semantic_bridges anchor and the next_destination CTA link. This is a
SAFETY NET — the section_writer prompt already asks the LLM to weave links
in naturally, but LLMs sometimes skip them. This stage guarantees coverage.

Algorithm per bridge:
  1. If anchor_text already appears AS a markdown link, skip (LLM did it)
  2. If anchor_text appears as plain text, wrap it as [anchor](destination)
  3. If only shared_entity appears, wrap the first mention with the anchor
  4. If neither appears, append a contextual sentence to the most relevant
     section (one matching bridge_point keywords)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from content_models import GeneratedArticle
from stages.url_map import URLMap


@dataclass
class LinkInjectionReport:
    bridges_total:     int = 0
    bridges_wrapped:   int = 0       # anchor was already in text, wrapped it
    bridges_appended:  int = 0       # added new sentence with the link
    bridges_skipped:   int = 0       # already linked by the LLM
    next_dest_added:   bool = False


# ── Public API ────────────────────────────────────────────────────────────────

def inject_internal_links(article: GeneratedArticle) -> LinkInjectionReport:
    """
    Mutates article.final_md in place. Returns a report of what changed.
    """
    report = LinkInjectionReport()

    # Pull bridge data out of the brief that produced this article — but we
    # don't have direct access to the brief here. Instead, we look at the
    # article's outline.headings[*].target_entities AND the original brief
    # stored in business_context? No — brief lives in input_, not on article.
    #
    # Solution: callers pass the bridges in via the helper below.
    return report


def inject_from_brief(
    article: GeneratedArticle,
    bridges: list[dict],
    next_destination: dict | None,
    url_map: URLMap | None = None,
    page_titles: dict[str, str] | None = None,
) -> LinkInjectionReport:
    """
    Inject internal links based on the brief's semantic_bridges +
    next_destination. Mutates article.final_md.

    If url_map is provided, page_id destinations are resolved to real URLs.
    page_titles is a {page_id: title} hint used by url_map for slug fallback.
    """
    report = LinkInjectionReport()
    md = article.final_md or ""
    page_titles = page_titles or {}

    def _resolve(raw_dest: str) -> str:
        if not raw_dest:
            return raw_dest
        if raw_dest.startswith(("http://", "https://", "/")):
            return raw_dest
        if url_map is not None:
            return url_map.resolve(raw_dest, fallback_title=page_titles.get(raw_dest, ""))
        return raw_dest

    # ── Semantic bridges ─────────────────────────────────────────────────────
    for b in bridges or []:
        report.bridges_total += 1
        anchor = (b.get("anchor_suggestion") or "").strip()
        dest_raw = (b.get("link_destination") or "").strip()
        dest = _resolve(dest_raw)
        entity = (b.get("shared_entity") or "").strip()
        bridge_point = (b.get("bridge_point") or "").strip()

        if not anchor or not dest:
            report.bridges_skipped += 1
            continue

        # Skip if anchor already linked
        if _is_already_linked(md, anchor):
            report.bridges_skipped += 1
            continue

        # Try wrapping plain anchor text
        wrapped, did_wrap = _wrap_first_occurrence(md, anchor, dest)
        if did_wrap:
            md = wrapped
            report.bridges_wrapped += 1
            continue

        # Try wrapping shared entity mention
        if entity:
            wrapped, did_wrap = _wrap_first_occurrence(md, entity, dest, label=anchor)
            if did_wrap:
                md = wrapped
                report.bridges_wrapped += 1
                continue

        # Fallback: append a sentence to the most relevant section
        md = _append_link_sentence(md, anchor, dest, bridge_point)
        report.bridges_appended += 1

    # ── Next destination CTA ─────────────────────────────────────────────────
    if next_destination:
        anchor = (next_destination.get("transition_anchor") or "").strip()
        page_id = (next_destination.get("next_page_id") or "").strip()
        page_title = (next_destination.get("next_page_title") or "").strip()
        if anchor and (page_id or page_title):
            raw = page_id or _slugify(page_title)
            dest = _resolve(raw)
            if not _is_already_linked(md, anchor) and not _is_already_linked(md, page_title):
                md = _append_next_dest_block(md, anchor, dest, page_title)
                report.next_dest_added = True

    article.final_md = md
    return report


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_already_linked(md: str, text: str) -> bool:
    """True if `text` appears inside a markdown link [text](url)."""
    if not text:
        return False
    pattern = r"\[[^\]]*" + re.escape(text) + r"[^\]]*\]\([^)]+\)"
    return bool(re.search(pattern, md, flags=re.IGNORECASE))


def _wrap_first_occurrence(
    md: str,
    needle: str,
    destination: str,
    label: str | None = None,
) -> tuple[str, bool]:
    """
    Wrap the first whole-word occurrence of `needle` as a markdown link.
    Avoids wrapping inside existing links or headings.
    Returns (new_md, changed).
    """
    if not needle:
        return md, False
    link_text = label or needle

    # Build a pattern that matches `needle` but NOT inside [...](...) or after #
    pattern = re.compile(
        r"(?<!\[)(?<!\!)\b" + re.escape(needle) + r"\b(?!\])",
        flags=re.IGNORECASE,
    )

    # Walk line by line so we can skip heading lines
    lines = md.split("\n")
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        m = pattern.search(line)
        if m:
            start, end = m.span()
            lines[i] = line[:start] + f"[{link_text}]({destination})" + line[end:]
            return "\n".join(lines), True
    return md, False


def _append_link_sentence(
    md: str,
    anchor: str,
    destination: str,
    bridge_point: str,
) -> str:
    """
    Append a contextual sentence with the link to the most relevant section.
    Relevance = section heading or body containing bridge_point keywords.
    """
    sections = _split_by_h2(md)
    if not sections:
        return md + f"\n\nRelated: [{anchor}]({destination}).\n"

    # Score sections by keyword overlap with bridge_point
    keywords = [w.lower() for w in re.findall(r"\w+", bridge_point) if len(w) > 3]
    best_idx, best_score = 0, -1
    for i, sec in enumerate(sections):
        sec_low = sec.lower()
        score = sum(1 for k in keywords if k in sec_low)
        if score > best_score:
            best_score, best_idx = score, i

    insertion = f"\n\nFor related setup, see [{anchor}]({destination}).\n"
    sections[best_idx] = sections[best_idx].rstrip() + insertion
    return "\n\n".join(sections)


def _append_next_dest_block(
    md: str,
    anchor: str,
    destination: str,
    page_title: str,
) -> str:
    """Append a final 'Next' CTA block before any closing template metadata."""
    block = (
        f"\n\n---\n\n"
        f"**Next:** [{anchor}]({destination})  \n"
        f"_Continue with: {page_title}_\n"
    )
    return md.rstrip() + block


def _split_by_h2(md: str) -> list[str]:
    """Split markdown into chunks delimited by H2 headings."""
    parts = re.split(r"(?m)^## ", md)
    if len(parts) <= 1:
        return [md]
    # First part is pre-H2 content; subsequent parts need ## prefix restored
    return [parts[0]] + [f"## {p}" for p in parts[1:]]


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]
