# Dashboard Design Spec

**Date:** 2026-03-21
**Goal:** Add a publicly-accessible web dashboard to the existing FastAPI app that visualises the full FOI RAG system — corpus health, eval results, pipeline config, and a live query explorer.

---

## Approach

Server-rendered HTML via Jinja2Templates, served directly from the existing FastAPI app under `/dashboard`. A shared base template provides the sidebar nav. Each section is a separate route and template. Chart.js (CDN) handles charts. A single JSON endpoint supports the eval run-comparison feature. The Query Explorer section calls the existing `/query` endpoint via JS fetch.

No new services, no build step, no frontend framework.

---

## Architecture

```
GET /dashboard              → overview.html
GET /dashboard/corpus       → corpus.html
GET /dashboard/eval         → eval.html
GET /dashboard/pipeline     → pipeline.html
GET /dashboard/explorer     → explorer.html
GET /dashboard/api/eval/{timestamp}  → JSON (run comparison)
```

Jinja2Templates is mounted in `src/api/main.py` pointing at `src/api/templates/`. The dashboard router is registered alongside the existing routers.

---

## Data Sources

| Page | Source |
|---|---|
| Overview | DB (doc/chunk counts) + latest `eval/results_*.jsonl` |
| Corpus | DB — `documents` and `chunks` tables |
| Eval | All `eval/results_*.jsonl` files, sorted by timestamp |
| Pipeline | Metadata line (`_type: metadata`) of latest eval JSONL |
| Explorer | JS POSTs to existing `/query` endpoint |

Eval files are read from `eval/` relative to the project root. Each file's first line is a metadata record (`_type: metadata`); remaining lines are per-question result records.

---

## Pages

### Overview (`/dashboard`)
- 4 stat cards: Documents, Chunks, Recall@5 (latest run), Faithfulness (latest run)
- Bar chart: Recall across all runs (x = timestamp, y = recall)
- Latest run info card: timestamp, git SHA, question count, rerank_top_k, judge errors

### Corpus (`/dashboard/corpus`)
- Stat cards: total documents, total chunks, avg chunks per document
- Bar chart: chunk count distribution (bucketed by chunk size in tokens)
- Table or chart: documents by ingestion date (if date metadata available)

### Eval (`/dashboard/eval`)
- Run selector: dropdown of all result files, sorted newest first
- Trend chart: recall and faithfulness over all runs (dual-axis line chart)
- Run comparison: two dropdowns (Run A, Run B); selecting either fires a fetch to `/dashboard/api/eval/{timestamp}` and renders a side-by-side table of per-question results (hit/miss, faithfulness score, question text)
- Summary table: one row per run — timestamp, git SHA, questions, recall, faithfulness, judge errors

### Pipeline Config (`/dashboard/pipeline`)
- Reads metadata from the latest eval run
- Displays: `rerank_top_k`, judge model, question set path, git SHA
- Static display only — no editing

### Query Explorer (`/dashboard/explorer`)
- Text input + submit button
- JS POSTs `{"query": "..."}` to `/query`
- Renders: generated answer, retrieved chunks (FOI reference, title, page, content snippet), faithfulness is not scored here

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `src/api/routes/dashboard.py` | Create | 5 page routes + `/dashboard/api/eval/{timestamp}` JSON endpoint |
| `src/api/dashboard_utils.py` | Create | Pure functions: `read_eval_runs()`, `parse_run_file()`, `get_corpus_stats()` |
| `src/api/templates/dashboard/base.html` | Create | Sidebar layout, Chart.js CDN, shared CSS |
| `src/api/templates/dashboard/overview.html` | Create | Extends base |
| `src/api/templates/dashboard/corpus.html` | Create | Extends base |
| `src/api/templates/dashboard/eval.html` | Create | Extends base; JS for run comparison fetch |
| `src/api/templates/dashboard/pipeline.html` | Create | Extends base |
| `src/api/templates/dashboard/explorer.html` | Create | Extends base; JS for `/query` fetch |
| `src/api/main.py` | Modify | Mount Jinja2Templates, include dashboard router |
| `pyproject.toml` | Modify | Add `jinja2` dependency |
| `tests/test_dashboard_utils.py` | Create | Unit tests for all pure functions in `dashboard_utils.py` |

---

## `dashboard_utils.py` — Pure Functions

```python
def read_eval_runs(eval_dir: Path) -> list[dict]:
    """Return list of run summaries (metadata + computed summary) sorted newest first."""

def parse_run_file(path: Path) -> dict:
    """Parse a single results JSONL. Returns {metadata, records, summary}."""

async def get_corpus_stats(pool) -> dict:
    """Query DB for doc count, chunk count, avg chunks/doc, chunk size distribution."""
```

All functions are pure/async-safe and unit-testable without a running server.

---

## Eval Run Comparison

`GET /dashboard/api/eval/{timestamp}` returns JSON:

```json
{
  "metadata": { "git_sha": "...", "rerank_top_k": 5, ... },
  "summary": { "total": 50, "recall": 0.96, "mean_faithfulness": 4.9, "judge_errors": 1 },
  "records": [ { "question": "...", "retrieval_hit": true, "faithfulness_score": 5, ... } ]
}
```

The Eval page JS fetches this for Run A and Run B and renders a side-by-side table highlighting rows where the two runs differ (hit vs miss, score difference).

---

## Dependencies

- `jinja2` — add to `pyproject.toml` (not currently installed)
- `Chart.js` — loaded via CDN in `base.html`, no install needed

---

## Testing

`tests/test_dashboard_utils.py` covers:
- `read_eval_runs()` with a directory of fixture JSONL files
- `parse_run_file()` with valid and malformed files (missing metadata line, empty file)
- `get_corpus_stats()` is async/DB-dependent — integration test or skip in unit suite

No template rendering tests — Jinja2 templates are tested implicitly via the running app.

---

## What Is Not In Scope

- Authentication / access control (public read-only)
- Editing pipeline config from the dashboard
- Scoring faithfulness in the Query Explorer
- Pagination of the per-question results table (can add later if >100 questions)
