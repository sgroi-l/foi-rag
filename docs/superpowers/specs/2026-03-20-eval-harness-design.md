# Evaluation Harness Design

**Date:** 2026-03-20
**Status:** Approved

## Overview

A two-script evaluation harness that measures retrieval quality and generation faithfulness for the Camden FOI RAG system. Built as a learning tool — emphasis on visible internals and per-question breakdowns rather than just headline numbers.

## Structure

```
scripts/
  generate_eval_set.py   # reads DB chunks, calls Claude, writes question set
  evaluate.py            # loads question set, runs pipeline, scores, logs

eval/
  question_set.json      # generated once, inspectable and editable
  results_<timestamp>.jsonl  # one line per question, one file per run
```

Two Makefile targets:
- `make generate-eval-set` — runs the generator (done once, or when you want fresh questions)
- `make eval` — runs the evaluator against the current pipeline

## Question Generation (`generate_eval_set.py`)

1. Pull one chunk per unique FOI document from the database (to avoid bias toward large documents), sampling up to ~50 documents
2. For each chunk, call Claude with a prompt asking it to produce one specific question the chunk answers, plus a concise expected answer drawn only from that chunk
3. Write results to `eval/question_set.json`

Each entry uses the raw `Identifier` value as stored in `documents.foi_reference` (e.g. `"CAM6551"`):
```json
{
  "question": "How many households were on the housing waiting list in 2022?",
  "source_foi_reference": "CAM6551",
  "source_document_title": "Housing Waiting List Statistics",
  "expected_answer": "There were 12,500 households on the waiting list as of March 2022."
}
```

The `source_foi_reference` field is the retrieval ground truth — used to check whether the right document was returned.

## Evaluation (`evaluate.py`)

For each question in the set:

1. Run the existing pipeline: embed → `vector_search` (top_k=20) → `rerank` (top_k=5) → `generate_answer`
2. Score retrieval: check whether `source_foi_reference` appears in the actually-returned reranked results (the reranker can return fewer than top_k when few results are genuinely relevant)
3. Score faithfulness: call Claude as a judge (see prompt below)

### Faithfulness judge prompt

Claude receives the question, the generated answer, and the retrieved chunk texts. It is asked to reason first, then score:

```
You are evaluating a RAG system answer for faithfulness to its sources.

Question: {question}

Retrieved sources:
{chunks}

Generated answer:
{answer}

Does the answer accurately reflect what the sources say, without adding unsupported claims?
Reason step by step, then give a score from 1 to 5 using this rubric:
  5 — Fully faithful: every claim is supported by the sources
  4 — Mostly faithful: minor omissions or imprecision, no fabrication
  3 — Partially faithful: some claims supported, some unsupported
  2 — Mostly unfaithful: most claims go beyond or contradict the sources
  1 — Not faithful: answer is fabricated or contradicts the sources

Respond in JSON: {"reason": "...", "score": N}
```

`{chunks}` is the list of retrieved chunk texts, formatted as `[SOURCE N] FOI ref — title\nPage N\ncontent` — the same format passed to the generator. The faithfulness judge uses `claude-haiku-4-5-20251001` (cheap, fast; quality is sufficient for a 1–5 rubric).

### Per-question output (`eval/results_<timestamp>.jsonl`)

Results are written to a timestamped file (e.g. `eval/results_2026-03-20T14-00.jsonl`) so runs can be compared over time. One JSON line per question:

```json
{
  "question": "...",
  "expected_foi": "CAM6551",
  "retrieved_fois": ["CAM6551", "CAM4321"],
  "retrieval_hit": true,
  "answer": "...",
  "faithfulness_score": 4,
  "faithfulness_reason": "Answer correctly cites the waiting list figure but omits the date qualifier.",
  "retrieved_chunks": [
    {"foi_reference": "CAM6551", "title": "...", "page_number": 2, "content": "..."},
    {"foi_reference": "CAM4321", "title": "...", "page_number": 1, "content": "..."}
  ]
}
```

### Summary (stdout)

```
Questions:         50
Recall@5:          0.74
Mean faithfulness: 3.8 / 5
```

## Scoring Details

**Retrieval (Recall@k):** Document-level. A question is a "hit" if the source FOI reference appears anywhere in the actually-returned reranked results. Since the reranker only returns results it considers genuinely relevant, the effective k may be less than 5 — the evaluator checks the actual list, not a fixed window.

**Faithfulness (LLM-as-judge):** Claude reasons before scoring (chain-of-thought), then returns structured JSON. This is the same technique RAGAS uses internally — building it manually first makes the RAGAS abstraction easier to understand later.

## Cost note

Each eval run makes approximately 100 Claude API calls (50 for generation + 50 for faithfulness judging) plus 50 OpenAI embedding calls. At current pricing this is roughly $0.10–0.30 per full run. The generator makes ~50 additional Claude calls (one per chunk) and is run once.

## What This Does Not Cover (Future)

- Chunk-level retrieval precision
- Answer relevance (does the answer address the question, independent of faithfulness)
- RAGAS integration (intended as a follow-on once the manual harness is understood)
- CI integration
