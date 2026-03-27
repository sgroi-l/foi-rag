# Evaluation Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a two-script evaluation harness that generates synthetic Q&A pairs from the FOI corpus and scores the RAG pipeline on retrieval recall and generation faithfulness.

**Architecture:** Pure utility functions (testable without I/O) live in `scripts/eval_utils.py`. Two scripts (`generate_eval_set.py`, `evaluate.py`) orchestrate DB access and Claude/OpenAI calls. Both scripts are `async` for DB access via `asyncpg`, but all synchronous blocking calls (Claude, OpenAI embeddings, reranking) are wrapped with `asyncio.to_thread` to avoid blocking the event loop. Results are written to timestamped JSONL files in `eval/`.

**Tech Stack:** Python 3.13, asyncpg, anthropic SDK, openai SDK, pytest. No new dependencies required.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `scripts/eval_utils.py` | Create | Pure functions: retrieval scoring, chunk formatting, judge response parsing, summary computation |
| `scripts/generate_eval_set.py` | Create | Async script: samples one chunk per document, calls Claude, writes `eval/question_set.json` |
| `scripts/evaluate.py` | Create | Async script: runs full pipeline per question, scores, writes timestamped JSONL |
| `tests/test_eval_utils.py` | Create | Unit tests for all pure functions in `eval_utils.py` |
| `eval/.gitkeep` | Create | Keeps the `eval/` directory in git |
| `.gitignore` | Modify | Ignore `eval/results_*.jsonl` (generated output, not source) |
| `Makefile` | Modify | Add `generate-eval-set` and `eval` targets (and to `.PHONY`) |

---

## Task 1: Scaffold the `eval/` directory and Makefile targets

**Files:**
- Create: `eval/.gitkeep`
- Modify: `.gitignore`
- Modify: `Makefile`

- [ ] **Step 1: Create `eval/` directory with a `.gitkeep`**

```bash
mkdir -p eval && touch eval/.gitkeep
```

- [ ] **Step 2: Add results files to `.gitignore`**

Append to `.gitignore` (or create it if absent):
```
eval/results_*.jsonl
```

- [ ] **Step 3: Add Makefile targets**

Update the `.PHONY` line to include the two new targets, and add the targets themselves:

```makefile
.PHONY: dev up down reset logs psql download ingest generate-eval-set eval

# Generate synthetic evaluation question set (run once)
generate-eval-set:
	uv run python3 scripts/generate_eval_set.py

# Run the evaluation harness
eval:
	uv run python3 scripts/evaluate.py
```

- [ ] **Step 4: Verify Makefile parses cleanly**

```bash
make --dry-run eval
```
Expected: prints `uv run python3 scripts/evaluate.py` with no errors.

- [ ] **Step 5: Commit**

```bash
git add eval/.gitkeep .gitignore Makefile
git commit -m "feat: scaffold eval directory and Makefile targets"
```

---

## Task 2: Write `eval_utils.py` pure functions (TDD)

These are the core logic units of the harness — no I/O, fully testable.

Note on `summarise_results`: records where `faithfulness_score == 0` are excluded from the faithfulness mean, because 0 indicates a judge parse failure rather than a genuine score. The count of excluded records is included in the summary for transparency.

**Files:**
- Create: `scripts/eval_utils.py`
- Create: `tests/test_eval_utils.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eval_utils.py`:

