# Design: Dynamic Recall@K Label and Overview Precision/F1 Metrics

**Date:** 2026-03-27
**Status:** Approved

---

## Goal

Two improvements to the eval dashboard:

1. **Dynamic Recall@K label** — replace the hardcoded "Recall@5" text with the actual K value from run metadata, falling back to "Recall@K" for old runs without a metadata header.
2. **Precision@K and F1 on the overview page** — add stat cards and replace the recall-only bar chart with a multi-line retrieval metrics chart.

---

## Scope

Template-only changes. No modifications to Python, `dashboard_utils.py`, or `eval_utils.py`. All required data (`precision`, `f1`, `metadata.rerank_top_k`) is already in the template context.

**Files changed:**
- `src/api/templates/dashboard/overview.html`
- `src/api/templates/dashboard/eval.html`

---

## Design

### 1. Dynamic Recall@K Label

`metadata.rerank_top_k` is already present in each run's parsed dict when the JSONL file has a metadata header row. Both templates already receive this data.

**Jinja2 pattern (overview, stat card label and `{% else %}` branch):**
```jinja2
Recall@{{ latest.metadata.rerank_top_k if latest.metadata else 'K' }}
```

**Jinja2 pattern (eval table header):**
```jinja2
Recall@{{ runs[0].metadata.rerank_top_k if runs and runs[0].metadata else 'K' }}
```

**JavaScript pattern (eval chart dataset label):**
```javascript
label: 'Recall@' + (runs[0]?.metadata?.rerank_top_k ?? 'K'),
```

The fallback `'K'` ensures old JSONL files without a metadata line degrade gracefully.

---

### 2. Overview Stat Cards

The stat grid expands from 4 to 6 cards. Two new cards are inserted between Recall@K and Faithfulness:

| Card | Colour | Format |
|------|--------|--------|
| Precision@K | `var(--blue)` | `"%.0f"|format(run.summary.precision * 100)`% |
| F1 | `var(--peach, #fab387)` | `"%.2f"|format(run.summary.f1)` |

Both cards are guarded by `{% if latest %}` / `{% else %}` like the existing Recall and Faithfulness cards. The `{% else %}` branch shows `—` in `var(--subtle)`.

---

### 3. Overview Chart

Replace the recall-only bar chart with a multi-line chart.

- **Type:** `line` (was `bar`)
- **Y-axis:** single axis, `min: 0`, `max: 1`, percent ticks — no dual axis needed since all three metrics are in [0, 1]
- **Legend:** shown (`display: true`)
- **Datasets:**

| Dataset | Colour | Data |
|---------|--------|------|
| `Recall@K` (dynamic label) | `#89b4fa` (blue) | `runs.map(r => r.summary.recall).reverse()` |
| `Precision@K` | `#fab387` (peach) | `runs.map(r => r.summary.precision).reverse()` |
| `F1` | `#cba6f7` (mauve) | `runs.map(r => r.summary.f1).reverse()` |

- **Chart title:** "Retrieval metrics across runs" (was "Recall@5 across runs")
- **`tension: 0.2`** on all datasets for smooth lines

The `precisions` and `f1s` variables follow the same pattern already used in `eval.html`.

---

## Non-Goals

- No per-run K column in the eval table (runs are assumed to use the same K in practice)
- No faithfulness line on the overview chart (faithfulness has a different scale and is shown as a stat card)
- No Python or API changes
