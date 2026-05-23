#!/usr/bin/env python3
"""
Build MCP-friendly data from scraped output alongside existing SPA assets.

Does NOT touch toc.json, docs.json, or search-meta.json — the SPA keeps working.

Reads:
  data/toc.json
  data/pages/*.json

Writes:
  ../site/assets/pages/{id}.json          { id, title, breadcrumbs, url, text }
  ../site/assets/index/sections.json      { section: [{id, title, crumbs, url}] }
  ../site/assets/index/title-lookup.json  { title_lower: id }
  ../site/assets/index/breadcrumb-map.json { id: "A › B › C" }

USAGE
  cd scraper
  python build_mcp_data.py

  # or from project root:
  python scraper/build_mcp_data.py --data scraper/data --out site/assets
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup  # type: ignore

# ── Zoomin chrome selectors — strip from every page ───────────────────
# Kept in sync with build_site_data.py
_NOISE_SELECTORS = [
    "[class*='zDocsTopicActions']",
    "[class*='zDocsBundlePagination']",
    "[class*='zDocsScrollTopBtn']",
    "[class*='zDocsMyDocsMenu']",
    "[class*='zDocsExportPdfMenu']",
    "[class*='zDocsDropdownMenu']",
    "[class*='zDocsFeedback']",
    "[class*='zDocsAiTopicSummary']",
    "[class*='zDocsTopicPageDetails']",
    "[class*='zDocsTopicActionsMobile']",
    "[class*='zDocsShareDialog']",
    "[data-testid='next-prev-container']",
    "script",
    "style",
    "form",
    "nav",
]


def extract_clean_text(raw_html: str) -> str:
    """Strip Zoomin chrome from raw scraped HTML and return plain text."""
    soup = BeautifulSoup(raw_html, "lxml")

    for sel in _NOISE_SELECTORS:
        for el in soup.select(sel):
            el.decompose()

    # Strip zDocsTopicPageHead only when the body content has its own h1
    # (otherwise the heading would disappear entirely)
    page_head = soup.select_one("[class*='zDocsTopicPageHead']")
    if page_head:
        body_content = soup.select_one("[class*='zDocsTopicPageBodyContent']")
        if body_content and body_content.find("h1"):
            page_head.decompose()

    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--data", default="data", help="Scraped data dir (default: data/)")
    ap.add_argument(
        "--out",
        default="../site/assets",
        help="Output assets dir (default: ../site/assets)",
    )
    args = ap.parse_args()

    src = Path(args.data)
    dst = Path(args.out)

    for required in [src / "toc.json", src / "pages"]:
        if not required.exists():
            print(f"ERROR: {required} not found — run scraper first", file=sys.stderr)
            return 1

    pages_dst = dst / "pages"
    index_dst = dst / "index"
    pages_dst.mkdir(parents=True, exist_ok=True)
    index_dst.mkdir(parents=True, exist_ok=True)

    # ── Process pages ────────────────────────────────────────────────
    page_files = sorted((src / "pages").glob("*.json"))
    total = len(page_files)
    print(f"→ processing {total} pages…", file=sys.stderr)

    sections: dict[str, list[dict]] = {}
    title_lookup: dict[str, str] = {}
    breadcrumb_map: dict[str, str] = {}

    for i, fp in enumerate(page_files, 1):
        raw = json.loads(fp.read_text(encoding="utf-8"))
        pid = raw["id"]
        title = raw.get("title", "")
        breadcrumbs: list[str] = raw.get("breadcrumbs", [])
        url = raw.get("url", "")
        raw_html = raw.get("html", "")

        text = extract_clean_text(raw_html) if raw_html else raw.get("text", "")

        # per-page file (text only — no HTML, MCP consumers don't need it)
        (pages_dst / f"{pid}.json").write_text(
            json.dumps(
                {"id": pid, "title": title, "breadcrumbs": breadcrumbs, "url": url, "text": text},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        crumb_str = " › ".join(breadcrumbs)
        section = breadcrumbs[0] if breadcrumbs else "Uncategorised"

        sections.setdefault(section, []).append(
            {"id": pid, "title": title, "crumbs": crumb_str, "url": url}
        )
        if title:
            title_lookup[title.lower()] = pid
        breadcrumb_map[pid] = crumb_str

        if i % 500 == 0:
            print(f"  {i}/{total}…", file=sys.stderr)

    # ── Write indexes ────────────────────────────────────────────────
    (index_dst / "sections.json").write_text(
        json.dumps(sections, ensure_ascii=False), encoding="utf-8"
    )
    (index_dst / "title-lookup.json").write_text(
        json.dumps(title_lookup, ensure_ascii=False), encoding="utf-8"
    )
    (index_dst / "breadcrumb-map.json").write_text(
        json.dumps(breadcrumb_map, ensure_ascii=False), encoding="utf-8"
    )

    print(f"✓ {total} pages  →  {pages_dst}/", file=sys.stderr)
    print(f"✓ {len(sections)} sections  →  {index_dst}/sections.json", file=sys.stderr)
    print(f"✓ title lookup ({len(title_lookup)} entries)  →  {index_dst}/title-lookup.json", file=sys.stderr)
    print(f"✓ breadcrumb map  →  {index_dst}/breadcrumb-map.json", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
