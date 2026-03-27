import asyncio
import json
import os
import subprocess
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
    retrieval_metrics,
    format_chunks_for_prompt,
    parse_judge_response,
    summarise_results,
)

QUESTION_SET_PATH = Path(__file__).parent.parent / "eval" / "question_set.json"
RESULTS_DIR = Path(__file__).parent.parent / "eval"
RERANK_TOP_K = 5

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
        text = next(b.text for b in message.content if b.type == "text").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return parse_judge_response(text)
    except Exception as e:
        return 0, f"judge error: {e}"


async def evaluate_question(pool: asyncpg.Pool, client: anthropic.Anthropic, entry: dict) -> dict:
    question = entry.get("question", "")
    expected_foi = entry.get("source_foi_reference", "")

    # embed_texts is a blocking OpenAI HTTP call — run in a thread
    embedding = await asyncio.to_thread(embed_texts, [question])
    embedding = embedding[0]

    results = await vector_search(embedding, pool, top_k=20)

    # rerank is a blocking Claude HTTP call — run in a thread
    reranked = await asyncio.to_thread(rerank, question, results, RERANK_TOP_K)

    metrics = retrieval_metrics(expected_foi, reranked)
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
        "retrieval_hit": metrics.hit,
        "retrieval_precision": metrics.precision,
        "retrieval_rank": metrics.rank,
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
    try:
        for i, entry in enumerate(questions):
            print(f"[{i + 1}/{len(questions)}] {entry.get('question', '?')[:80]}")
            record = await evaluate_question(pool, client, entry)
            hit_str = "HIT" if record["retrieval_hit"] else "MISS"
            print(f"  Retrieval: {hit_str} (rank={record['retrieval_rank']}, prec={record['retrieval_precision']:.2f}) | Faithfulness: {record['faithfulness_score']}/5")
            records.append(record)
    finally:
        await pool.close()

    # Write timestamped results file
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RESULTS_DIR / f"results_{timestamp}.jsonl"

    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except subprocess.CalledProcessError:
        git_sha = "unknown"

    metadata = {
        "_type": "metadata",
        "timestamp": timestamp,
        "git_sha": git_sha,
        "question_set": str(QUESTION_SET_PATH),
        "rerank_top_k": RERANK_TOP_K,
        "models": {
            "judge": "claude-haiku-4-5-20251001",
        },
    }

    with output_path.open("w") as f:
        f.write(json.dumps(metadata, ensure_ascii=False) + "\n")
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"\nResults written to {output_path}")

    # Print summary
    summary = summarise_results(records)
    print(f"\nQuestions:         {summary['total']}")
    print(f"Recall@5:          {summary['recall']:.2f}")
    print(f"Precision@K:       {summary['precision']:.2f}")
    print(f"F1:                {summary['f1']:.2f}")
    print(f"Mean faithfulness: {summary['mean_faithfulness']:.1f} / 5")
    if summary["judge_errors"]:
        print(f"Judge errors:      {summary['judge_errors']} (excluded from faithfulness mean)")


if __name__ == "__main__":
    asyncio.run(main())
