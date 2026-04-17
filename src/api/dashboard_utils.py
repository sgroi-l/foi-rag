import json
from pathlib import Path

import asyncpg


def _summarise(records: list[dict], k: int | None) -> dict:
    if not records:
        return {"total": 0, "avg_precision": 0.0, "avg_recall": 0.0, "mrr": 0.0, "k": k}
    total = len(records)
    return {
        "total": total,
        "avg_precision": sum(r.get("precision", 0.0) for r in records) / total,
        "avg_recall": sum(r.get("recall", 0.0) for r in records) / total,
        "mrr": sum(r.get("rr", 0.0) for r in records) / total,
        "k": k,
    }


def parse_run_file(path: Path) -> dict:
    text = path.read_text().strip()
    filename_timestamp = path.stem.removeprefix("results_")

    if not text:
        return {"timestamp": filename_timestamp, "metadata": None, "records": [], "summary": _summarise([], None)}

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
    k = metadata.get("k") if metadata else None

    return {
        "timestamp": timestamp,
        "metadata": metadata,
        "records": records,
        "summary": _summarise(records, k),
    }


def read_eval_runs(eval_dir: Path) -> list[dict]:
    files = sorted(eval_dir.glob("results_*.jsonl"), reverse=True)
    return [parse_run_file(f) for f in files]


def read_chunk_sweeps(eval_dir: Path) -> list[dict]:
    """Return chunk sweep results, most recent first.

    Each entry: {timestamp, git_sha, k, rows: [{chunk_size, n_chunks, avg_precision, avg_recall, mrr}]}
    """
    sweeps = []
    for path in sorted(eval_dir.glob("chunk_sweep_*.jsonl"), reverse=True):
        lines = path.read_text().strip().splitlines()
        if not lines:
            continue
        meta = json.loads(lines[0])
        rows = [json.loads(l) for l in lines[1:] if l.strip()]
        sweeps.append({
            "timestamp": meta.get("timestamp", path.stem.removeprefix("chunk_sweep_")),
            "git_sha": meta.get("git_sha", ""),
            "k": meta.get("k", 5),
            "rows": rows,
        })
    return sweeps


async def get_corpus_stats(pool: asyncpg.Pool) -> dict:
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
