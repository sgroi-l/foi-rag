# Precision@K and F1 Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Precision@K and F1 retrieval metrics to the eval harness and dashboard, backed by a `RetrievalMetrics` dataclass that also captures rank for future MRR/NDCG work.

**Architecture:** Replace the `score_retrieval() -> bool` function in `eval_utils.py` with `retrieval_metrics() -> RetrievalMetrics`. Extend `summarise_results()` to compute mean precision and F1 from per-question records. Update `evaluate.py` to call the new function and store the extra fields. Update the dashboard template to display the new summary values.

**Tech Stack:** Python dataclasses, pytest, Chart.js (already in dashboard), Jinja2 templates.

---

## File Map

| File | Change |
|------|--------|
| `scripts/eval_utils.py` | Add `RetrievalMetrics` dataclass; replace `score_retrieval` with `retrieval_metrics`; extend `summarise_results` |
| `scripts/evaluate.py` | Use `retrieval_metrics`; store `retrieval_precision` + `retrieval_rank` in result dict; update stdout summary |
| `tests/test_eval_utils.py` | Replace `score_retrieval` tests with `retrieval_metrics` tests; add `summarise_results` precision/F1 tests |
| `tests/fixtures/eval/results_2026-01-01T10-00-00.jsonl` | Add `retrieval_precision` and `retrieval_rank` fields to records |
| `tests/test_dashboard_utils.py` | Add assertions for `precision` and `f1` in parsed run summary |
| `src/api/templates/dashboard/eval.html` | Runs table columns; trend chart dataset; run comparison summary text |

---

### Task 1: Replace `score_retrieval` with `retrieval_metrics` in `eval_utils.py`

**Files:**
- Modify: `scripts/eval_utils.py`
- Modify: `tests/test_eval_utils.py`

- [ ] **Step 1: Replace the `score_retrieval` tests with `retrieval_metrics` tests**

In `tests/test_eval_utils.py`, replace the entire `# --- score_retrieval ---` block (lines 26–39) with:

```python
from scripts.eval_utils import (
    retrieval_metrics,
    format_chunks_for_prompt,
    parse_judge_response,
    summarise_results,
    RetrievalMetrics,
)
```

(Replace the existing import block at the top of the file — remove `score_retrieval` from it.)

Then replace the `# --- score_retrieval ---` test block with:

```python
# --- retrieval_metrics ---

def test_retrieval_metrics_hit_single_result():
    results = [make_result("CAM001")]
    m = retrieval_metrics("CAM001", results)
    assert m.hit is True
    assert m.rank == 1
    assert abs(m.precision - 1.0) < 0.001


def test_retrieval_metrics_hit_multiple_results():
    results = [make_result("CAM002"), make_result("CAM001"), make_result("CAM003")]
    m = retrieval_metrics("CAM001", results)
    assert m.hit is True
    assert m.rank == 2
    assert abs(m.precision - 1 / 3) < 0.001


def test_retrieval_metrics_miss():
    results = [make_result("CAM002"), make_result("CAM003")]
    m = retrieval_metrics("CAM001", results)
    assert m.hit is False
    assert m.rank is None
    assert m.precision == 0.0


def test_retrieval_metrics_empty_results():
    m = retrieval_metrics("CAM001", [])
    assert m.hit is False
    assert m.rank is None
    assert m.precision == 0.0


def test_retrieval_metrics_deduplicates_chunks():
    # Two chunks from same FOI — should count as 1 unique document
    results = [make_result("CAM001"), make_result("CAM001"), make_result("CAM002")]
    m = retrieval_metrics("CAM001", results)
    assert m.hit is True
    assert m.rank == 1
    # 2 unique FOIs: CAM001, CAM002 → precision = 1/2
    assert abs(m.precision - 0.5) < 0.001


def test_retrieval_metrics_preserves_order_after_dedup():
    # CAM002 appears first (two chunks), CAM001 second → rank of CAM001 is 2
    results = [make_result("CAM002"), make_result("CAM002"), make_result("CAM001")]
    m = retrieval_metrics("CAM001", results)
    assert m.rank == 2
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
uv run pytest tests/test_eval_utils.py -k "retrieval_metrics" -v
```

