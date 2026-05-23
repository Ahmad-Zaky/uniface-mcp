# Uniface 10.4 Docs — MCP Server & Client

This guide covers everything needed to expose the scraped Uniface 10.4
documentation as an **MCP (Model Context Protocol) server** and interact
with it through an LLM-powered client.

The MCP layer sits **alongside** the browser SPA — both use the same
scraped data and neither breaks the other.

---

## Table of Contents

1. [What is the MCP layer?](#1-what-is-the-mcp-layer)
2. [Project structure](#2-project-structure)
3. [Prerequisites](#3-prerequisites)
4. [Step 1 — Build the MCP data](#4-step-1--build-the-mcp-data)
5. [Step 2 — Install dependencies](#5-step-2--install-dependencies)
6. [Step 3 — Set your API key](#6-step-3--set-your-api-key)
7. [Step 4 — Run the client](#7-step-4--run-the-client)
8. [Step 5 — Wire into Claude Code (optional)](#8-step-5--wire-into-claude-code-optional)
9. [Available tools](#9-available-tools)
10. [Example interactions](#10-example-interactions)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. What is the MCP layer?

**MCP (Model Context Protocol)** is an open standard that lets LLMs call
tools on a running server. Instead of pasting documentation into a prompt,
Claude (or any MCP-compatible model) can call tools like `search_docs` or
`get_page` at inference time and retrieve exactly what it needs.

```
You ──► mcp_client/client.py  ──► Groq LLM (llama-3.3-70b)
                │                        │
                │   tool call request    │
                ▼                        ▼
         mcp_server/server.py ◄──────────┘
                │
         site/assets/pages/
         site/assets/index/
         site/assets/search-meta.json
         site/assets/toc.json
```

The MCP server exposes **6 tools** over stdio. The client wraps an LLM
that decides which tools to call, executes them, and synthesises the
results into a natural-language answer.

**The browser SPA is unaffected** — `docs.json`, `toc.json`, and
`search-meta.json` are not touched.

---

## 2. Project structure

```
uniface-docs/
├── scraper/
│   ├── scrape.py                # Playwright scraper (run first)
│   ├── build_site_data.py       # Builds SPA assets (docs.json etc.)
│   ├── build_mcp_data.py        # ← NEW: builds MCP assets
│   └── requirements.txt
│
├── site/
│   └── assets/
│       ├── toc.json             # (SPA + MCP — unchanged)
│       ├── docs.json            # (SPA only — unchanged)
│       ├── search-meta.json     # (SPA + MCP — unchanged)
│       ├── pages/               # ← NEW: one JSON per page, text-only
│       │   └── <page-id>.json
│       └── index/               # ← NEW: precomputed lookup indexes
│           ├── sections.json
│           ├── title-lookup.json
│           └── breadcrumb-map.json
│
├── mcp_server/
│   ├── server.py                # ← NEW: FastMCP server (6 tools)
│   └── requirements.txt
│
├── mcp_client/
│   ├── client.py                # ← NEW: Groq-powered interactive client
│   └── requirements.txt
│
├── README.md                    # Browser SPA guide
└── MCP.md                       # This file
```

---

## 3. Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | The project uses `match`-free syntax; 3.10 is safe |
| Scraped data | `scraper/data/pages/*.json` must exist (run `scrape.py` first — see main README) |
| Virtual environment | Recommended — instructions below use the project `.venv` |

> **If you haven't scraped yet**, follow the main `README.md` first.
> The MCP layer has nothing to serve without the scraped pages.

---

## 4. Step 1 — Build the MCP data

This is a one-time step (re-run only after a fresh scrape).

```bash
cd scraper
source ../.venv/bin/activate     # or your own venv

python build_mcp_data.py
```

Expected output:

```
→ processing 4990 pages…
  500/4990…
  …
✓ 4990 pages  →  ../site/assets/pages/
✓ 27 sections  →  ../site/assets/index/sections.json
✓ title lookup (4553 entries)  →  ../site/assets/index/title-lookup.json
✓ breadcrumb map  →  ../site/assets/index/breadcrumb-map.json
```

If your scraped data lives somewhere other than `data/`:

```bash
python build_mcp_data.py --data /path/to/scraped/data --out ../site/assets
```

### What this builds

| File | Size | Purpose |
|---|---|---|
| `site/assets/pages/<id>.json` | ~6 KB each | Clean text content per page (no HTML) |
| `site/assets/index/sections.json` | ~1.4 MB | Pages grouped by top-level section |
| `site/assets/index/title-lookup.json` | ~197 KB | Lowercase title → page ID |
| `site/assets/index/breadcrumb-map.json` | ~643 KB | Page ID → breadcrumb string |

---

## 5. Step 2 — Install dependencies

The server needs `mcp`. The client needs `mcp`, `python-dotenv`, and the
SDK for whichever provider you choose.

```bash
source .venv/bin/activate

pip install mcp python-dotenv         # always required

# Install ONE (or more) provider SDKs:
pip install groq                      # Groq  (free)
pip install anthropic                 # Claude
pip install google-generativeai       # Gemini (free)
pip install openai                    # OpenAI or any OpenAI-compatible endpoint
```

Verify:

```bash
python -c "import mcp; print('OK')"
# → OK
```

---

## 6. Step 3 — Set your API key

The client auto-detects which provider to use based on which key is set.

| Provider | Where to get a key | Environment variable | Free? |
|---|---|---|---|
| **Groq** (recommended) | https://console.groq.com → API Keys | `GROQ_API_KEY` | Yes |
| **Gemini** | https://aistudio.google.com/app/apikey | `GEMINI_API_KEY` | Yes |
| **Claude** | https://console.anthropic.com | `ANTHROPIC_API_KEY` | No (cheap) |
| **OpenAI** | https://platform.openai.com/api-keys | `OPENAI_API_KEY` | No |

### Recommended — `.env` file

The project ships a `.env.example` template. Copy it and fill in your key:

```bash
cp .env.example .env
```

Then open `.env` and set your key (leaving the others commented out):

```bash
# .env
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxx
```

The client loads `.env` automatically on startup. The file is listed in
`.gitignore` so your keys never end up in version control.

### Alternative — shell export

For one-off sessions or CI environments, export the variable directly:

```bash
export GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxx
```

> **Groq free tier**: ~14,400 requests/day, 500K tokens/minute on
> `llama-3.3-70b-versatile`. More than enough for documentation queries.
>
> **Gemini free tier**: 1,500 requests/day on `gemini-1.5-flash`.

---

## 7. Step 4 — Run the client

The client automatically starts the MCP server as a subprocess — you
don't need to launch the server separately.

Use `--provider` to pick a backend explicitly, or omit it to
auto-detect from whichever API key is set.

### Interactive mode (recommended for exploration)

```bash
python mcp_client/client.py                    # auto-detect provider
python mcp_client/client.py --provider groq    # explicit
python mcp_client/client.py --provider claude
python mcp_client/client.py --provider gemini
python mcp_client/client.py --provider openai
```

```
Connecting to Uniface docs MCP server…
Ready — 6 tools: search_docs, get_page, list_sections, browse_section, lookup_reference, get_toc_children

Uniface 10.4 Docs Assistant  (Ctrl-C or 'quit' to exit)
Type 'examples' to see sample questions.

You: ▌
```

Type any question in natural language. The client prints each tool call
as it happens so you can follow exactly what the model is looking up.

#### Built-in commands

| Input | Action |
|---|---|
| Any question | Run the agentic tool-calling loop and print the answer |
| `examples` | Print the 8 built-in example prompts |
| `quit` / `exit` / `q` | Exit |
| `Ctrl-C` | Exit |

---

### Demo mode (runs all 8 example prompts)

```bash
python mcp_client/client.py --demo
python mcp_client/client.py --provider gemini --demo
```

Good for a first run to see the system working end-to-end.

---

### Single-question mode

```bash
python mcp_client/client.py --prompt "What is a ProcScript trigger?"
python mcp_client/client.py --provider claude --prompt "Explain entity in Uniface."
```

Prints the answer and exits. Useful for scripting or quick lookups.

---

### Example session

```
You: What does trigger clear do in Uniface?

════════════════════════════════════════════════════════════════
  What does trigger clear do in Uniface?
════════════════════════════════════════════════════════════════

  ⚙  lookup_reference(name='trigger clear')
     ↩  Title: trigger clear | Path: Uniface Reference › Script Module Reference › Triggers…

The **trigger clear** in Uniface is an interactive trigger that reacts to
the user's request to start over with a clean form.

**Declaration:** `trigger clear`
**Applies to:** Form
**Activation:** Activated by the `^CLEAR` structure editor function.

**Default behavior:** None
**Behavior upon completion:** None

**Description:** The default ProcScript provided for this trigger drops all
data currently in the component — any data entered or retrieved is removed
from the component. This does not remove the data from the database itself.

Source: https://docs.rocketsoftware.com/de-DE/bundle/uniface_104/page/aag1665703130023.html
```

---

## 8. Step 5 — Wire into Claude Code (optional)

You can add the MCP server to **Claude Code** or **Claude Desktop** so
that Claude can query your Uniface docs during any conversation — no
client script needed.

### Claude Code (VS Code / CLI)

Add to `~/.claude/claude_desktop_config.json` (create it if absent):

```json
{
  "mcpServers": {
    "uniface-docs": {
      "command": "/absolute/path/to/uniface-docs/.venv/bin/python",
      "args": ["/absolute/path/to/uniface-docs/mcp_server/server.py"]
    }
  }
}
```

Replace `/absolute/path/to/uniface-docs` with the real path on your
machine (e.g. `/home/ahmed/Downloads/uniface-docs`).

Then restart Claude Code. You should see `uniface-docs` appear in the
MCP servers list. Claude can now call all 6 tools during any session.

### Verify the server registers correctly

```bash
# From the project root — should print tool names and exit cleanly
source .venv/bin/activate
python mcp_server/server.py --help 2>/dev/null || echo "server loaded OK"
```

---

## 9. Available tools

| Tool | Arguments | Description |
|---|---|---|
| `search_docs` | `query: str`, `limit: int = 10` | Ranked keyword search across all 4,990 pages. Scores by title (×10), breadcrumb path (×3), body text (×1). Returns up to `limit` results (max 50). |
| `get_page` | `page_id: str` | Full cleaned text of a single page. Use IDs returned by other tools. |
| `list_sections` | — | All 27 top-level sections with page counts. |
| `browse_section` | `section_name: str`, `offset: int = 0`, `limit: int = 30` | Paginated listing of pages within a section. Supports `offset` for large sections. |
| `lookup_reference` | `name: str` | Exact (case-insensitive) title match. Falls back to partial matches and lists candidates. Best for the 2,466 Uniface Reference pages. |
| `get_toc_children` | `page_id: str` | Direct children of a page in the TOC hierarchy. `⊕` means the child has further children; `·` means it is a leaf. |

### Tool decision guide

```
Looking for a named construct?       →  lookup_reference("trigger clear")
Exploring a topic area?              →  search_docs("database connection oracle")
Browsing what's in a section?        →  browse_section("DBMS Support")
Navigating the doc tree?             →  get_toc_children("<parent-id>")
Reading a full page?                 →  get_page("<page-id>")
Seeing what sections exist?          →  list_sections()
```

---

## 10. Example interactions

These are the 8 built-in demo prompts (run with `--demo` or type
`examples` in interactive mode):

```
1. List all the documentation sections and how many pages each has.

2. What does 'trigger clear' do in Uniface? Give me the full details.

3. How do I develop web applications with Uniface? Search for relevant pages.

4. What is a Derived Component Field?

5. Show me the top-level structure of the Uniface documentation tree.

6. I want to connect Uniface to an Oracle database. What should I read?

7. Look up the glossary entry for 'entity' in Uniface.

8. What ProcScript statements are available for working with files?
```

Additional prompts worth trying:

```
- "What triggers are available in a Uniface form?"
- "Explain the difference between a component and an entity in Uniface."
- "How does Uniface handle session management in web apps?"
- "What does the /e qualifier do on the clear statement?"
- "Browse the 'Installing Uniface' section and summarise what's covered."
- "What DBMS systems does Uniface 10.4 support?"
```

---

## 11. Troubleshooting

### `ModuleNotFoundError: No module named 'mcp'`

The `mcp` package is not installed in the active environment.

```bash
source .venv/bin/activate
pip install mcp python-dotenv groq
```

### `ERROR: GROQ_API_KEY is not set`

Either set it in your `.env` file (recommended):

```bash
# .env
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxx
```

Or export it for the current shell session:

```bash
export GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxx
```

If you have a `.env` file but the error persists, make sure `python-dotenv`
is installed (`pip install python-dotenv`) and that the key is not commented
out in the file.

### `Page '...' not found` from `get_page`

The `site/assets/pages/` directory is missing or incomplete.
Re-run the data builder:

```bash
cd scraper
python build_mcp_data.py
```

### `Section index not loaded` from `list_sections` or `browse_section`

Same cause — `site/assets/index/` is missing. Re-run `build_mcp_data.py`.

### Search returns zero results

- Check that `site/assets/search-meta.json` exists (built by `build_site_data.py`).
- Try shorter or simpler keywords — the search is keyword-based, not semantic.
- The model may refine the query automatically on a retry; ask again with different phrasing.

### Server fails to start when wired into Claude Code

Make sure the `command` path points to the **venv Python**, not the system
Python — the venv Python is the one with `mcp` installed:

```bash
# Find the correct path
source .venv/bin/activate
which python
# → /home/ahmed/Downloads/uniface-docs/.venv/bin/python
```

Use that full path in `claude_desktop_config.json`.

### Rate limit errors (`429`)

Free tiers have per-minute limits. Wait 60 seconds and retry, or switch
to the lighter model via an env var:

```bash
# Groq — switch to the faster small model
export GROQ_MODEL=llama-3.1-8b-instant

# Gemini — already using the fastest free model (gemini-1.5-flash)
# Claude — switch to Haiku (cheapest)
export CLAUDE_MODEL=claude-haiku-4-5-20251001

# OpenAI — switch to a cheaper model
export OPENAI_MODEL=gpt-4o-mini
```

### Using an OpenAI-compatible endpoint (Ollama, Together, etc.)

```bash
export OPENAI_API_KEY=unused          # some endpoints accept any string
export OPENAI_BASE_URL=http://localhost:11434/v1   # e.g. Ollama
export OPENAI_MODEL=llama3.2
python mcp_client/client.py --provider openai
```

### Auto-detect picked the wrong provider

If you have multiple keys set, the client picks the first one found
(Groq → Claude → Gemini → OpenAI). Override with `--provider`.

---

## Updating after a fresh scrape

When you re-scrape the documentation, rebuild both the SPA assets and the
MCP data:

```bash
cd scraper
python build_site_data.py --in data --out ../site/assets   # SPA
python build_mcp_data.py                                    # MCP
```

The MCP server picks up the new files automatically on next startup — no
code changes needed.
