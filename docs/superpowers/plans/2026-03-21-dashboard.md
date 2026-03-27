# Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a publicly-accessible Jinja2-rendered dashboard at `/dashboard` to the existing FastAPI app, visualising corpus health, eval results, pipeline config, and a live query explorer.

**Architecture:** Jinja2Templates serves HTML from `src/api/templates/dashboard/`. A shared `base.html` provides the dark-themed sidebar nav; each page extends it. Data comes from the asyncpg pool (corpus stats) and `eval/results_*.jsonl` files (eval results). Chart.js via CDN handles charts. A JSON endpoint at `/dashboard/api/eval/{timestamp}` powers run comparison in the Eval page. The Query Explorer calls the existing `/query` endpoint via JS fetch.

**Tech Stack:** Python 3.13, FastAPI, Jinja2, asyncpg, Chart.js (CDN), pytest.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `pyproject.toml` | Modify | Add `jinja2` to deps; `pytest-asyncio` to dev deps |
| `src/api/routes/dashboard.py` | Create | All dashboard routes (5 pages + JSON comparison endpoint) |
| `src/api/dashboard_utils.py` | Create | Pure/async data functions: `parse_run_file`, `read_eval_runs`, `get_corpus_stats` |
| `src/api/templates/dashboard/base.html` | Create | Sidebar layout, Chart.js CDN, shared dark-theme CSS |
| `src/api/templates/dashboard/overview.html` | Create | Stat cards + recall bar chart |
| `src/api/templates/dashboard/corpus.html` | Create | Chunk distribution bar chart |
| `src/api/templates/dashboard/eval.html` | Create | Trend chart + run comparison JS |
| `src/api/templates/dashboard/pipeline.html` | Create | Static config display |
| `src/api/templates/dashboard/explorer.html` | Create | Live query box with JS fetch |
| `src/api/main.py` | Modify | Include dashboard router |
| `tests/fixtures/eval/results_2026-01-01T10-00-00.jsonl` | Create | Test fixture: file with metadata |
| `tests/fixtures/eval/results_2026-01-02T10-00-00.jsonl` | Create | Test fixture: file without metadata |
| `tests/fixtures/eval/results_2026-01-03T10-00-00.jsonl` | Create | Test fixture: empty file |
| `tests/test_dashboard_utils.py` | Create | Unit tests for `parse_run_file` and `read_eval_runs` |
| `docs/dashboard.md` | Create | User-facing dashboard documentation |
| `README.md` | Modify | Add Dashboard section linking to `docs/dashboard.md` |

---

## Task 1: Add dependencies and wire Jinja2 into the app

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/api/main.py`
- Create: `src/api/routes/dashboard.py` (stub)
- Create: `src/api/templates/dashboard/.gitkeep`

- [ ] **Step 1: Add dependencies to `pyproject.toml`**

```toml
dependencies = [
    "fastapi",
    "uvicorn[standard]",
    "asyncpg",
    "openai",
    "anthropic",
    "pymupdf",
    "tiktoken",
    "python-dotenv",
    "pandas",
    "requests",
    "jinja2",
]

[dependency-groups]
dev = [
    "pytest>=9.0.2",
    "pytest-asyncio",
]
```

- [ ] **Step 2: Install dependencies**

```bash
uv sync
```

Expected: no errors.

- [ ] **Step 3: Create the templates directory**

```bash
mkdir -p src/api/templates/dashboard && touch src/api/templates/dashboard/.gitkeep
```

- [ ] **Step 4: Create stub `src/api/routes/dashboard.py`**

```python
from pathlib import Path

import asyncpg
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from src.api.dashboard_utils import get_corpus_stats, parse_run_file, read_eval_runs

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

EVAL_DIR = Path(__file__).parent.parent.parent.parent / "eval"


@router.get("/health")
async def dashboard_health():
    """Stub health check — confirms dashboard router is wired up."""
    return {"status": "ok"}
```

- [ ] **Step 5: Register the dashboard router in `src/api/main.py`**

Add the import and `include_router` call:

```python
from src.api.routes import documents, ingest, query, dashboard

# after the existing include_router calls:
app.include_router(dashboard.router)
```

- [ ] **Step 6: Verify the app starts and the stub route responds**

```bash
uv run uvicorn src.api.main:app --reload &
sleep 2
curl -s http://localhost:8000/dashboard/health
```

Expected: `{"status":"ok"}`

Kill the server with `kill %1` (or Ctrl+C if foreground).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/api/main.py src/api/routes/dashboard.py src/api/templates/
git commit -m "feat: wire Jinja2 and dashboard router into FastAPI app"
```

---

## Task 2: `dashboard_utils.py` — pure functions (TDD)

Implements `parse_run_file` and `read_eval_runs`. These are the only testable functions (no DB needed).

**Files:**
- Create: `tests/fixtures/eval/results_2026-01-01T10-00-00.jsonl`
- Create: `tests/fixtures/eval/results_2026-01-02T10-00-00.jsonl`
- Create: `tests/fixtures/eval/results_2026-01-03T10-00-00.jsonl`
- Create: `tests/test_dashboard_utils.py`
- Create: `src/api/dashboard_utils.py`

- [ ] **Step 1: Create test fixture files**

`tests/fixtures/eval/results_2026-01-01T10-00-00.jsonl` — file **with** metadata line:

```jsonl
{"_type": "metadata", "timestamp": "2026-01-01T10-00-00", "git_sha": "abc123", "rerank_top_k": 5, "question_set": "eval/question_set.json", "models": {"judge": "claude-haiku-4-5-20251001"}}
{"question": "What is Camden's policy?", "expected_foi": "CAM001", "retrieved_fois": ["CAM001"], "retrieval_hit": true, "answer": "Camden has a policy.", "faithfulness_score": 4, "faithfulness_reason": "Supported.", "retrieved_chunks": []}
{"question": "How many staff?", "expected_foi": "CAM002", "retrieved_fois": ["CAM003"], "retrieval_hit": false, "answer": "Unknown.", "faithfulness_score": 3, "faithfulness_reason": "Partial.", "retrieved_chunks": []}
```

`tests/fixtures/eval/results_2026-01-02T10-00-00.jsonl` — file **without** metadata (older format, first line is a result record):

```jsonl
{"question": "What enforcement action?", "expected_foi": "CAM003", "retrieved_fois": ["CAM003"], "retrieval_hit": true, "answer": "Action taken.", "faithfulness_score": 5, "faithfulness_reason": "Supported.", "retrieved_chunks": []}
```

`tests/fixtures/eval/results_2026-01-03T10-00-00.jsonl` — **empty** file:

(create an empty file)

```bash
touch tests/fixtures/eval/results_2026-01-03T10-00-00.jsonl
```

- [ ] **Step 2: Write `tests/test_dashboard_utils.py`**

```python
import pytest
from pathlib import Path

from src.api.dashboard_utils import parse_run_file, read_eval_runs

FIXTURES = Path(__file__).parent / "fixtures" / "eval"


# --- parse_run_file ---

def test_parse_run_file_with_metadata():
    run = parse_run_file(FIXTURES / "results_2026-01-01T10-00-00.jsonl")
    assert run["timestamp"] == "2026-01-01T10-00-00"
    assert run["metadata"]["git_sha"] == "abc123"
    assert run["metadata"]["rerank_top_k"] == 5
    assert len(run["records"]) == 2
    assert run["summary"]["total"] == 2
    assert run["summary"]["recall"] == 0.5
    assert run["summary"]["mean_faithfulness"] == 3.5


def test_parse_run_file_without_metadata():
    """First line is a result record — older format. metadata should be None."""
    run = parse_run_file(FIXTURES / "results_2026-01-02T10-00-00.jsonl")
    assert run["timestamp"] == "2026-01-02T10-00-00"
    assert run["metadata"] is None
    assert len(run["records"]) == 1
    assert run["summary"]["recall"] == 1.0


def test_parse_run_file_empty():
    run = parse_run_file(FIXTURES / "results_2026-01-03T10-00-00.jsonl")
    assert run["metadata"] is None
    assert run["records"] == []
    assert run["summary"]["total"] == 0
    assert run["summary"]["recall"] == 0.0


def test_parse_run_file_timestamp_from_filename_when_no_metadata():
    run = parse_run_file(FIXTURES / "results_2026-01-02T10-00-00.jsonl")
    assert run["timestamp"] == "2026-01-02T10-00-00"


# --- read_eval_runs ---

def test_read_eval_runs_returns_all_files():
    runs = read_eval_runs(FIXTURES)
    assert len(runs) == 3


def test_read_eval_runs_sorted_newest_first():
    runs = read_eval_runs(FIXTURES)
    timestamps = [r["timestamp"] for r in runs]
    assert timestamps == sorted(timestamps, reverse=True)
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/test_dashboard_utils.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` — `dashboard_utils` doesn't exist yet.

- [ ] **Step 4: Create `src/api/dashboard_utils.py`**