Expected: `ImportError` or `AttributeError` — `retrieval_metrics` does not exist yet.

- [ ] **Step 3: Implement `RetrievalMetrics` and `retrieval_metrics` in `eval_utils.py`**

In `scripts/eval_utils.py`, replace:

```python
import json
from src.retrieval.search import SearchResult


def score_retrieval(expected_foi: str, retrieved_results: list[SearchResult]) -> bool:
    """Return True if the expected FOI reference appears in the retrieved results."""
    return any(r.foi_reference == expected_foi for r in retrieved_results)
```

with:

```python
import json
from dataclasses import dataclass
from src.retrieval.search import SearchResult


@dataclass
class RetrievalMetrics:
    hit: bool
    precision: float   # 1/n_unique_returned if hit, else 0.0; 0.0 if nothing returned
    rank: int | None   # 1-based rank of expected FOI among unique FOIs; None if not found


def retrieval_metrics(expected_foi: str, retrieved_results: list[SearchResult]) -> RetrievalMetrics:
    """Compute document-level retrieval metrics for a single question.

    Deduplicates on foi_reference (preserving order) before computing metrics.
    Precision denominator is the actual number of unique documents returned.
    """
    seen: list[str] = []
    for r in retrieved_results:
        if r.foi_reference not in seen:
            seen.append(r.foi_reference)

    if not seen:
        return RetrievalMetrics(hit=False, precision=0.0, rank=None)

    try:
        rank = seen.index(expected_foi) + 1
        return RetrievalMetrics(hit=True, precision=1 / len(seen), rank=rank)
    except ValueError:
        return RetrievalMetrics(hit=False, precision=0.0, rank=None)
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
uv run pytest tests/test_eval_utils.py -k "retrieval_metrics" -v
```

Expected: all 6 `retrieval_metrics` tests PASS.

- [ ] **Step 5: Confirm no other tests broke**

```bash
uv run pytest tests/test_eval_utils.py -v
```

Expected: all tests PASS (the old `score_retrieval` tests were removed in Step 1).

- [ ] **Step 6: Commit**

```bash
git add scripts/eval_utils.py tests/test_eval_utils.py
git commit -m "feat: replace score_retrieval with RetrievalMetrics dataclass"
```

---

### Task 2: Extend `summarise_results` with precision and F1

**Files:**
- Modify: `scripts/eval_utils.py`
- Modify: `tests/test_eval_utils.py`

- [ ] **Step 1: Add failing tests for precision and F1 in `summarise_results`**

Append to the `# --- summarise_results ---` section in `tests/test_eval_utils.py`:

```python
def test_summarise_results_precision_and_f1():
    records = [
        {"retrieval_hit": True,  "retrieval_precision": 1.0, "faithfulness_score": 5},
        {"retrieval_hit": True,  "retrieval_precision": 0.5, "faithfulness_score": 4},
        {"retrieval_hit": False, "retrieval_precision": 0.0, "faithfulness_score": 3},
    ]
    summary = summarise_results(records)
    # recall = 2/3
    assert abs(summary["recall"] - 2 / 3) < 0.001
    # precision = (1.0 + 0.5 + 0.0) / 3 = 0.5
    assert abs(summary["precision"] - 0.5) < 0.001
    # f1 = 2 * 0.5 * (2/3) / (0.5 + 2/3)
    expected_f1 = 2 * 0.5 * (2 / 3) / (0.5 + 2 / 3)
    assert abs(summary["f1"] - expected_f1) < 0.001


def test_summarise_results_precision_zero_no_divide_by_zero():
    # All misses — precision=0, recall=0, f1 must be 0 not ZeroDivisionError
    records = [
        {"retrieval_hit": False, "retrieval_precision": 0.0, "faithfulness_score": 2},
    ]
    summary = summarise_results(records)
    assert summary["precision"] == 0.0
    assert summary["f1"] == 0.0


def test_summarise_results_backward_compat_missing_precision():
    # Records from old runs lack retrieval_precision — should default to 0.0
    records = [
        {"retrieval_hit": True, "faithfulness_score": 5},
        {"retrieval_hit": False, "faithfulness_score": 3},
    ]
    summary = summarise_results(records)
    assert summary["precision"] == 0.0
    assert summary["f1"] == 0.0


def test_summarise_results_empty_has_precision_and_f1():
    summary = summarise_results([])
    assert summary["precision"] == 0.0
    assert summary["f1"] == 0.0
```