```python
from scripts.eval_utils import (
    score_retrieval,
    format_chunks_for_prompt,
    parse_judge_response,
    summarise_results,
)
from src.retrieval.search import SearchResult
from datetime import date


def make_result(foi_reference: str, title: str = "Title", content: str = "Content") -> SearchResult:
    return SearchResult(
        chunk_id="c1",
        document_id="d1",
        filename="file.pdf",
        foi_reference=foi_reference,
        title=title,
        date=date(2023, 1, 1),
        page_number=1,
        chunk_index=0,
        content=content,
        score=0.9,
    )


# --- score_retrieval ---

def test_score_retrieval_hit():
    results = [make_result("CAM001"), make_result("CAM002")]
    assert score_retrieval("CAM001", results) is True


def test_score_retrieval_miss():
    results = [make_result("CAM002"), make_result("CAM003")]
    assert score_retrieval("CAM001", results) is False


def test_score_retrieval_empty_results():
    assert score_retrieval("CAM001", []) is False


# --- format_chunks_for_prompt ---

def test_format_chunks_for_prompt_single():
    results = [make_result("CAM001", title="Housing", content="Some text")]
    output = format_chunks_for_prompt(results)
    assert "[SOURCE 1]" in output
    assert "CAM001" in output
    assert "Housing" in output
    assert "Some text" in output


def test_format_chunks_for_prompt_multiple():
    results = [make_result("CAM001"), make_result("CAM002")]
    output = format_chunks_for_prompt(results)
    assert "[SOURCE 1]" in output
    assert "[SOURCE 2]" in output


def test_format_chunks_for_prompt_empty():
    assert format_chunks_for_prompt([]) == ""


# --- parse_judge_response ---

def test_parse_judge_response_valid():
    text = '{"reason": "All claims supported.", "score": 5}'
    score, reason = parse_judge_response(text)
    assert score == 5
    assert reason == "All claims supported."


def test_parse_judge_response_invalid_json():
    score, reason = parse_judge_response("not json at all")
    assert score == 0
    assert "parse error" in reason.lower()


def test_parse_judge_response_missing_reason():
    # Missing "reason" key — score is returned, reason defaults to ""
    score, reason = parse_judge_response('{"score": 3}')
    assert score == 3
    assert reason == ""


def test_parse_judge_response_missing_score():
    # Missing "score" key — score defaults to 0 (treated as parse failure by summarise_results)
    score, reason = parse_judge_response('{"reason": "text"}')
    assert score == 0
    assert reason == "text"


# --- summarise_results ---

def test_summarise_results_basic():
    records = [
        {"retrieval_hit": True, "faithfulness_score": 5},
        {"retrieval_hit": False, "faithfulness_score": 3},
        {"retrieval_hit": True, "faithfulness_score": 4},
    ]
    summary = summarise_results(records)
    assert summary["total"] == 3
    assert abs(summary["recall"] - 2 / 3) < 0.001
    assert abs(summary["mean_faithfulness"] - 4.0) < 0.001
    assert summary["judge_errors"] == 0


def test_summarise_results_excludes_parse_failures():
    # score=0 means judge failed — excluded from faithfulness mean
    records = [
        {"retrieval_hit": True, "faithfulness_score": 4},
        {"retrieval_hit": True, "faithfulness_score": 0},  # parse failure
    ]
    summary = summarise_results(records)
    assert summary["total"] == 2
    assert summary["mean_faithfulness"] == 4.0  # 0 excluded
    assert summary["judge_errors"] == 1


def test_summarise_results_all_hits():
    records = [{"retrieval_hit": True, "faithfulness_score": 5}]
    summary = summarise_results(records)
    assert summary["recall"] == 1.0


def test_summarise_results_empty():
    summary = summarise_results([])
    assert summary["total"] == 0
    assert summary["recall"] == 0.0
    assert summary["mean_faithfulness"] == 0.0
    assert summary["judge_errors"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_eval_utils.py -v
```
Expected: `ModuleNotFoundError` or `ImportError` — `eval_utils` doesn't exist yet.

- [ ] **Step 3: Create `scripts/eval_utils.py`**

