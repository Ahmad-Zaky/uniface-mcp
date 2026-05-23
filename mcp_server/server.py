#!/usr/bin/env python3
"""
Uniface 10.4 documentation MCP server.

Exposes the scraped Uniface docs as tools for Claude (or any MCP client).

Tools
-----
  search_docs       Ranked keyword search across all 4,990 pages
  get_page          Full content of a page by ID
  list_sections     All top-level documentation sections with page counts
  browse_section    Pages within a named section
  lookup_reference  Exact-name lookup for triggers, properties, functions
  get_toc_children  Direct children of a page in the TOC hierarchy

Prerequisites
-------------
  pip install mcp
  cd scraper && python build_mcp_data.py   # generates site/assets/pages/ and index/

Wire into Claude Code — add to ~/.claude/claude_desktop_config.json:
  {
    "mcpServers": {
      "uniface-docs": {
        "command": "python",
        "args": ["/absolute/path/to/uniface-docs/mcp_server/server.py"]
      }
    }
  }
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# ── Paths ──────────────────────────────────────────────────────────────
ASSETS = Path(__file__).parent.parent / "site" / "assets"
PAGES_DIR = ASSETS / "pages"
INDEX_DIR = ASSETS / "index"


# ── Load indexes once at startup ───────────────────────────────────────

def _load(path: Path):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


_search_meta: list[dict] = _load(ASSETS / "search-meta.json") or []
_sections: dict[str, list[dict]] = _load(INDEX_DIR / "sections.json") or {}
_title_lookup: dict[str, str] = _load(INDEX_DIR / "title-lookup.json") or {}
_breadcrumb_map: dict[str, str] = _load(INDEX_DIR / "breadcrumb-map.json") or {}


def _build_toc_index(nodes: list[dict]) -> dict[str, dict]:
    index: dict[str, dict] = {}

    def walk(ns: list[dict]) -> None:
        for n in ns:
            index[n["id"]] = n
            walk(n.get("children", []))

    walk(nodes or [])
    return index


_toc_index: dict[str, dict] = _build_toc_index(_load(ASSETS / "toc.json") or [])

# ── Server ─────────────────────────────────────────────────────────────

mcp = FastMCP(
    "uniface-docs",
    instructions="Uniface 10.4 documentation — search, lookup, and navigation",
)


# ── Internal helpers ───────────────────────────────────────────────────

def _tokenize(query: str) -> list[str]:
    return [t.lower() for t in re.split(r"\s+", query.strip()) if len(t) > 1]


def _score(entry: dict, tokens: list[str]) -> float:
    score = 0.0
    title = entry.get("title", "").lower()
    crumbs = entry.get("breadcrumbs", "").lower()
    text = entry.get("text", "").lower()
    for tok in tokens:
        if tok in title:
            score += 10
        if title == tok:          # exact full-title match
            score += 25
        if tok in crumbs:
            score += 3
        if tok in text:
            score += 1
    return score


def _snippet(text: str, tokens: list[str], width: int = 220) -> str:
    lower = text.lower()
    pos = -1
    for tok in tokens:
        i = lower.find(tok)
        if i >= 0 and (pos == -1 or i < pos):
            pos = i
    start = max(0, pos - 60) if pos >= 0 else 0
    end = min(len(text), start + width)
    out = text[start:end].strip()
    if start > 0:
        out = "… " + out
    if end < len(text):
        out += " …"
    return out


def _read_page(page_id: str) -> dict | None:
    path = PAGES_DIR / f"{page_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _format_page(p: dict) -> str:
    crumbs = (
        " › ".join(p["breadcrumbs"])
        if isinstance(p.get("breadcrumbs"), list)
        else p.get("breadcrumbs", "")
    )
    lines = [
        f"Title: {p.get('title', '')}",
        f"Path:  {crumbs}",
        f"URL:   {p.get('url', '')}",
        f"ID:    {p['id']}",
        "─" * 60,
        p.get("text", "(no content)"),
    ]
    return "\n".join(lines)


# ── Tools ──────────────────────────────────────────────────────────────

@mcp.tool()
def search_docs(query: str, limit: int = 10) -> str:
    """
    Search Uniface 10.4 documentation by keyword.

    Scores matches by title (highest), breadcrumb path, and body text.
    Returns up to `limit` results with ID, path, and a text snippet.
    Call get_page(id) to retrieve the full content of any result.

    Args:
        query: One or more keywords to search for.
        limit: Maximum number of results to return (default 10, max 50).
    """
    if not query.strip():
        return "Provide a non-empty search query."
    if not _search_meta:
        return "Search index not loaded. Run scraper/build_mcp_data.py first."

    tokens = _tokenize(query)
    if not tokens:
        return "Query contains no usable terms."

    limit = min(limit, 50)
    hits = sorted(
        ((e, _score(e, tokens)) for e in _search_meta),
        key=lambda x: -x[1],
    )
    hits = [(e, s) for e, s in hits if s > 0][:limit]

    if not hits:
        return f"No results for '{query}'."

    lines = [f"Search: '{query}' — {len(hits)} result(s)\n"]
    for i, (entry, _) in enumerate(hits, 1):
        snippet = _snippet(entry.get("text", ""), tokens)
        lines.append(
            f"{i}. {entry.get('title', '(untitled)')}\n"
            f"   ID:   {entry['id']}\n"
            f"   Path: {entry.get('breadcrumbs', '')}\n"
            f"   {snippet}\n"
        )
    return "\n".join(lines)


@mcp.tool()
def get_page(page_id: str) -> str:
    """
    Retrieve the full documentation content for a page by its ID.

    The ID comes from search_docs results, browse_section, or lookup_reference.

    Args:
        page_id: The unique page identifier (e.g. 'aag1665703130023').
    """
    page = _read_page(page_id)
    if page is None:
        return (
            f"Page '{page_id}' not found. "
            "Run scraper/build_mcp_data.py to generate the pages directory, "
            "or verify the ID with search_docs."
        )
    return _format_page(page)


@mcp.tool()
def list_sections() -> str:
    """
    List all top-level documentation sections with their page counts.

    Use browse_section(section_name) to explore pages within a section.
    """
    if not _sections:
        return "Section index not loaded. Run scraper/build_mcp_data.py first."

    lines = ["Uniface 10.4 documentation sections:\n"]
    for name, pages in sorted(_sections.items(), key=lambda x: -len(x[1])):
        lines.append(f"  {len(pages):4d} pages  {name}")
    return "\n".join(lines)


@mcp.tool()
def browse_section(section_name: str, offset: int = 0, limit: int = 30) -> str:
    """
    List pages within a named top-level documentation section.

    Section names come from list_sections(). Supports pagination via offset.

    Args:
        section_name: Exact section name (e.g. 'Uniface Reference').
        offset:       Skip this many entries (for pagination, default 0).
        limit:        Entries to return per call (default 30, max 100).
    """
    if not _sections:
        return "Section index not loaded. Run scraper/build_mcp_data.py first."

    # Case-insensitive match
    key = next(
        (k for k in _sections if k.lower() == section_name.lower()),
        None,
    )
    if key is None:
        close = [k for k in _sections if section_name.lower() in k.lower()]
        hint = f" Did you mean: {', '.join(close[:5])}?" if close else ""
        return f"Section '{section_name}' not found.{hint}"

    pages = _sections[key]
    limit = min(limit, 100)
    chunk = pages[offset : offset + limit]
    total = len(pages)

    lines = [f"Section: {key} ({total} pages, showing {offset + 1}–{offset + len(chunk)})\n"]
    for entry in chunk:
        lines.append(
            f"  [{entry['id']}]  {entry['title']}\n"
            f"    {entry['crumbs']}"
        )
    if offset + limit < total:
        lines.append(
            f"\n→ More: browse_section('{key}', offset={offset + limit})"
        )
    return "\n".join(lines)


@mcp.tool()
def lookup_reference(name: str) -> str:
    """
    Look up a Uniface reference entry by its exact name (case-insensitive).

    Best for the Uniface Reference section: triggers, properties, component
    fields, DBMS specifics, and other named constructs.
    Returns the full page content when an exact match is found.

    Args:
        name: The exact name to look up (e.g. 'trigger clear', 'Derived Component Field').
    """
    if not _title_lookup:
        return "Title index not loaded. Run scraper/build_mcp_data.py first."

    pid = _title_lookup.get(name.lower())
    if pid is None:
        # Fuzzy fallback: find titles containing the search term
        matches = [
            (title, pid)
            for title, pid in _title_lookup.items()
            if name.lower() in title
        ]
        if not matches:
            return f"No reference entry found for '{name}'."
        if len(matches) == 1:
            pid = matches[0][1]
        else:
            lines = [f"No exact match for '{name}'. Partial matches:\n"]
            for title, mid in sorted(matches[:20]):
                lines.append(f"  [{mid}]  {title}")
            if len(matches) > 20:
                lines.append(f"  … and {len(matches) - 20} more")
            return "\n".join(lines)

    page = _read_page(pid)
    if page is None:
        return f"Index entry found (ID: {pid}) but page file is missing. Run scraper/build_mcp_data.py."
    return _format_page(page)


@mcp.tool()
def get_toc_children(page_id: str) -> str:
    """
    Return the direct children of a page in the table-of-contents hierarchy.

    Useful for navigating the documentation tree. Use the TOC root IDs from
    list_sections or search_docs to start exploring.

    Args:
        page_id: The ID of the parent page whose children you want.
    """
    node = _toc_index.get(page_id)
    if node is None:
        return f"Page ID '{page_id}' not found in the TOC."

    children = node.get("children", [])
    if not children:
        return f"'{node['title']}' is a leaf node with no children."

    lines = [f"Children of '{node['title']}' ({len(children)}):\n"]
    for child in children:
        has_children = "⊕" if child.get("children") else "·"
        lines.append(f"  {has_children} [{child['id']}]  {child['title']}")
    return "\n".join(lines)


# ── Entry point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