- [ ] **Step 2: Run to confirm they fail**

```bash
uv run pytest tests/test_eval_utils.py -k "precision or f1" -v
```

Expected: FAIL — `summarise_results` does not yet return `precision` or `f1` keys.

- [ ] **Step 3: Extend `summarise_results` in `eval_utils.py`**

Replace the existing `summarise_results` function with:

```python
def summarise_results(records: list[dict]) -> dict:
    """Compute recall, precision, F1, and mean faithfulness from per-question result dicts.

    Records with faithfulness_score == 0 are excluded from the faithfulness mean.
    Records missing retrieval_precision (old format) default to 0.0 for backward compat.
    Uses safe dict access (.get) to handle malformed records gracefully.
    """
    if not records:
        return {
            "total": 0,
            "recall": 0.0,
            "precision": 0.0,
            "f1": 0.0,
            "mean_faithfulness": 0.0,
            "judge_errors": 0,
        }

    total = len(records)
    hits = sum(1 for r in records if r.get("retrieval_hit", False))
    recall = hits / total
    mean_precision = sum(r.get("retrieval_precision", 0.0) for r in records) / total
    f1 = (
        2 * mean_precision * recall / (mean_precision + recall)
        if (mean_precision + recall) > 0
        else 0.0
    )

    scoreable = [r for r in records if r.get("faithfulness_score", 0) > 0]
    judge_errors = total - len(scoreable)
    mean_faith = (
        sum(r.get("faithfulness_score", 0) for r in scoreable) / len(scoreable)
        if scoreable
        else 0.0
    )

    return {
        "total": total,
        "recall": recall,
        "precision": mean_precision,
        "f1": f1,
        "mean_faithfulness": mean_faith,
        "judge_errors": judge_errors,
    }
```

- [ ] **Step 4: Run the new tests to confirm they pass**

```bash
uv run pytest tests/test_eval_utils.py -k "precision or f1" -v
```

Expected: all 4 new tests PASS.

- [ ] **Step 5: Run the full test file to confirm nothing regressed**

```bash
uv run pytest tests/test_eval_utils.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/eval_utils.py tests/test_eval_utils.py
git commit -m "feat: add precision and F1 to summarise_results"
```

---

### Task 3: Update `evaluate.py` to use `retrieval_metrics`

**Files:**
- Modify: `scripts/evaluate.py`

- [ ] **Step 1: Update the import in `evaluate.py`**

In `scripts/evaluate.py`, replace:

```python
from scripts.eval_utils import (
    score_retrieval,
    format_chunks_for_prompt,
    parse_judge_response,
    summarise_results,
)
```

with:

```python
from scripts.eval_utils import (
    retrieval_metrics,
    format_chunks_for_prompt,
    parse_judge_response,
    summarise_results,
)
```

- [ ] **Step 2: Update `evaluate_question` to call `retrieval_metrics`**

In `evaluate_question`, replace:

```python
    hit = score_retrieval(expected_foi, reranked)
    retrieved_fois = [r.foi_reference for r in reranked]
```

with:

```python
    metrics = retrieval_metrics(expected_foi, reranked)
    retrieved_fois = [r.foi_reference for r in reranked]
```

Then in the `return` dict, replace:

```python
        "retrieval_hit": hit,
```

with:

```python
        "retrieval_hit": metrics.hit,
        "retrieval_precision": metrics.precision,
        "retrieval_rank": metrics.rank,
```

- [ ] **Step 3: Update the per-question progress line**

In the `main` loop, replace:

```python
            hit_str = "HIT" if record["retrieval_hit"] else "MISS"
            print(f"  Retrieval: {hit_str} | Faithfulness: {record['faithfulness_score']}/5")
```

with:

