# Dashboard: Dynamic Recall@K Label and Overview Precision/F1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded "Recall@5" label with a dynamic Recall@K label, add Precision@K and F1 stat cards to the overview page, and replace the overview bar chart with a multi-line retrieval metrics chart.

**Architecture:** Template-only changes. Both files already receive all required data (`summary.precision`, `summary.f1`, `metadata.rerank_top_k`) via the template context. No Python changes needed.

**Tech Stack:** Jinja2 templates, Chart.js (already loaded via base template), vanilla JS.

---

## File Map

| File | Change |
|------|--------|
| `src/api/templates/dashboard/overview.html` | Dynamic Recall@K label; add Precision@K + F1 stat cards; replace bar chart with multi-line line chart |
| `src/api/templates/dashboard/eval.html` | Dynamic Recall@K label in table header and chart dataset |

---

### Task 1: Update `overview.html` — stat cards and chart

**Files:**
- Modify: `src/api/templates/dashboard/overview.html`

- [ ] **Step 1: Replace the stat cards block**

Replace the entire `{% if latest %} ... {% endif %}` block inside `<div class="stat-grid">` (lines 16–34) with:

```html
    {% if latest %}
    <div class="stat-card">
        <div class="stat-label">Recall@{{ latest.metadata.rerank_top_k if latest.metadata else 'K' }}</div>
        <div class="stat-value" style="color: var(--green)">{{ "%.0f"|format(latest.summary.recall * 100) }}%</div>
    </div>
    <div class="stat-card">
        <div class="stat-label">Precision@K</div>
        <div class="stat-value" style="color: var(--blue)">{{ "%.0f"|format(latest.summary.precision * 100) }}%</div>
    </div>
    <div class="stat-card">
        <div class="stat-label">F1</div>
        <div class="stat-value" style="color: var(--peach, #fab387)">{{ "%.2f"|format(latest.summary.f1) }}</div>
    </div>
    <div class="stat-card">
        <div class="stat-label">Faithfulness</div>
        <div class="stat-value" style="color: var(--yellow)">{{ "%.1f"|format(latest.summary.mean_faithfulness) }}/5</div>
    </div>
    {% else %}
    <div class="stat-card">
        <div class="stat-label">Recall@K</div>
        <div class="stat-value" style="color: var(--subtle)">—</div>
    </div>
    <div class="stat-card">
        <div class="stat-label">Precision@K</div>
        <div class="stat-value" style="color: var(--subtle)">—</div>
    </div>
    <div class="stat-card">
        <div class="stat-label">F1</div>
        <div class="stat-value" style="color: var(--subtle)">—</div>
    </div>
    <div class="stat-card">
        <div class="stat-label">Faithfulness</div>
        <div class="stat-value" style="color: var(--subtle)">—</div>
    </div>
    {% endif %}
```

- [ ] **Step 2: Update the chart title**

Replace:

```html
        <div class="chart-title">Recall@5 across runs</div>
```

with:

```html
        <div class="chart-title">Retrieval metrics across runs</div>
```

- [ ] **Step 3: Replace the chart script block**

Replace the entire `<script>` block (lines 58–83):

```html
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
```

with:

```html
<script>
// Runs are newest-first; reverse so chart reads left=oldest, right=newest
const runs = {{ runs | tojson }};
const labels = runs.map(r => r.timestamp).reverse();
const recalls = runs.map(r => r.summary.recall).reverse();
const precisions = runs.map(r => r.summary.precision).reverse();
const f1s = runs.map(r => r.summary.f1).reverse();
const recallLabel = 'Recall@' + (runs[0]?.metadata?.rerank_top_k ?? 'K');
new Chart(document.getElementById('recallChart'), {
    type: 'line',
    data: {
        labels,
        datasets: [
            {
                label: recallLabel,
                data: recalls,
                borderColor: '#89b4fa',
                backgroundColor: '#89b4fa22',
                tension: 0.2,
            },
            {
                label: 'Precision@K',
                data: precisions,
                borderColor: '#fab387',
                backgroundColor: '#fab38722',
                tension: 0.2,
            },
            {
                label: 'F1',
                data: f1s,
                borderColor: '#cba6f7',
                backgroundColor: '#cba6f722',
                tension: 0.2,
            }
        ]
    },
    options: {
        plugins: { legend: { labels: { color: '#cdd6f4' } } },
        scales: {
            y: { min: 0, max: 1, ticks: { color: '#6c7086' }, grid: { color: '#313244' } },
            x: { ticks: { color: '#6c7086', maxRotation: 20 }, grid: { color: '#313244' } }
        }
    }
});
</script>
```

- [ ] **Step 4: Run the full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS (no template tests, but confirms no Python regressions).

- [ ] **Step 5: Commit**

```bash
git add src/api/templates/dashboard/overview.html
git commit -m "feat: add Precision@K and F1 to overview page; replace bar chart with multi-line"
```

---

### Task 2: Update `eval.html` — dynamic Recall@K label

**Files:**
- Modify: `src/api/templates/dashboard/eval.html`

- [ ] **Step 1: Update the table header**

Replace:

```html
                <th>Recall@5</th><th>Precision@K</th><th>F1</th><th>Faithfulness</th><th>Judge errors</th>
```

with:

```html
                <th>Recall@{{ runs[0].metadata.rerank_top_k if runs and runs[0].metadata else 'K' }}</th><th>Precision@K</th><th>F1</th><th>Faithfulness</th><th>Judge errors</th>
```

- [ ] **Step 2: Update the chart dataset label**

Replace:

```javascript
                label: 'Recall@5',
```

with:

```javascript
                label: 'Recall@' + (runs[0]?.metadata?.rerank_top_k ?? 'K'),
```

- [ ] **Step 3: Run the full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add src/api/templates/dashboard/eval.html
git commit -m "feat: make Recall@K label dynamic from run metadata"
```
