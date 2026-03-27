import json
from dataclasses import dataclass
from src.retrieval.search import SearchResult


@dataclass
class RetrievalMetrics:
    hit: bool
    precision: float   # 1/n_unique_returned if hit, else 0.0; 0.0 if nothing returned
    rank: int | None   # 1-based rank of expected FOI among unique FOIs; None if not found


def retrieval_metrics(expected_foi: str, retrieved_results: list[SearchResult]) -> RetrievalMetrics:
    """Compute document-level retrieval metrics for a single question.

    Deduplicates on foi_reference (preserving order) before computing metrics.
    Precision denominator is the actual number of unique documents returned.
    """
    seen: list[str] = []
    for r in retrieved_results:
        if r.foi_reference not in seen:
            seen.append(r.foi_reference)

    if not seen:
        return RetrievalMetrics(hit=False, precision=0.0, rank=None)

    try:
        rank = seen.index(expected_foi) + 1
        return RetrievalMetrics(hit=True, precision=1 / len(seen), rank=rank)
    except ValueError:
        return RetrievalMetrics(hit=False, precision=0.0, rank=None)


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
    Valid scores are 1–5; scores outside this range return (0, "invalid score: ...").
    """
    try:
        data = json.loads(text)
        score = int(data.get("score", 0))
        if not (1 <= score <= 5):
            return 0, f"invalid score: {score}"
        reason = str(data.get("reason", ""))
        return score, reason
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        return 0, f"parse error: {e}"


def summarise_results(records: list[dict]) -> dict:
    """Compute recall, precision, F1, and mean faithfulness from per-question result dicts.

    Records with faithfulness_score == 0 are excluded from the faithfulness mean.
    Records missing retrieval_precision (old format) default to 0.0 for backward compat.
    Uses safe dict access (.get) to handle malformed records gracefully.
    """
    if not records:
        return {
            "total": 0,
            "recall": 0.0,
            "precision": 0.0,
            "f1": 0.0,
            "mean_faithfulness": 0.0,
            "judge_errors": 0,
        }

    total = len(records)
    hits = sum(1 for r in records if r.get("retrieval_hit", False))
    recall = hits / total
    mean_precision = sum(r.get("retrieval_precision", 0.0) for r in records) / total
    f1 = (
        2 * mean_precision * recall / (mean_precision + recall)
        if (mean_precision + recall) > 0
        else 0.0
    )

    scoreable = [r for r in records if r.get("faithfulness_score", 0) > 0]
    judge_errors = total - len(scoreable)
    mean_faith = (
        sum(r.get("faithfulness_score", 0) for r in scoreable) / len(scoreable)
        if scoreable
        else 0.0
    )

    return {
        "total": total,
        "recall": recall,
        "precision": mean_precision,
        "f1": f1,
        "mean_faithfulness": mean_faith,
        "judge_errors": judge_errors,
    }
