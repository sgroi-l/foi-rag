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
