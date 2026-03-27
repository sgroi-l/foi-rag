import pytest
from pathlib import Path

from src.api.dashboard_utils import parse_run_file, read_eval_runs

FIXTURES = Path(__file__).parent / "fixtures" / "eval"


# --- parse_run_file ---

def test_parse_run_file_with_metadata():
    run = parse_run_file(FIXTURES / "results_2026-01-01T10-00-00.jsonl")
    assert run["timestamp"] == "2026-01-01T10-00-00"
    assert run["metadata"]["git_sha"] == "abc123"
    assert run["metadata"]["rerank_top_k"] == 5
    assert len(run["records"]) == 2
    assert run["summary"]["total"] == 2
    assert run["summary"]["recall"] == 0.5
    assert run["summary"]["mean_faithfulness"] == 3.5


def test_parse_run_file_without_metadata():
    """First line is a result record — older format. metadata should be None."""
    run = parse_run_file(FIXTURES / "results_2026-01-02T10-00-00.jsonl")
    assert run["timestamp"] == "2026-01-02T10-00-00"
    assert run["metadata"] is None
    assert len(run["records"]) == 1
    assert run["summary"]["recall"] == 1.0


def test_parse_run_file_empty():
    run = parse_run_file(FIXTURES / "results_2026-01-03T10-00-00.jsonl")
    assert run["metadata"] is None
    assert run["records"] == []
    assert run["summary"]["total"] == 0
    assert run["summary"]["recall"] == 0.0


def test_parse_run_file_timestamp_from_filename_when_no_metadata():
    run = parse_run_file(FIXTURES / "results_2026-01-02T10-00-00.jsonl")
    assert run["timestamp"] == "2026-01-02T10-00-00"


# --- read_eval_runs ---

def test_read_eval_runs_returns_all_files():
    runs = read_eval_runs(FIXTURES)
    assert len(runs) == 3


def test_read_eval_runs_sorted_newest_first():
    runs = read_eval_runs(FIXTURES)
    timestamps = [r["timestamp"] for r in runs]
    assert timestamps == sorted(timestamps, reverse=True)
