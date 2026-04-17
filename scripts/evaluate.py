import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import asyncpg
import numpy as np
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ingestion.chunker import chunk_pages
from src.ingestion.embedder import embed_texts
from src.ingestion.extractor import extract_pages
from src.retrieval.search import vector_search

QUESTION_SET_PATH = Path(__file__).parent.parent / "eval" / "question_set_v2.json"
RESULTS_DIR = Path(__file__).parent.parent / "eval"
CORPUS_DIR = Path(__file__).parent.parent / "camden_foi_random_pdfs"


# --- Metrics (from module) ---

def precision_at_k(retrieved_ids: list[str], relevant_ids: list[str]) -> float:
    retrieved = set(retrieved_ids)
    relevant = set(relevant_ids)
    if not retrieved:
        return 0.0
    return len(retrieved & relevant) / len(retrieved)


def recall_at_k(retrieved_ids: list[str], relevant_ids: list[str]) -> float:
    retrieved = set(retrieved_ids)
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0
    return len(retrieved & relevant) / len(relevant)


def reciprocal_rank(retrieved_ids: list[str], relevant_ids: list[str]) -> float:
    relevant = set(relevant_ids)
    for i, chunk_id in enumerate(retrieved_ids):
        if chunk_id in relevant:
            return 1.0 / (i + 1)
    return 0.0


async def evaluate_retrieval(eval_set: list[dict], retrieve_fn, k: int = 5) -> dict:
    """Run all queries through retrieve_fn and compute metrics.

    retrieve_fn(query, k) -> Awaitable[list[str]]  (chunk IDs, ordered by rank)
    """
    results = []

    for item in eval_set:
        retrieved = await retrieve_fn(item["question"], k)
        relevant = item["relevant_chunk_ids"]

        results.append({
            "question": item["question"],
            "source_foi_reference": item.get("source_foi_reference", ""),
            "precision": precision_at_k(retrieved, relevant),
            "recall": recall_at_k(retrieved, relevant),
            "rr": reciprocal_rank(retrieved, relevant),
            "retrieved": retrieved,
            "relevant": relevant,
        })

    return {
        "per_query": results,
        "avg_precision": float(np.mean([r["precision"] for r in results])),
        "avg_recall": float(np.mean([r["recall"] for r in results])),
        "mrr": float(np.mean([r["rr"] for r in results])),
        "k": k,
    }


# --- Report ---

def print_report(results: dict, label: str = "") -> None:
    if label:
        print(f"\n{'='*60}")
        print(f"  {label}")
        print(f"{'='*60}")

    k = results["k"]
    print(f"\n  k = {k}")
    print(f"  Queries: {len(results['per_query'])}")
    print(f"\n  {'Query':<50} {'P@k':>6} {'R@k':>6} {'RR':>6}")
    print(f"  {'-'*68}")

    for r in results["per_query"]:
        query_short = r["question"][:48]
        print(f"  {query_short:<50} {r['precision']:>6.2f} {r['recall']:>6.2f} {r['rr']:>6.2f}")

    print(f"  {'-'*68}")
    print(f"  {'Average':<50} {results['avg_precision']:>6.2f} {results['avg_recall']:>6.2f} {results['mrr']:>6.2f}")


# --- Retrieval function ---

def make_retrieve_fn(pool: asyncpg.Pool):
    """Returns an async retrieve_fn(query, k) -> list[chunk_id] using vector search."""
    async def retrieve(query: str, k: int) -> list[str]:
        embedding = await asyncio.to_thread(embed_texts, [query])
        results = await vector_search(embedding[0], pool, top_k=k)
        return [str(r.chunk_id) for r in results]
    return retrieve


# --- Experiment 2: chunk size sweep ---

async def fetch_relevant_texts(pool: asyncpg.Pool, eval_set: list[dict]) -> dict[str, str]:
    """Fetch chunk content for all relevant_chunk_ids in the eval set."""
    all_ids = list({cid for item in eval_set for cid in item["relevant_chunk_ids"]})
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id::text, content FROM chunks WHERE id = ANY($1::uuid[])",
            all_ids,
        )
    return {row["id"]: row["content"] for row in rows}


def word_overlap_ratio(text_a: str, text_b: str) -> float:
    """Fraction of the smaller text's words found in the other."""
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / min(len(words_a), len(words_b))