```python
import json
from src.retrieval.search import SearchResult


def score_retrieval(expected_foi: str, retrieved_results: list[SearchResult]) -> bool:
    """Return True if the expected FOI reference appears in the retrieved results."""
    return any(r.foi_reference == expected_foi for r in retrieved_results)


def format_chunks_for_prompt(results: list[SearchResult]) -> str:
    """Format retrieved chunks as [SOURCE N] blocks for use in LLM prompts."""
    if not results:
        return ""
    parts = []
    for i, r in enumerate(results):
        parts.append(
            f"[SOURCE {i + 1}] FOI {r.foi_reference} — {r.title}\n"
            f"Page {r.page_number}\n"
            f"{r.content}"
        )
    return "\n\n---\n\n".join(parts)


def parse_judge_response(text: str) -> tuple[int, str]:
    """Parse Claude's faithfulness judge JSON response.

    Returns (score, reason). On parse failure returns (0, "parse error: ...").
    A score of 0 is treated as a parse failure by summarise_results.
    """
    try:
        data = json.loads(text)
        score = int(data.get("score", 0))
        reason = str(data.get("reason", ""))
        return score, reason
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        return 0, f"parse error: {e}"


def summarise_results(records: list[dict]) -> dict:
    """Compute recall and mean faithfulness from a list of per-question result dicts.

    Records with faithfulness_score == 0 are excluded from the faithfulness mean
    (score 0 indicates a judge parse failure, not a genuine score).
    """
    if not records:
        return {"total": 0, "recall": 0.0, "mean_faithfulness": 0.0, "judge_errors": 0}

    total = len(records)
    hits = sum(1 for r in records if r["retrieval_hit"])
    scoreable = [r for r in records if r["faithfulness_score"] > 0]
    judge_errors = total - len(scoreable)
    mean_faith = sum(r["faithfulness_score"] for r in scoreable) / len(scoreable) if scoreable else 0.0

    return {
        "total": total,
        "recall": hits / total,
        "mean_faithfulness": mean_faith,
        "judge_errors": judge_errors,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_eval_utils.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/eval_utils.py tests/test_eval_utils.py
git commit -m "feat: add eval_utils pure functions with tests"
```

---

## Task 3: Write `generate_eval_set.py`

Samples one chunk per document from the DB, calls Claude to generate a Q&A pair per chunk, writes `eval/question_set.json`.

`generate_qa` is a plain synchronous function — it makes a single blocking Claude call. It is called directly (not awaited) in a sequential `for` loop. The script's `main()` is `async` only because it uses `asyncpg` for DB access.

Note on `RANDOM_SEED`: the seed controls `random.sample()` (which documents to pick from the fetched pool), not the SQL `ORDER BY RANDOM()` (which chunk to pick per document). Regenerating will produce a different question set even with the same seed if the database contents change.

**Files:**
- Create: `scripts/generate_eval_set.py`

- [ ] **Step 1: Create `scripts/generate_eval_set.py`**