```python
import json
import sys
from pathlib import Path

import asyncpg

# Project root must be on sys.path for the scripts package to be importable.
# dashboard_utils is loaded as part of the server process, not run directly,
# so the project root is not automatically on sys.path.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.eval_utils import summarise_results


def parse_run_file(path: Path) -> dict:
    """Parse a single eval results JSONL file.

    Returns a dict with keys:
        timestamp (str): from metadata["timestamp"] or derived from filename stem.
        metadata (dict | None): the _type: metadata record, or None if absent.
        records (list[dict]): per-question result dicts.
        summary (dict): recall, mean_faithfulness, etc. via summarise_results().

    If the first line has _type: "metadata", it is consumed as the metadata record
    and all remaining lines are result records. Otherwise metadata is None and all
    lines are treated as result records. Empty files return zeros.
    """
    text = path.read_text().strip()
    filename_timestamp = path.stem.removeprefix("results_")

    if not text:
        return {
            "timestamp": filename_timestamp,
            "metadata": None,
            "records": [],
            "summary": summarise_results([]),
        }

    lines = text.splitlines()
    first = json.loads(lines[0])

    if first.get("_type") == "metadata":
        metadata = first
        timestamp = metadata.get("timestamp", filename_timestamp)
        record_lines = lines[1:]
    else:
        metadata = None
        timestamp = filename_timestamp
        record_lines = lines

    records = [json.loads(line) for line in record_lines if line.strip()]

    return {
        "timestamp": timestamp,
        "metadata": metadata,
        "records": records,
        "summary": summarise_results(records),
    }


def read_eval_runs(eval_dir: Path) -> list[dict]:
    """Return all eval runs from eval_dir, sorted newest-first.

    Sorts by lexicographic order on timestamp string (YYYY-MM-DDTHH-MM-SS),
    which is equivalent to chronological order for this format.

    Recommended eval_dir resolution from a route handler:
        Path(__file__).parent.parent.parent.parent / "eval"
    """
    files = sorted(eval_dir.glob("results_*.jsonl"), reverse=True)
    return [parse_run_file(f) for f in files]


async def get_corpus_stats(pool: asyncpg.Pool) -> dict:
    """Query the database for corpus statistics.

    Returns:
        doc_count (int): total number of ingested documents.
        chunk_count (int): total number of chunks.
        avg_chunks_per_doc (float): average chunks per document, rounded to 1dp.
        chunk_size_distribution (dict): chunk counts per token_count bucket.
            Buckets: "0-99", "100-199", "200-299", "300-399", "400-499", "500+".
            Only chunks with non-null token_count are included.

    Not unit tested (DB-dependent). Called by Overview and Corpus route handlers
    which pass request.app.state.pool.
    """
    async with pool.acquire() as conn:
        doc_count = await conn.fetchval("SELECT COUNT(*) FROM documents")
        chunk_count = await conn.fetchval("SELECT COUNT(*) FROM chunks")
        avg_chunks = await conn.fetchval("""
            SELECT ROUND(AVG(cnt)::numeric, 1)
            FROM (SELECT COUNT(*) AS cnt FROM chunks GROUP BY document_id) sub
        """)
        rows = await conn.fetch("""
            SELECT
                CASE
                    WHEN token_count < 100 THEN '0-99'
                    WHEN token_count < 200 THEN '100-199'
                    WHEN token_count < 300 THEN '200-299'
                    WHEN token_count < 400 THEN '300-399'
                    WHEN token_count < 500 THEN '400-499'
                    ELSE '500+'
                END AS bucket,
                COUNT(*) AS count
            FROM chunks
            WHERE token_count IS NOT NULL
            GROUP BY bucket
            ORDER BY MIN(token_count)
        """)

    buckets = {"0-99": 0, "100-199": 0, "200-299": 0, "300-399": 0, "400-499": 0, "500+": 0}
    for row in rows:
        buckets[row["bucket"]] = row["count"]

    return {
        "doc_count": doc_count,
        "chunk_count": chunk_count,
        "avg_chunks_per_doc": float(avg_chunks or 0),
        "chunk_size_distribution": buckets,
    }
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_dashboard_utils.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 6: Run the full test suite to confirm nothing broken**

```bash
uv run pytest -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/api/dashboard_utils.py tests/test_dashboard_utils.py tests/fixtures/
git commit -m "feat: add dashboard_utils with parse_run_file and read_eval_runs (TDD)"
```

---

## Task 3: Base template

The shared layout all pages extend. Defines the sidebar, dark theme CSS, Chart.js CDN, and a `{% block content %}` for page-specific HTML.

**Files:**
- Create: `src/api/templates/dashboard/base.html`

- [ ] **Step 1: Create `src/api/templates/dashboard/base.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}FOI RAG Dashboard{% endblock %}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        :root {
            --bg: #1e2030; --sidebar: #181825; --surface: #181825;
            --border: #313244; --text: #cdd6f4; --subtle: #6c7086;
            --blue: #89b4fa; --green: #a6e3a1; --yellow: #f9e2af;
            --purple: #cba6f7; --red: #f38ba8;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: system-ui, sans-serif; background: var(--bg); color: var(--text); display: flex; height: 100vh; overflow: hidden; }

        /* Sidebar */
        .sidebar { width: 180px; background: var(--sidebar); border-right: 1px solid var(--border); padding: 20px 12px; flex-shrink: 0; }
        .sidebar-brand { color: var(--blue); font-weight: bold; font-size: 15px; margin-bottom: 4px; }
        .sidebar-sub { color: var(--subtle); font-size: 11px; margin-bottom: 24px; }
        .nav-label { color: var(--subtle); font-size: 10px; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 8px; }
        .nav-link { display: block; padding: 7px 10px; border-radius: 5px; color: var(--subtle); text-decoration: none; font-size: 13px; margin-bottom: 2px; }
        .nav-link:hover { color: var(--text); background: var(--bg); }
        .nav-link.active { color: var(--green); background: var(--bg); }

        /* Main content area */
        .main { flex: 1; overflow-y: auto; padding: 28px 32px; }
        .page-title { font-size: 20px; font-weight: bold; margin-bottom: 4px; }
        .page-sub { color: var(--subtle); font-size: 13px; margin-bottom: 24px; }

        /* Stat cards */
        .stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 24px; }
        .stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
        .stat-label { color: var(--subtle); font-size: 10px; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 8px; }
        .stat-value { font-size: 26px; font-weight: bold; }

        /* Chart / info cards */
        .chart-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 16px; }
        .chart-title { color: var(--subtle); font-size: 10px; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 12px; }
        .info-row { font-size: 13px; margin-bottom: 4px; }
        .info-subtle { color: var(--subtle); font-size: 12px; margin-bottom: 4px; }

        /* Table */
        .table-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; margin-bottom: 16px; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th { color: var(--subtle); font-size: 10px; letter-spacing: 1px; text-transform: uppercase; padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--border); }
        td { padding: 10px 14px; border-bottom: 1px solid var(--border); }
        tr:last-child td { border-bottom: none; }
        .hit { color: var(--green); font-weight: bold; }
        .miss { color: var(--red); font-weight: bold; }
        .diff { background: rgba(249, 226, 175, 0.08); }

        /* Layout helpers */
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }

        /* Forms */
        .form-group { margin-bottom: 16px; }
        textarea, input[type=text], select {
            background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
            color: var(--text); padding: 10px 12px; font-size: 14px; font-family: inherit;
        }
        textarea { width: 100%; resize: vertical; }
        select { padding: 7px 10px; font-size: 13px; }
        button { background: var(--blue); color: #1e2030; border: none; border-radius: 6px; padding: 9px 20px; font-size: 14px; font-weight: bold; cursor: pointer; }
        button:hover { opacity: 0.9; }

        /* Explorer */
        .answer-box { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 16px; line-height: 1.6; white-space: pre-wrap; }
        .citation-list { list-style: none; }
        .citation-list li { padding: 8px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
        .citation-list li:last-child { border-bottom: none; }
        .citation-ref { color: var(--blue); font-weight: bold; margin-right: 8px; }
    </style>
</head>
<body>
    <nav class="sidebar">
        <div class="sidebar-brand">FOI RAG</div>
        <div class="sidebar-sub">Dashboard</div>
        <div class="nav-label">Navigation</div>
        <a href="/dashboard" class="nav-link {% if active == 'overview' %}active{% endif %}">Overview</a>
        <a href="/dashboard/corpus" class="nav-link {% if active == 'corpus' %}active{% endif %}">Corpus</a>
        <a href="/dashboard/eval" class="nav-link {% if active == 'eval' %}active{% endif %}">Eval</a>
        <a href="/dashboard/pipeline" class="nav-link {% if active == 'pipeline' %}active{% endif %}">Pipeline</a>
        <a href="/dashboard/explorer" class="nav-link {% if active == 'explorer' %}active{% endif %}">Explorer</a>
    </nav>
    <main class="main">
        {% block content %}{% endblock %}
    </main>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add src/api/templates/dashboard/base.html
git commit -m "feat: add dashboard base template with sidebar and dark theme"
```

---

## Task 4: Overview page

**Files:**
- Modify: `src/api/routes/dashboard.py`
- Create: `src/api/templates/dashboard/overview.html`

- [ ] **Step 1: Add the overview route to `dashboard.py`**

Replace the stub health route with real routes. Start with overview:

```python
@router.get("")
@router.get("/")
async def overview(request: Request):
    """Overview page: corpus health + latest eval metrics + recall trend."""
    pool: asyncpg.Pool = request.app.state.pool
    corpus = await get_corpus_stats(pool)
    runs = read_eval_runs(EVAL_DIR)
    latest = runs[0] if runs else None
    return templates.TemplateResponse("dashboard/overview.html", {
        "request": request,
        "active": "overview",
        "corpus": corpus,
        "runs": runs,
        "latest": latest,
    })
```

- [ ] **Step 2: Create `src/api/templates/dashboard/overview.html`**

```html
{% extends "dashboard/base.html" %}
{% block title %}Overview — FOI RAG{% endblock %}
{% block content %}
<div class="page-title">Overview</div>
<div class="page-sub">System health at a glance</div>

<div class="stat-grid">
    <div class="stat-card">
        <div class="stat-label">Documents</div>
        <div class="stat-value" style="color: var(--blue)">{{ corpus.doc_count }}</div>
    </div>
    <div class="stat-card">
        <div class="stat-label">Chunks</div>
        <div class="stat-value" style="color: var(--purple)">{{ corpus.chunk_count }}</div>
    </div>
    {% if latest %}
    <div class="stat-card">
        <div class="stat-label">Recall@5</div>
        <div class="stat-value" style="color: var(--green)">{{ "%.0f"|format(latest.summary.recall * 100) }}%</div>
    </div>
    <div class="stat-card">
        <div class="stat-label">Faithfulness</div>
        <div class="stat-value" style="color: var(--yellow)">{{ "%.1f"|format(latest.summary.mean_faithfulness) }}/5</div>
    </div>
    {% else %}
    <div class="stat-card">
        <div class="stat-label">Recall@5</div>
        <div class="stat-value" style="color: var(--subtle)">—</div>
    </div>
    <div class="stat-card">
        <div class="stat-label">Faithfulness</div>
        <div class="stat-value" style="color: var(--subtle)">—</div>
    </div>
    {% endif %}
</div>

{% if runs %}
<div class="grid-2">
    <div class="chart-card">
        <div class="chart-title">Recall@5 across runs</div>
        <canvas id="recallChart" height="140"></canvas>
    </div>
    {% if latest %}
    <div class="chart-card">
        <div class="chart-title">Latest run</div>
        <div class="info-row">{{ latest.timestamp }}</div>
        {% if latest.metadata %}
        <div class="info-subtle">git: {{ latest.metadata.git_sha }}</div>
        <div class="info-subtle">{{ latest.summary.total }} questions · rerank_top_k: {{ latest.metadata.rerank_top_k }}</div>
        {% endif %}
        {% if latest.summary.judge_errors %}
        <div class="info-subtle" style="color: var(--yellow)">{{ latest.summary.judge_errors }} judge error(s) excluded from mean</div>
        {% endif %}
    </div>
    {% endif %}
</div>

<script>
// Runs are newest-first; reverse so chart reads left=oldest, right=newest
const runs = {{ runs | tojson }};
const labels = runs.map(r => r.timestamp).reverse();
const recalls = runs.map(r => r.summary.recall).reverse();
new Chart(document.getElementById('recallChart'), {
    type: 'bar',
    data: {
        labels,
        datasets: [{
            label: 'Recall@5',
            data: recalls,
            backgroundColor: '#89b4fa55',
            borderColor: '#89b4fa',
            borderWidth: 1,
        }]
    },
    options: {
        plugins: { legend: { display: false } },
        scales: {
            y: { min: 0, max: 1, ticks: { color: '#6c7086', format: { style: 'percent' } }, grid: { color: '#313244' } },
            x: { ticks: { color: '#6c7086', maxRotation: 20 }, grid: { color: '#313244' } }
        }
    }
});
</script>
{% else %}
<div class="chart-card">
    <div class="info-subtle">No eval runs found in <code>eval/</code>. Run <code>make eval</code> to generate results.</div>
</div>
{% endif %}
{% endblock %}
```

- [ ] **Step 3: Manually verify**

Start the app and open `http://localhost:8000/dashboard` in a browser. Confirm:
- 4 stat cards are visible with real values
- Sidebar links are present, Overview is highlighted
- Recall chart renders (if eval runs exist)

```bash
uv run uvicorn src.api.main:app --reload
```

- [ ] **Step 4: Commit**

```bash
git add src/api/routes/dashboard.py src/api/templates/dashboard/overview.html
git commit -m "feat: add dashboard overview page"
```

---

## Task 5: Corpus page

**Files:**
- Modify: `src/api/routes/dashboard.py`
- Create: `src/api/templates/dashboard/corpus.html`

- [ ] **Step 1: Add corpus route to `dashboard.py`**

```python
@router.get("/corpus")
async def corpus(request: Request):
    """Corpus page: document and chunk statistics with size distribution chart."""
    pool: asyncpg.Pool = request.app.state.pool
    stats = await get_corpus_stats(pool)
    return templates.TemplateResponse("dashboard/corpus.html", {
        "request": request,
        "active": "corpus",
        "stats": stats,
    })
```

- [ ] **Step 2: Create `src/api/templates/dashboard/corpus.html`**

```html
{% extends "dashboard/base.html" %}
{% block title %}Corpus — FOI RAG{% endblock %}
{% block content %}
<div class="page-title">Corpus</div>
<div class="page-sub">What has been ingested into the system</div>

<div class="stat-grid">
    <div class="stat-card">
        <div class="stat-label">Documents</div>
        <div class="stat-value" style="color: var(--blue)">{{ stats.doc_count }}</div>
    </div>
    <div class="stat-card">
        <div class="stat-label">Total chunks</div>
        <div class="stat-value" style="color: var(--purple)">{{ stats.chunk_count }}</div>
    </div>
    <div class="stat-card">
        <div class="stat-label">Avg chunks / doc</div>
        <div class="stat-value" style="color: var(--yellow)">{{ stats.avg_chunks_per_doc }}</div>
    </div>
</div>

<div class="chart-card">
    <div class="chart-title">Chunk size distribution (tokens)</div>
    <canvas id="distChart" height="120"></canvas>
</div>

<script>
const dist = {{ stats.chunk_size_distribution | tojson }};
const labels = Object.keys(dist);
const values = Object.values(dist);
new Chart(document.getElementById('distChart'), {
    type: 'bar',
    data: {
        labels,
        datasets: [{
            label: 'Chunks',
            data: values,
            backgroundColor: '#cba6f755',
            borderColor: '#cba6f7',
            borderWidth: 1,
        }]
    },
    options: {
        plugins: { legend: { display: false } },
        scales: {
            y: { ticks: { color: '#6c7086' }, grid: { color: '#313244' } },
            x: { ticks: { color: '#6c7086' }, grid: { color: '#313244' } }
        }
    }
});
</script>
{% endblock %}
```

- [ ] **Step 3: Manually verify**

Open `http://localhost:8000/dashboard/corpus`. Confirm stat cards show real numbers and the bar chart renders.

- [ ] **Step 4: Commit**

```bash
git add src/api/routes/dashboard.py src/api/templates/dashboard/corpus.html
git commit -m "feat: add dashboard corpus page with chunk distribution chart"
```

---

## Task 6: Eval page + run comparison

**Files:**
- Modify: `src/api/routes/dashboard.py`
- Create: `src/api/templates/dashboard/eval.html`

- [ ] **Step 1: Add eval routes to `dashboard.py`**

```python
@router.get("/eval")
async def eval_page(request: Request):
    """Eval page: recall/faithfulness trend chart, run summary table, run comparison."""
    runs = read_eval_runs(EVAL_DIR)
    return templates.TemplateResponse("dashboard/eval.html", {
        "request": request,
        "active": "eval",
        "runs": runs,
    })


@router.get("/api/eval/{timestamp}")
async def eval_run_json(timestamp: str):
    """Return JSON for a single eval run by timestamp.

    Used by the run-comparison JS in eval.html.
    {timestamp} must match the metadata.timestamp field verbatim,
    e.g. '2026-03-21T09-32-29' (hyphens, not colons).
    Returns 404 if no matching run is found.
    """
    runs = read_eval_runs(EVAL_DIR)
    for run in runs:
        if run["timestamp"] == timestamp:
            return JSONResponse(run)
    raise HTTPException(status_code=404, detail="Run not found")
```

- [ ] **Step 2: Create `src/api/templates/dashboard/eval.html`**

```html
{% extends "dashboard/base.html" %}
{% block title %}Eval — FOI RAG{% endblock %}
{% block content %}
<div class="page-title">Eval</div>
<div class="page-sub">Retrieval recall and generation faithfulness across runs</div>

{% if runs %}
<div class="chart-card">
    <div class="chart-title">Recall@5 and faithfulness over runs</div>
    <canvas id="trendChart" height="120"></canvas>
</div>

<div class="table-card">
    <table>
        <thead>
            <tr>
                <th>Run</th><th>Git SHA</th><th>Questions</th>
                <th>Recall@5</th><th>Faithfulness</th><th>Judge errors</th>
            </tr>
        </thead>
        <tbody>
        {% for run in runs %}
        <tr>
            <td>{{ run.timestamp }}</td>
            <td style="color: var(--subtle)">{{ run.metadata.git_sha if run.metadata else '—' }}</td>
            <td>{{ run.summary.total }}</td>
            <td class="hit">{{ "%.0f"|format(run.summary.recall * 100) }}%</td>
            <td style="color: var(--yellow)">{{ "%.1f"|format(run.summary.mean_faithfulness) }}/5</td>
            <td style="color: var(--subtle)">{{ run.summary.judge_errors or '—' }}</td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
</div>

<!-- Run comparison section -->
<div class="chart-card">
    <div class="chart-title">Run comparison</div>
    <div style="display: flex; gap: 16px; align-items: center; margin-bottom: 12px; flex-wrap: wrap;">
        <div>
            <div class="info-subtle" style="margin-bottom: 4px;">Run A</div>
            <select id="selectA" onchange="loadRun('selectA', 'runA')">
                <option value="">— select a run —</option>
                {% for run in runs %}
                <option value="{{ run.timestamp }}">{{ run.timestamp }}</option>
                {% endfor %}
            </select>
        </div>
        <div>
            <div class="info-subtle" style="margin-bottom: 4px;">Run B</div>
            <select id="selectB" onchange="loadRun('selectB', 'runB')">
                <option value="">— select a run —</option>
                {% for run in runs %}
                <option value="{{ run.timestamp }}">{{ run.timestamp }}</option>
                {% endfor %}
            </select>
        </div>
    </div>
    <div id="comparisonSummary" style="font-size: 13px; margin-bottom: 12px; color: var(--subtle);"></div>
    <div id="comparisonTable" style="display: none;" class="table-card">
        <table>
            <thead>
                <tr>
                    <th style="width: 45%">Question</th>
                    <th>A: Hit</th><th>A: Faith</th>
                    <th>B: Hit</th><th>B: Faith</th>
                </tr>
            </thead>
            <tbody id="comparisonBody"></tbody>
        </table>
    </div>
</div>

<script>
// Trend chart — runs are newest-first, reverse for chronological display
const runs = {{ runs | tojson }};
const labels = runs.map(r => r.timestamp).reverse();
const recalls = runs.map(r => r.summary.recall).reverse();
const faiths = runs.map(r => r.summary.mean_faithfulness).reverse();

new Chart(document.getElementById('trendChart'), {
    type: 'line',
    data: {
        labels,
        datasets: [
            {
                label: 'Recall@5',
                data: recalls,
                borderColor: '#89b4fa',
                backgroundColor: '#89b4fa22',
                yAxisID: 'yRecall',
                tension: 0.2,
            },
            {
                label: 'Faithfulness /5',
                data: faiths,
                borderColor: '#a6e3a1',
                backgroundColor: '#a6e3a122',
                yAxisID: 'yFaith',
                tension: 0.2,
            }
        ]
    },
    options: {
        plugins: { legend: { labels: { color: '#cdd6f4' } } },
        scales: {
            yRecall: { type: 'linear', position: 'left', min: 0, max: 1, ticks: { color: '#89b4fa' }, grid: { color: '#313244' } },
            yFaith:  { type: 'linear', position: 'right', min: 0, max: 5, ticks: { color: '#a6e3a1' }, grid: { display: false } },
            x: { ticks: { color: '#6c7086', maxRotation: 20 }, grid: { color: '#313244' } }
        }
    }
});

// Run comparison — fetch run data from the JSON endpoint and render side-by-side
window.runA = null;
window.runB = null;

async function loadRun(selectId, key) {
    const timestamp = document.getElementById(selectId).value;
    if (!timestamp) { window[key] = null; renderComparison(); return; }
    const resp = await fetch(`/dashboard/api/eval/${timestamp}`);
    if (!resp.ok) { alert('Could not load run'); return; }
    window[key] = await resp.json();
    renderComparison();
}

function renderComparison() {
    const a = window.runA, b = window.runB;
    const summary = document.getElementById('comparisonSummary');
    const table = document.getElementById('comparisonTable');
    const tbody = document.getElementById('comparisonBody');

    if (!a || !b) { table.style.display = 'none'; summary.textContent = ''; return; }

    summary.innerHTML =
        `<strong>Run A:</strong> ${(a.summary.recall * 100).toFixed(0)}% recall, ` +
        `${a.summary.mean_faithfulness.toFixed(1)}/5 faithfulness &nbsp;|&nbsp; ` +
        `<strong>Run B:</strong> ${(b.summary.recall * 100).toFixed(0)}% recall, ` +
        `${b.summary.mean_faithfulness.toFixed(1)}/5 faithfulness`;

    // Build lookup of Run B records by question text
    const bByQ = {};
    for (const r of b.records) bByQ[r.question] = r;

    tbody.innerHTML = '';
    for (const ra of a.records) {
        const rb = bByQ[ra.question];
        // Highlight rows where the two runs differ in hit or faithfulness (≥1 point)
        const hitDiff = rb && ra.retrieval_hit !== rb.retrieval_hit;
        const faithDiff = rb && Math.abs(ra.faithfulness_score - rb.faithfulness_score) >= 1;
        const row = document.createElement('tr');
        if (hitDiff || faithDiff) row.classList.add('diff');
        row.innerHTML = `
            <td style="font-size:12px">${ra.question.slice(0, 100)}${ra.question.length > 100 ? '…' : ''}</td>
            <td class="${ra.retrieval_hit ? 'hit' : 'miss'}">${ra.retrieval_hit ? 'HIT' : 'MISS'}</td>
            <td>${ra.faithfulness_score}/5</td>
            <td class="${rb ? (rb.retrieval_hit ? 'hit' : 'miss') : ''}">${rb ? (rb.retrieval_hit ? 'HIT' : 'MISS') : '—'}</td>
            <td>${rb ? rb.faithfulness_score + '/5' : '—'}</td>
        `;
        tbody.appendChild(row);
    }
    table.style.display = 'block';
}
</script>

{% else %}
<div class="chart-card">
    <div class="info-subtle">No eval runs found. Run <code>make eval</code> to generate results, then refresh.</div>
</div>
{% endif %}
{% endblock %}
```

- [ ] **Step 3: Manually verify**

Open `http://localhost:8000/dashboard/eval`. Confirm:
- Trend chart renders with recall and faithfulness lines
- Summary table lists all runs
- Selecting two runs in the comparison dropdowns renders the side-by-side table
- Differing rows are highlighted yellow

- [ ] **Step 4: Commit**

```bash
git add src/api/routes/dashboard.py src/api/templates/dashboard/eval.html
git commit -m "feat: add dashboard eval page with trend chart and run comparison"
```

---

## Task 7: Pipeline page

**Files:**
- Modify: `src/api/routes/dashboard.py`
- Create: `src/api/templates/dashboard/pipeline.html`

- [ ] **Step 1: Add pipeline route to `dashboard.py`**

```python
@router.get("/pipeline")
async def pipeline(request: Request):
    """Pipeline page: configuration from the latest eval run's metadata."""
    runs = read_eval_runs(EVAL_DIR)
    # Find the most recent run that has metadata
    latest_with_meta = next((r for r in runs if r["metadata"]), None)
    return templates.TemplateResponse("dashboard/pipeline.html", {
        "request": request,
        "active": "pipeline",
        "run": latest_with_meta,
    })
```

- [ ] **Step 2: Create `src/api/templates/dashboard/pipeline.html`**

```html
{% extends "dashboard/base.html" %}
{% block title %}Pipeline — FOI RAG{% endblock %}
{% block content %}
<div class="page-title">Pipeline Config</div>
<div class="page-sub">Configuration from the most recent eval run</div>

{% if run and run.metadata %}
{% set meta = run.metadata %}
<div class="chart-card">
    <div class="chart-title">Run</div>
    <div class="info-row">{{ run.timestamp }}</div>
    <div class="info-subtle">git SHA: {{ meta.git_sha }}</div>
</div>

<div class="chart-card">
    <div class="chart-title">Retrieval settings</div>
    <div class="info-row">rerank_top_k: <strong>{{ meta.rerank_top_k }}</strong></div>
</div>

<div class="chart-card">
    <div class="chart-title">Models</div>
    {% if meta.models %}
    <div class="info-row">Judge: <strong>{{ meta.models.judge }}</strong></div>
    {% endif %}
</div>

<div class="chart-card">
    <div class="chart-title">Question set</div>
    <div class="info-subtle">{{ meta.question_set }}</div>
</div>

{% else %}
<div class="chart-card">
    <div class="info-subtle">No eval run with metadata found. Run <code>make eval</code> first.</div>
</div>
{% endif %}
{% endblock %}
```

- [ ] **Step 3: Manually verify**

Open `http://localhost:8000/dashboard/pipeline`. Confirm config values are displayed.

- [ ] **Step 4: Commit**

```bash
git add src/api/routes/dashboard.py src/api/templates/dashboard/pipeline.html
git commit -m "feat: add dashboard pipeline config page"
```

---

## Task 8: Explorer page

**Files:**
- Modify: `src/api/routes/dashboard.py`
- Create: `src/api/templates/dashboard/explorer.html`

- [ ] **Step 1: Add explorer route to `dashboard.py`**

```python
@router.get("/explorer")
async def explorer(request: Request):
    """Query Explorer page: live query box that calls the /query endpoint."""
    return templates.TemplateResponse("dashboard/explorer.html", {
        "request": request,
        "active": "explorer",
    })
```

- [ ] **Step 2: Create `src/api/templates/dashboard/explorer.html`**

```html
{% extends "dashboard/base.html" %}
{% block title %}Explorer — FOI RAG{% endblock %}
{% block content %}
<div class="page-title">Query Explorer</div>
<div class="page-sub">Query the RAG pipeline and see retrieved citations</div>

<div class="chart-card">
    <div class="form-group">
        <textarea id="queryInput" rows="3" placeholder="e.g. What enforcement action has Camden taken in the private rented sector?"></textarea>
    </div>
    <button onclick="submitQuery()">Query</button>
</div>

<div id="results"></div>

<script>
// Submit a query to the /query endpoint and render the answer + citations.
// CitationItem fields: foi_reference, title, page_number, chunk_id.
// Note: chunk content is not available in citations — this view shows references only.
async function submitQuery() {
    const q = document.getElementById('queryInput').value.trim();
    if (!q) return;

    document.getElementById('results').innerHTML = '<div class="chart-card"><div class="info-subtle">Loading…</div></div>';

    const resp = await fetch('/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q }),
    });

    if (!resp.ok) {
        document.getElementById('results').innerHTML =
            '<div class="chart-card"><div class="miss">No relevant documents found.</div></div>';
        return;
    }

    const data = await resp.json();

    const citHtml = data.citations.length
        ? data.citations.map(c => `
            <li>
                <span class="citation-ref">${c.foi_reference}</span>
                ${c.title} — page ${c.page_number}
            </li>`).join('')
        : '<li style="color: var(--subtle)">No citations returned.</li>';

    document.getElementById('results').innerHTML = `
        <div class="chart-card">
            <div class="chart-title">Answer</div>
            <div class="answer-box">${data.answer}</div>
            <div class="chart-title">Citations</div>
            <ul class="citation-list">${citHtml}</ul>
        </div>`;
}
</script>
{% endblock %}
```

- [ ] **Step 3: Manually verify**

Open `http://localhost:8000/dashboard/explorer`. Type a query (e.g. "What enforcement action has Camden taken in the private rented sector?") and submit. Confirm the answer and citations render correctly.

- [ ] **Step 4: Run the full test suite**

```bash
uv run pytest -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/api/routes/dashboard.py src/api/templates/dashboard/explorer.html
git commit -m "feat: add dashboard query explorer page"
```

---

## Task 9: Documentation

**Files:**
- Create: `docs/dashboard.md`
- Modify: `README.md`

- [ ] **Step 1: Create `docs/dashboard.md`**

```markdown
# FOI RAG Dashboard

The dashboard is a web UI built into the API server that lets you explore the RAG system — what's been ingested, how it's performing, and how to query it.

## Accessing the dashboard

Start the API server (see [README](../README.md)) and open:

```
http://localhost:8000/dashboard
```

In production, replace `localhost:8000` with your server's hostname.

---

## Pages

### Overview

**Question it answers:** Is the system healthy right now?

Shows four headline metrics:
- **Documents** — total documents ingested into the vector database
- **Chunks** — total text chunks (each document is split into overlapping chunks for retrieval)
- **Recall@5** — from the most recent eval run: the fraction of questions where the correct source document appeared in the top-5 reranked results
- **Faithfulness** — from the most recent eval run: mean score (1–5) measuring how well the generated answer is supported by the retrieved sources

Also shows a bar chart of Recall@5 across all eval runs, and a summary card for the latest run.

---

### Corpus

**Question it answers:** What has been ingested, and how?

Shows:
- Total document and chunk counts
- Average chunks per document
- A bar chart showing how chunks are distributed by size (in tokens). Chunks with no token count recorded are excluded.

Chunk sizes tell you about your chunking strategy. A distribution skewed to the left means many short chunks; skewed right means long chunks. Very short chunks may lack context; very long chunks may dilute relevance.

---

### Eval

**Question it answers:** How has system performance changed across runs?

Shows:
- A dual-axis line chart tracking Recall@5 (left axis, 0–1) and Faithfulness (right axis, 0–5) across all runs from oldest to newest
- A summary table of all runs with timestamp, git SHA, question count, and metrics
- A **run comparison** tool: select any two runs from the dropdowns to see a side-by-side table of per-question results. Rows are highlighted where the runs differ in hit/miss or faithfulness score (≥1 point difference).

#### Running a new eval

```bash
make eval
```

Then refresh the Eval page. Results are saved to `eval/results_<timestamp>.jsonl` and appear automatically.

#### Interpreting Recall@5

Recall@5 measures whether the correct source document (by FOI reference) appears in the top 5 reranked chunks returned for each question. A score of 0.96 means 96% of questions retrieved the correct source in the top 5. Misses can indicate:
- The source document is poorly chunked
- The question is too dissimilar to the chunk content (embedding gap)
- The boilerplate filter excluded the relevant chunk during question generation

#### Interpreting Faithfulness

Faithfulness (1–5) is scored by Claude Haiku acting as a judge. It measures whether the generated answer is supported by the retrieved sources, not whether the answer is correct overall.

- **5** — Every claim is supported by the sources
- **4** — Minor omissions or imprecision, no fabrication
- **3** — Some claims supported, some unsupported
- **2** — Most claims go beyond or contradict the sources
- **1** — Answer is fabricated or contradicts the sources

A score of 0 means the judge failed to return parseable JSON and the question is excluded from the mean.

---

### Pipeline Config

**Question it answers:** What settings produced the latest results?

Reads metadata from the most recent eval run and displays:
- **rerank_top_k** — how many chunks the reranker returns after the initial vector search
- **Judge model** — which Claude model scored faithfulness
- **Question set** — path to the eval question set used
- **Git SHA** — the exact commit the eval was run on

---

### Explorer

**Question it answers:** How does the system respond to a specific query?

Type any question and click **Query** to run it through the full RAG pipeline:
1. Your question is embedded (OpenAI)
2. The top 20 nearest chunks are retrieved from the vector database
3. Claude reranks them to the top 5
4. Claude generates an answer grounded in those chunks

The answer and cited sources (FOI reference, document title, page number) are displayed. Chunk content is not shown here — see the source PDFs for the full text.

---

## Generating a new question set

The eval question set is fixed (committed to `eval/question_set.json`). To regenerate it from the current corpus:

```bash
rm eval/question_set.json
make generate-eval-set
```

This makes ~50 Claude API calls (one per sampled document) and costs a small amount. Boilerplate chunks (internal review notices, sign-off text) are automatically excluded.
```

- [ ] **Step 2: Add a Dashboard section to `README.md`**

Find the existing `## Quick start` section and add a new section after it:

```markdown
## Dashboard

A built-in web dashboard is available at `/dashboard` when the API is running. It shows corpus health, eval results, pipeline config, and a live query explorer.

See [docs/dashboard.md](docs/dashboard.md) for full documentation.
```

- [ ] **Step 3: Run the full test suite one final time**

```bash
uv run pytest -v
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add docs/dashboard.md README.md
git commit -m "docs: add dashboard user documentation and README section"
```

---
