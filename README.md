# ContentMatrix OS

AI-driven content generator that consumes a Topical Map + Content Brief
(produced by `topical-map-engine-pro`) and produces full SEO-optimized articles.

**Approved model set:** `gemini-2.0-flash` (bulk drafting) + `claude-sonnet-4-6`
(quality refinement). The hybrid keeps cost low while preserving editorial polish.

## Architecture

```
Topical Map + Brief (input)
    -> Outline Builder (Gemini Flash)
    -> Section Writer  (Gemini Flash, chunk-by-chunk)
    -> Quality Scorer  (NeuronWriter-style)
    -> Refiner         (Claude Sonnet, score-gated)
    -> Exporter        (.md / .docx / .html)
```

## Stack

- **Streamlit** — UI (same pattern as topical-map-engine)
- **Pydantic** — type-safe data models
- **Anthropic Claude** — quality-critical reasoning (refinement, QA)
- **Google Gemini Flash** — bulk drafting (cost saving)
- **Serper.dev** — live SERP enrichment (1000 free / month)
- **SQLite / Turso** — response cache (cuts repeat API cost)
- **spaCy + KeyBERT** — local NLP (term extraction)

## Quick Start

```bash
# 1. Setup
pip install -r requirements.txt
cp .env.example .env   # add your API keys

# 2. Validate models
python validate_models.py

# 3. Run locally
streamlit run app.py
```

## Deploy

Same pattern as existing engines — push to GitHub, connect Streamlit Cloud,
add secrets in Streamlit Cloud settings.

## File Layout

| Path | Purpose |
|------|---------|
| `content_models.py` | Pydantic schemas (input, output, cache, session) |
| `pipeline.py` | Top-level orchestrator |
| `stages/` | Business logic — one module per stage |
| `ui/` | Streamlit page modules |
| `prompts/` | External prompt files (editable without code changes) |
| `templates/` | Jinja2 article templates |
| `cache/` | SQLite cache store (gitignored) |
| `sessions/` | Generated articles (gitignored) |

## Input Compatibility

Accepts output from `topical-map-engine-pro`:
- `topical_map.json` -> `TopicalMapRef`
- `all_briefs.json` -> per-page `brief_payload` dict

See `example_input.json` for the full shape.