```python
import asyncio
import json
import os
import random
import sys
from pathlib import Path

import asyncpg
import anthropic
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

N_SAMPLE = 50
# Controls random.sample() — which documents to include.
# Does NOT affect ORDER BY RANDOM() in SQL (which chunk per document).
RANDOM_SEED = 42
OUTPUT_PATH = Path("eval/question_set.json")

GENERATION_PROMPT = """\
You are generating evaluation data for a RAG system about Camden Council Freedom of Information requests.

Below is an excerpt from an FOI document. Write one specific factual question that this excerpt directly answers, and a concise expected answer based only on this text.

Document: {title} (FOI {foi_reference})
Excerpt:
{content}

Respond in JSON:
{{"question": "...", "expected_answer": "..."}}

Return only the JSON, nothing else."""


def generate_qa(client: anthropic.Anthropic, title: str, foi_reference: str, content: str) -> dict | None:
    """Generate a Q&A pair for a single chunk. Synchronous — called sequentially."""
    prompt = GENERATION_PROMPT.format(title=title, foi_reference=foi_reference, content=content)
    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        data = json.loads(message.content[0].text.strip())
        return {
            "question": data["question"],
            "source_foi_reference": foi_reference,
            "source_document_title": title,
            "expected_answer": data["expected_answer"],
        }
    except (json.JSONDecodeError, KeyError) as e:
        print(f"  Skipping ({foi_reference}): {e}")
        return None


async def main() -> None:
    random.seed(RANDOM_SEED)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    client = anthropic.Anthropic()

    # Fetch one random chunk per document (ORDER BY RANDOM() is non-deterministic)
    rows = await pool.fetch("""
        SELECT DISTINCT ON (d.id)
            d.foi_reference,
            d.title,
            c.content
        FROM documents d
        JOIN chunks c ON c.document_id = d.id
        ORDER BY d.id, RANDOM()
    """)
    await pool.close()

    print(f"Documents available: {len(rows)}")
    sample = random.sample(list(rows), min(N_SAMPLE, len(rows)))
    print(f"Sampling {len(sample)} documents...")

    questions = []
    for i, row in enumerate(sample):
        print(f"[{i + 1}/{len(sample)}] Generating Q&A for: {row['title'] or row['foi_reference']}")
        entry = generate_qa(client, row["title"] or "", row["foi_reference"] or "", row["content"])
        if entry:
            questions.append(entry)

    OUTPUT_PATH.write_text(json.dumps(questions, indent=2, ensure_ascii=False))
    print(f"\nDone. {len(questions)} questions written to {OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Verify the script is importable (no syntax errors)**

```bash
uv run python3 -c "import scripts.generate_eval_set"
```
Expected: no output, no errors. (This checks syntax and import resolution only — it does not run `main()`.)

- [ ] **Step 3: Commit**

```bash
git add scripts/generate_eval_set.py
git commit -m "feat: add generate_eval_set script"
```

---

## Task 4: Write `evaluate.py`

Loads `eval/question_set.json`, runs each question through the full pipeline, scores retrieval and faithfulness, writes a timestamped JSONL and prints a summary.

The pipeline mixes async and sync I/O. `vector_search` is natively async (asyncpg). All other blocking calls — `embed_texts` (OpenAI HTTP), `rerank` (Claude HTTP), `generate_answer` (Claude HTTP), `judge_faithfulness` (Claude HTTP) — are synchronous and must be run via `asyncio.to_thread` to avoid blocking the event loop.

**Files:**
- Create: `scripts/evaluate.py`

- [ ] **Step 1: Create `scripts/evaluate.py`**

```python
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import asyncpg
import anthropic
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ingestion.embedder import embed_texts
from src.retrieval.search import vector_search
from src.retrieval.reranker import rerank
from src.retrieval.generator import generate_answer
from scripts.eval_utils import (
    score_retrieval,
    format_chunks_for_prompt,
    parse_judge_response,
    summarise_results,
)

QUESTION_SET_PATH = Path("eval/question_set.json")

FAITHFULNESS_PROMPT = """\
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

Respond in JSON: {{"reason": "...", "score": N}}

Return only the JSON, nothing else."""


def _judge_faithfulness_sync(client: anthropic.Anthropic, question: str, chunks_text: str, answer: str) -> tuple[int, str]:
    """Synchronous faithfulness judge — run via asyncio.to_thread."""
    prompt = FAITHFULNESS_PROMPT.format(question=question, chunks=chunks_text, answer=answer)
    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return parse_judge_response(message.content[0].text.strip())
    except Exception as e:
        return 0, f"judge error: {e}"


async def evaluate_question(pool: asyncpg.Pool, client: anthropic.Anthropic, entry: dict) -> dict:
    question = entry["question"]
    expected_foi = entry["source_foi_reference"]

    # embed_texts is a blocking OpenAI HTTP call — run in a thread
    embedding = await asyncio.to_thread(embed_texts, [question])
    embedding = embedding[0]

    results = await vector_search(embedding, pool, top_k=20)

    # rerank is a blocking Claude HTTP call — run in a thread
    reranked = await asyncio.to_thread(rerank, question, results, 5)

    hit = score_retrieval(expected_foi, reranked)
    retrieved_fois = [r.foi_reference for r in reranked]

    if reranked:
        # generate_answer is a blocking Claude HTTP call — run in a thread
        generated = await asyncio.to_thread(generate_answer, question, reranked)
        answer = generated.answer
        chunks_text = format_chunks_for_prompt(reranked)
        faith_score, faith_reason = await asyncio.to_thread(
            _judge_faithfulness_sync, client, question, chunks_text, answer
        )
    else:
        answer = ""
        faith_score, faith_reason = 0, "no results returned"

    return {
        "question": question,
        "expected_foi": expected_foi,
        "retrieved_fois": retrieved_fois,
        "retrieval_hit": hit,
        "answer": answer,
        "faithfulness_score": faith_score,
        "faithfulness_reason": faith_reason,
        "retrieved_chunks": [
            {
                "foi_reference": r.foi_reference,
                "title": r.title,
                "page_number": r.page_number,
                "content": r.content,
            }
            for r in reranked
        ],
    }


