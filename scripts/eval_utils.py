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
