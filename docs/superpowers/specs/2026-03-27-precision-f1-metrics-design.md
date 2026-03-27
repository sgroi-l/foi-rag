# Precision@K and F1 Metrics Design

**Date:** 2026-03-27
**Status:** Approved

## Overview

Add Precision@K and F1 to the eval harness and dashboard. The system currently measures Recall@5 (hit rate) and faithfulness. Precision and F1 complete the retrieval picture and lay groundwork for MRR and NDCG later.

## Core data structure — `RetrievalMetrics`

Replace the `score_retrieval() -> bool` function in `eval_utils.py` with `retrieval_metrics() -> RetrievalMetrics`:

```python
@dataclass
class RetrievalMetrics:
    hit: bool          # expected FOI appears in returned results
    precision: float   # 1/n_unique_returned if hit, else 0.0; 0.0 if nothing returned
    rank: int | None   # 1-based rank of expected FOI among unique FOIs; None if not found
```

`rank` is included now because MRR needs it; NDCG will require a relevance vector and can be added later.

### Deduplication

Retrieval operates at chunk level — multiple chunks from the same FOI can appear in results. All metrics are **document-level**: `retrieved_results` is deduplicated on `foi_reference` (preserving order) before computing hit, precision, and rank.

### Precision denominator

Precision uses **actual number of unique documents returned** (not a fixed k=5). The reranker is intentionally conservative and may return fewer than 5 results; penalising that behaviour would be misleading. The metric is labelled "Precision@K" in output to signal the variable denominator.

### F1

Computed at the corpus level as the harmonic mean of mean Precision@K and Recall@5:

```
F1 = 2 * precision * recall / (precision + recall)
     0.0 if both are zero
```

## Changes to `eval_utils.py`

- Add `RetrievalMetrics` dataclass
- Add `retrieval_metrics(expected_foi: str, retrieved_results: list[SearchResult]) -> RetrievalMetrics`
- Remove `score_retrieval()` (replaced by `retrieval_metrics`)
- Extend `summarise_results()` — reads `retrieval_precision` from per-question records, adds `precision` and `f1` to the returned summary dict:

```python
{
    "total": 50,
    "recall": 0.74,
    "precision": 0.23,
    "f1": 0.35,
    "mean_faithfulness": 3.8,
    "judge_errors": 2,
}
```

## Changes to `evaluate.py`

- Import `retrieval_metrics` instead of `score_retrieval`
- In `evaluate_question()`: call `retrieval_metrics()`, store `retrieval_precision` and `retrieval_rank` as flat fields in the result dict alongside existing `retrieval_hit`
- Update stdout summary:

```
Questions:         50
Recall@5:          0.74
Precision@K:       0.23
F1:                0.35
Mean faithfulness: 3.8 / 5
```

### Per-question JSONL output (additive)

New fields added to each record; existing fields unchanged (old results files remain valid):

```json
{
  "retrieval_hit": true,
  "retrieval_precision": 0.5,
  "retrieval_rank": 1,
  ...
}
```

## Changes to `eval.html`

`dashboard_utils.py` calls `summarise_results()` and passes it to the template unchanged — new summary keys flow through automatically without touching that file.

Three locations in `eval.html` need updating:

**Runs table** — add Precision@K and F1 columns:

```
Run | Git SHA | Questions | Recall@5 | Precision@K | F1 | Faithfulness | Judge errors
```

**Trend chart** — add Precision@K as a third dataset on the left axis (range 0–1, same as Recall). F1 is derivable from the other two so is omitted from the chart to avoid clutter.

**Run comparison summary text** — add precision and F1 for each run:

```
Run A: 74% recall, 0.23 precision, 0.35 F1, 3.8/5 faithfulness
Run B: ...
```

Per-question comparison table: no change — hit/miss already captures the per-question retrieval signal.

## Backward compatibility

The JSONL changes are additive. `summarise_results()` must use `.get("retrieval_precision", 0.0)` so that old results files (lacking the new fields) load without error — they will show `precision: 0.0` and `f1: 0.0` in the dashboard, which is acceptable for historical runs.

## Files changed

| File | Change |
|------|--------|
| `scripts/eval_utils.py` | Add `RetrievalMetrics`, replace `score_retrieval`, extend `summarise_results` |
| `scripts/evaluate.py` | Use `retrieval_metrics`, store new fields, update stdout |
| `src/api/templates/dashboard/eval.html` | Runs table, trend chart, comparison summary |

`dashboard_utils.py`, `generate_eval_set.py`, Makefile, and all other files: no changes.

## Future extensions

`RetrievalMetrics.rank` enables **MRR** (mean reciprocal rank) to be added to `summarise_results` with no structural changes. **NDCG** will require a relevance vector per question (binary or graded) — likely a new field on `RetrievalMetrics` when that work is scoped.
