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

### Eval file format

Each `eval/results_*.jsonl` file may or may not have a metadata line. If the first line contains `_type: "metadata"`, it is the run's metadata record; all remaining lines are per-question result records. If no line has `_type: "metadata"` (older files), treat metadata as absent and use the filename timestamp as the run identifier.

---

## Pages

### Overview (`/dashboard`)
- 4 stat cards: Documents, Chunks, Recall@5 (latest run), Faithfulness (latest run)
- Bar chart: Recall across all runs (x = run timestamp label, y = recall)
- Latest run info card: timestamp, git SHA, question count, rerank_top_k, judge errors

### Corpus (`/dashboard/corpus`)
- Stat cards: total documents, total chunks, avg chunks per document
- Bar chart: chunk size distribution, bucketed into fixed ranges: 0–99, 100–199, 200–299, 300–399, 400–499, 500+ tokens (using `chunks.token_count`)

### Eval (`/dashboard/eval`)
- Trend chart: recall and faithfulness over all runs (dual-axis line chart, x = run timestamp label)
- Summary table: one row per run — timestamp, git SHA, questions, recall, faithfulness, judge errors
- Run comparison: two dropdowns (Run A, Run B); selecting either fires a fetch to `/dashboard/api/eval/{timestamp}` and renders a side-by-side table highlighting rows where the runs differ (hit vs miss, faithfulness score difference ≥ 1)

### Pipeline Config (`/dashboard/pipeline`)
- Reads metadata from the latest eval run
- Displays: `rerank_top_k`, judge model (`metadata["models"]["judge"]`), question set path, git SHA
- Static display only — no editing

### Query Explorer (`/dashboard/explorer`)
- Text input + submit button
- JS POSTs `{"query": "..."}` to `/query`
- Renders: generated answer and citation list (`citations[].foi_reference`, `citations[].title`, `citations[].page_number`)
- Note: `CitationItem` has no content field — chunk text is not displayed in this view

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
| `pyproject.toml` | Modify | Add `jinja2` to dependencies; add `pytest-asyncio` to dev dependencies |
| `tests/test_dashboard_utils.py` | Create | Unit tests for pure functions in `dashboard_utils.py` |

---

## `dashboard_utils.py` — Pure Functions

```python
def read_eval_runs(eval_dir: Path) -> list[dict]:
    """Return list of parsed runs sorted newest first.

    Callers are responsible for resolving eval_dir. Recommended:
        Path(__file__).parent.parent.parent / "eval"
    Each entry is the return value of parse_run_file().
    Sorted newest-first by lexicographic order on the timestamp string
    (format YYYY-MM-DDTHH-MM-SS, so lexicographic == chronological).
    """

def parse_run_file(path: Path) -> dict:
    """Parse a single results JSONL file.

    Returns:
        {
            "timestamp": str,        # from metadata["timestamp"] or filename stem
            "metadata": dict | None, # None if no _type: metadata line found
            "records": list[dict],   # per-question result dicts
            "summary": dict,         # from eval_utils.summarise_results(records)
        }

    If the first line has _type: "metadata", it is the metadata record and all
    remaining lines are result records. If no _type: "metadata" line is present,
    metadata is None and all lines are treated as result records.
    Empty files return metadata=None, records=[], summary with all zeros.
    Imports summarise_results from scripts.eval_utils.
    """

async def get_corpus_stats(pool) -> dict:
    """Query DB for corpus statistics.

    Returns:
        {
            "doc_count": int,
            "chunk_count": int,
            "avg_chunks_per_doc": float,
            "chunk_size_distribution": {
                "0-99": int, "100-199": int, "200-299": int,
                "300-399": int, "400-499": int, "500+": int
            }
        }
    Uses app.state.pool passed by the route handler. DB-dependent — not unit tested.
    """
```

`dashboard_utils.py` imports `summarise_results` from `scripts.eval_utils`. Because `dashboard_utils.py` is imported as part of the running server (not executed directly), the project root is not automatically on `sys.path`. The module must insert it explicitly at the top:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.eval_utils import summarise_results
```

---

## Eval Run Comparison — JSON Endpoint

`GET /dashboard/api/eval/{timestamp}` where `{timestamp}` is the value of the `metadata.timestamp` field verbatim (e.g. `2026-03-21T09-32-29` — hyphens, not colons). Matches against `parse_run_file().timestamp` for each file.

Returns 200 JSON:

```json
{
  "metadata": { "git_sha": "...", "rerank_top_k": 5, ... },
  "summary": { "total": 50, "recall": 0.96, "mean_faithfulness": 4.9, "judge_errors": 1 },
  "records": [ { "question": "...", "retrieval_hit": true, "faithfulness_score": 5, ... } ]
}
```

Returns `404 {"detail": "Run not found"}` if no file matches the timestamp.

---

## Dependencies

- `jinja2` — add to `pyproject.toml` dependencies (not currently listed; FastAPI's optional install is not reliable)
- `pytest-asyncio` — add to `pyproject.toml` dev dependencies (needed if any async tests are written; `get_corpus_stats` tests are skipped with `pytest.mark.skip` so this is precautionary)
- `Chart.js` — CDN in `base.html`, no install needed

---

## Testing

`tests/test_dashboard_utils.py` covers `read_eval_runs()` and `parse_run_file()` with fixture JSONL files:

- Valid file with metadata line
- Valid file without metadata line (older format)
- File where first line lacks `_type: metadata` but contains a result record
- Empty file
- `read_eval_runs()` with a directory of mixed files, confirms sort order

`get_corpus_stats()` is async and DB-dependent — all tests for it are skipped with `pytest.mark.skip`.

---

## What Is Not In Scope

- Authentication / access control (public read-only)
- Editing pipeline config from the dashboard
- Faithfulness scoring in the Query Explorer
- Chunk text content in the Query Explorer (not available in `CitationItem`)
- Pagination of the per-question results table (add later if needed)