```python
            hit_str = "HIT" if record["retrieval_hit"] else "MISS"
            print(f"  Retrieval: {hit_str} (rank={record['retrieval_rank']}, prec={record['retrieval_precision']:.2f}) | Faithfulness: {record['faithfulness_score']}/5")
```

- [ ] **Step 4: Update the stdout summary**

Replace:

```python
    print(f"\nQuestions:         {summary['total']}")
    print(f"Recall@5:          {summary['recall']:.2f}")
    print(f"Mean faithfulness: {summary['mean_faithfulness']:.1f} / 5")
    if summary["judge_errors"]:
        print(f"Judge errors:      {summary['judge_errors']} (excluded from faithfulness mean)")
```

with:

```python
    print(f"\nQuestions:         {summary['total']}")
    print(f"Recall@5:          {summary['recall']:.2f}")
    print(f"Precision@K:       {summary['precision']:.2f}")
    print(f"F1:                {summary['f1']:.2f}")
    print(f"Mean faithfulness: {summary['mean_faithfulness']:.1f} / 5")
    if summary["judge_errors"]:
        print(f"Judge errors:      {summary['judge_errors']} (excluded from faithfulness mean)")
```

- [ ] **Step 5: Run the full test suite to confirm nothing broke**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/evaluate.py
git commit -m "feat: store retrieval_precision and retrieval_rank in eval results"
```

---

### Task 4: Update fixture and dashboard tests

**Files:**
- Modify: `tests/fixtures/eval/results_2026-01-01T10-00-00.jsonl`
- Modify: `tests/test_dashboard_utils.py`

- [ ] **Step 1: Add failing tests for precision and F1 in the dashboard summary**

Append to `tests/test_dashboard_utils.py`:

```python
def test_parse_run_file_precision_and_f1():
    run = parse_run_file(FIXTURES / "results_2026-01-01T10-00-00.jsonl")
    # record 1: hit, precision=1.0; record 2: miss, precision=0.0 → mean=0.5
    # recall=0.5, precision=0.5 → f1 = 2*0.5*0.5/(0.5+0.5) = 0.5
    assert abs(run["summary"]["precision"] - 0.5) < 0.001
    assert abs(run["summary"]["f1"] - 0.5) < 0.001
```

- [ ] **Step 2: Run to confirm it fails**

```bash
uv run pytest tests/test_dashboard_utils.py::test_parse_run_file_precision_and_f1 -v
```

Expected: FAIL — fixture records lack `retrieval_precision`.

- [ ] **Step 3: Update the fixture to include `retrieval_precision` and `retrieval_rank`**

Replace the entire contents of `tests/fixtures/eval/results_2026-01-01T10-00-00.jsonl` with:

```
{"_type": "metadata", "timestamp": "2026-01-01T10-00-00", "git_sha": "abc123", "rerank_top_k": 5, "question_set": "eval/question_set.json", "models": {"judge": "claude-haiku-4-5-20251001"}}
{"question": "What is Camden's policy?", "expected_foi": "CAM001", "retrieved_fois": ["CAM001"], "retrieval_hit": true, "retrieval_precision": 1.0, "retrieval_rank": 1, "answer": "Camden has a policy.", "faithfulness_score": 4, "faithfulness_reason": "Supported.", "retrieved_chunks": []}
{"question": "How many staff?", "expected_foi": "CAM002", "retrieved_fois": ["CAM003"], "retrieval_hit": false, "retrieval_precision": 0.0, "retrieval_rank": null, "answer": "Unknown.", "faithfulness_score": 3, "faithfulness_reason": "Partial.", "retrieved_chunks": []}
```

- [ ] **Step 4: Run the new test to confirm it passes**

```bash
uv run pytest tests/test_dashboard_utils.py::test_parse_run_file_precision_and_f1 -v
```

Expected: PASS.

- [ ] **Step 5: Run the full dashboard test file to confirm nothing regressed**

```bash
uv run pytest tests/test_dashboard_utils.py -v
```

Expected: all tests PASS (existing tests don't assert on precision/f1 so are unaffected).

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/eval/results_2026-01-01T10-00-00.jsonl tests/test_dashboard_utils.py
git commit -m "test: add precision and F1 assertions for dashboard eval summary"
```