async def main() -> None:
    if not QUESTION_SET_PATH.exists():
        print(f"Question set not found at {QUESTION_SET_PATH}. Run `make generate-eval-set` first.")
        sys.exit(1)

    questions = json.loads(QUESTION_SET_PATH.read_text())
    print(f"Loaded {len(questions)} questions from {QUESTION_SET_PATH}")

    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    client = anthropic.Anthropic()

    records = []
    for i, entry in enumerate(questions):
        print(f"[{i + 1}/{len(questions)}] {entry['question'][:80]}")
        record = await evaluate_question(pool, client, entry)
        hit_str = "HIT" if record["retrieval_hit"] else "MISS"
        print(f"  Retrieval: {hit_str} | Faithfulness: {record['faithfulness_score']}/5")
        records.append(record)

    await pool.close()

    # Write timestamped results file
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M")
    output_path = Path(f"eval/results_{timestamp}.jsonl")
    with output_path.open("w") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"\nResults written to {output_path}")

    # Print summary
    summary = summarise_results(records)
    print(f"\nQuestions:         {summary['total']}")
    print(f"Recall@5:          {summary['recall']:.2f}")
    print(f"Mean faithfulness: {summary['mean_faithfulness']:.1f} / 5")
    if summary["judge_errors"]:
        print(f"Judge errors:      {summary['judge_errors']} (excluded from faithfulness mean)")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Verify the script is importable (no syntax errors)**

```bash
uv run python3 -c "import scripts.evaluate"
```
Expected: no output, no errors. (Checks syntax and import resolution only.)

- [ ] **Step 3: Run the full test suite to confirm nothing is broken**

```bash
uv run pytest -v
```
Expected: all existing tests plus the new `test_eval_utils.py` tests PASS.

- [ ] **Step 4: Commit**

```bash
git add scripts/evaluate.py
git commit -m "feat: add evaluate script"
```

---

## Task 5: End-to-end smoke test

Run the harness against the live database to confirm everything works together.

- [ ] **Step 1: Ensure the database is running and populated**

```bash
make up
```
Confirm documents are indexed:
```bash
docker compose exec db psql -U foi -d foi -c "SELECT COUNT(*) FROM documents;"
```
Expected: non-zero count. If zero, run `make ingest` first.

- [ ] **Step 2: Generate the question set**

```bash
make generate-eval-set
```
Expected: `eval/question_set.json` created with ~50 entries. Inspect a few:
```bash
head -c 500 eval/question_set.json
```

- [ ] **Step 3: Run the evaluator**

```bash
make eval
```
Expected: per-question output with HIT/MISS and faithfulness scores, followed by a summary. A `eval/results_<timestamp>.jsonl` file should appear.

- [ ] **Step 4: Inspect the results file**

```bash
head -n 1 eval/results_*.jsonl | python3 -m json.tool
```
Expected: a single formatted JSON object with all fields present (`question`, `retrieval_hit`, `faithfulness_score`, `retrieved_chunks`, etc.).

- [ ] **Step 5: Commit the question set**

The question set is worth keeping in git as a stable evaluation fixture:
```bash
git add eval/question_set.json
git commit -m "feat: add initial synthetic evaluation question set"
```