def _build_index_sync(chunk_size: int) -> dict:
    """Re-chunk all PDFs at chunk_size, embed, return in-memory index."""
    pdfs_dir = CORPUS_DIR / "pdfs"
    chunks_meta = []  # (filename, page_number, chunk_index, content)

    for pdf_path in sorted(pdfs_dir.glob("*.pdf")):
        pages = extract_pages(pdf_path)
        for chunk in chunk_pages(pages, max_tokens=chunk_size):
            chunks_meta.append((pdf_path.name, chunk.page_number, chunk.chunk_index, chunk.content))

    texts = [c[3] for c in chunks_meta]
    embeddings = embed_texts(texts)
    matrix = np.array(embeddings, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    normalized = matrix / np.maximum(norms, 1e-10)

    return {"meta": chunks_meta, "texts": texts, "normalized": normalized}


def make_in_memory_retrieve_fn(index: dict):
    """Returns an async retrieve_fn(query, k) -> list[chunk_text]."""
    normalized = index["normalized"]
    texts = index["texts"]

    async def retrieve(query: str, k: int) -> list[str]:
        q_emb = await asyncio.to_thread(embed_texts, [query])
        q_vec = np.array(q_emb[0], dtype=np.float32)
        q_vec /= max(np.linalg.norm(q_vec), 1e-10)
        scores = normalized @ q_vec
        top_idx = np.argsort(scores)[::-1][:k]
        return [texts[i] for i in top_idx]

    return retrieve


async def evaluate_retrieval_by_overlap(
    eval_set: list[dict],
    chunk_id_to_text: dict[str, str],
    retrieve_fn,
    k: int = 5,
    overlap_threshold: float = 0.5,
) -> dict:
    """Evaluate retrieval using word-overlap matching instead of exact chunk IDs."""
    results = []

    for item in eval_set:
        retrieved_texts = await retrieve_fn(item["question"], k)
        relevant_texts = [chunk_id_to_text[cid] for cid in item["relevant_chunk_ids"] if cid in chunk_id_to_text]

        relevance_flags = [
            any(word_overlap_ratio(rt, gt) >= overlap_threshold for gt in relevant_texts)
            for rt in retrieved_texts
        ]

        n_retrieved_relevant = sum(relevance_flags)
        n_gt_covered = sum(
            any(word_overlap_ratio(rt, gt) >= overlap_threshold for rt in retrieved_texts)
            for gt in relevant_texts
        )
        precision = n_retrieved_relevant / k if k > 0 else 0.0
        recall = n_gt_covered / len(relevant_texts) if relevant_texts else 0.0
        rr = next((1.0 / (i + 1) for i, r in enumerate(relevance_flags) if r), 0.0)

        results.append({"question": item["question"], "precision": precision, "recall": recall, "rr": rr})

    return {
        "per_query": results,
        "avg_precision": float(np.mean([r["precision"] for r in results])),
        "avg_recall": float(np.mean([r["recall"] for r in results])),
        "mrr": float(np.mean([r["rr"] for r in results])),
        "k": k,
    }


# --- Main ---

async def main() -> None:
    if not QUESTION_SET_PATH.exists():
        print(f"Question set not found: {QUESTION_SET_PATH}")
        sys.exit(1)

    eval_set = json.loads(QUESTION_SET_PATH.read_text())
    print(f"Loaded {len(eval_set)} questions from {QUESTION_SET_PATH.name}")

    k = int(sys.argv[1]) if len(sys.argv) > 1 else 5

    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])

    try:
        retrieve_fn = make_retrieve_fn(pool)
        output = await evaluate_retrieval(eval_set, retrieve_fn, k=k)

        print_report(output, label=f"Baseline: vector search k={k}")

        # Save results
        timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        output_path = RESULTS_DIR / f"results_{timestamp}.jsonl"

        try:
            git_sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
        except subprocess.CalledProcessError:
            git_sha = "unknown"

        metadata = {
            "_type": "metadata",
            "timestamp": timestamp,
            "git_sha": git_sha,
            "question_set": QUESTION_SET_PATH.name,
            "k": k,
        }

        with output_path.open("w") as f:
            f.write(json.dumps(metadata) + "\n")
            for r in output["per_query"]:
                f.write(json.dumps(r) + "\n")

        print(f"\nResults written to {output_path}")

        print("\nExperiment 1: Varying k")
        print(f"\n  {'k':>4} | {'Avg P@k':>8} | {'Avg R@k':>8} | {'MRR':>6}")
        print(f"  {'-'*36}")

        for k in [1, 3, 5, 10, 20]:
            results = await evaluate_retrieval(eval_set, retrieve_fn, k=k)
            print(f"  {k:>4} | {results['avg_precision']:>8.3f} | {results['avg_recall']:>8.3f} | {results['mrr']:>6.3f}")

        print("\nExperiment 2: Varying chunk size")
        print("  (re-chunking + re-embedding PDFs for each size; relevance via word overlap)")
        print(f"\n  {'Chunk size':>10} | {'Chunks':>7} | {'Avg P@5':>8} | {'Avg R@5':>8} | {'MRR':>6}")
        print(f"  {'-'*48}")

        chunk_id_to_text = await fetch_relevant_texts(pool, eval_set)

        sweep_rows = []
        for size in [128, 256, 512, 1024]:
            print(f"  Building index for chunk_size={size}...", end=" ", flush=True)
            index = await asyncio.to_thread(_build_index_sync, size)
            print(f"{len(index['texts'])} chunks embedded.")
            in_mem_fn = make_in_memory_retrieve_fn(index)
            results = await evaluate_retrieval_by_overlap(eval_set, chunk_id_to_text, in_mem_fn, k=5)
            n = len(index["texts"])
            print(f"  {size:>10} | {n:>7} | {results['avg_precision']:>8.3f} | {results['avg_recall']:>8.3f} | {results['mrr']:>6.3f}")
            sweep_rows.append({
                "chunk_size": size,
                "n_chunks": n,
                "avg_precision": results["avg_precision"],
                "avg_recall": results["avg_recall"],
                "mrr": results["mrr"],
            })

        sweep_path = RESULTS_DIR / f"chunk_sweep_{timestamp}.jsonl"
        with sweep_path.open("w") as f:
            f.write(json.dumps({"_type": "chunk_sweep_metadata", "timestamp": timestamp, "git_sha": git_sha, "k": 5}) + "\n")
            for row in sweep_rows:
                f.write(json.dumps(row) + "\n")
        print(f"\nChunk sweep results written to {sweep_path}")

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
