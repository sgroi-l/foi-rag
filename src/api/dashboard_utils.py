import json
import sys
from pathlib import Path

import asyncpg

# Project root must be on sys.path for the scripts package to be importable.
# dashboard_utils is loaded as part of the server process, not run directly,
# so the project root is not automatically on sys.path.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.eval_utils import summarise_results


def parse_run_file(path: Path) -> dict:
    """Parse a single eval results JSONL file.

    Returns a dict with keys:
        timestamp (str): from metadata["timestamp"] or derived from filename stem.
        metadata (dict | None): the _type: metadata record, or None if absent.
        records (list[dict]): per-question result dicts.
        summary (dict): recall, mean_faithfulness, etc. via summarise_results().

    If the first line has _type: "metadata", it is consumed as the metadata record
    and all remaining lines are result records. Otherwise metadata is None and all
    lines are treated as result records. Empty files return zeros.
    """
    text = path.read_text().strip()
    filename_timestamp = path.stem.removeprefix("results_")

    if not text:
        return {
            "timestamp": filename_timestamp,
            "metadata": None,
            "records": [],
            "summary": summarise_results([]),
        }

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

    return {
        "timestamp": timestamp,
        "metadata": metadata,
        "records": records,
        "summary": summarise_results(records),
    }


def read_eval_runs(eval_dir: Path) -> list[dict]:
    """Return all eval runs from eval_dir, sorted newest-first.

    Sorts by lexicographic order on timestamp string (YYYY-MM-DDTHH-MM-SS),
    which is equivalent to chronological order for this format.

    Recommended eval_dir resolution from a route handler:
        Path(__file__).parent.parent.parent.parent / "eval"
    """
    files = sorted(eval_dir.glob("results_*.jsonl"), reverse=True)
    return [parse_run_file(f) for f in files]


async def get_corpus_stats(pool: asyncpg.Pool) -> dict:
    """Query the database for corpus statistics.

    Returns:
        doc_count (int): total number of ingested documents.
        chunk_count (int): total number of chunks.
        avg_chunks_per_doc (float): average chunks per document, rounded to 1dp.
        chunk_size_distribution (dict): chunk counts per token_count bucket.
            Buckets: "0-99", "100-199", "200-299", "300-399", "400-499", "500+".
            Only chunks with non-null token_count are included.

    Not unit tested (DB-dependent). Called by Overview and Corpus route handlers
    which pass request.app.state.pool.
    """
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