---

### Task 5: Update `eval.html` dashboard template

**Files:**
- Modify: `src/api/templates/dashboard/eval.html`

- [ ] **Step 1: Update the runs table header**

Replace:

```html
            <tr>
                <th>Run</th><th>Git SHA</th><th>Questions</th>
                <th>Recall@5</th><th>Faithfulness</th><th>Judge errors</th>
            </tr>
```

with:

```html
            <tr>
                <th>Run</th><th>Git SHA</th><th>Questions</th>
                <th>Recall@5</th><th>Precision@K</th><th>F1</th><th>Faithfulness</th><th>Judge errors</th>
            </tr>
```

- [ ] **Step 2: Update the runs table data row**

Replace:

```html
            <td class="hit">{{ "%.0f"|format(run.summary.recall * 100) }}%</td>
            <td style="color: var(--yellow)">{{ "%.1f"|format(run.summary.mean_faithfulness) }}/5</td>
            <td style="color: var(--subtle)">{{ run.summary.judge_errors or '—' }}</td>
```

with:

```html
            <td class="hit">{{ "%.0f"|format(run.summary.recall * 100) }}%</td>
            <td style="color: var(--blue, #89b4fa)">{{ "%.0f"|format(run.summary.precision * 100) }}%</td>
            <td style="color: var(--peach, #fab387)">{{ "%.2f"|format(run.summary.f1) }}</td>
            <td style="color: var(--yellow)">{{ "%.1f"|format(run.summary.mean_faithfulness) }}/5</td>
            <td style="color: var(--subtle)">{{ run.summary.judge_errors or '—' }}</td>
```

- [ ] **Step 3: Add Precision@K to the trend chart datasets**

In the `datasets` array of the Chart.js config, after the Recall@5 dataset and before the Faithfulness dataset, add a third entry:

Replace:

```javascript
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
```

with:

```javascript
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
                label: 'Precision@K',
                data: precisions,
                borderColor: '#fab387',
                backgroundColor: '#fab38722',
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
```

Also add the `precisions` variable alongside `recalls` and `faiths` at the top of the script block. Replace:

```javascript
const recalls = runs.map(r => r.summary.recall).reverse();
const faiths = runs.map(r => r.summary.mean_faithfulness).reverse();
```

with:

```javascript
const recalls = runs.map(r => r.summary.recall).reverse();
const precisions = runs.map(r => r.summary.precision).reverse();
const faiths = runs.map(r => r.summary.mean_faithfulness).reverse();
```

- [ ] **Step 4: Update the run comparison summary text**

Replace:

```javascript
    summary.innerHTML =
        `<strong>Run A:</strong> ${(a.summary.recall * 100).toFixed(0)}% recall, ` +
        `${a.summary.mean_faithfulness.toFixed(1)}/5 faithfulness &nbsp;|&nbsp; ` +
        `<strong>Run B:</strong> ${(b.summary.recall * 100).toFixed(0)}% recall, ` +
        `${b.summary.mean_faithfulness.toFixed(1)}/5 faithfulness`;
```

with:

```javascript
    summary.innerHTML =
        `<strong>Run A:</strong> ${(a.summary.recall * 100).toFixed(0)}% recall, ` +
        `${(a.summary.precision * 100).toFixed(0)}% precision, ` +
        `${a.summary.f1.toFixed(2)} F1, ` +
        `${a.summary.mean_faithfulness.toFixed(1)}/5 faithfulness &nbsp;|&nbsp; ` +
        `<strong>Run B:</strong> ${(b.summary.recall * 100).toFixed(0)}% recall, ` +
        `${(b.summary.precision * 100).toFixed(0)}% precision, ` +
        `${b.summary.f1.toFixed(2)} F1, ` +
        `${b.summary.mean_faithfulness.toFixed(1)}/5 faithfulness`;
```

- [ ] **Step 5: Run the full test suite to confirm nothing broke**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/api/templates/dashboard/eval.html
git commit -m "feat: add Precision@K and F1 to eval dashboard"
```
