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
