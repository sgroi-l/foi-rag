from pathlib import Path

import asyncpg
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from src.api.dashboard_utils import get_corpus_stats, parse_run_file, read_eval_runs

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

EVAL_DIR = Path(__file__).parent.parent.parent.parent / "eval"


@router.get("")
@router.get("/")
async def overview(request: Request):
    """Overview page: corpus health + latest eval metrics + recall trend."""
    pool: asyncpg.Pool = request.app.state.pool
    corpus = await get_corpus_stats(pool)
    runs = read_eval_runs(EVAL_DIR)
    latest = runs[0] if runs else None
    return templates.TemplateResponse("dashboard/overview.html", {
        "request": request,
        "active": "overview",
        "corpus": corpus,
        "runs": runs,
        "latest": latest,
    })


@router.get("/corpus")
async def corpus(request: Request):
    """Corpus page: document and chunk statistics with size distribution chart."""
    pool: asyncpg.Pool = request.app.state.pool
    stats = await get_corpus_stats(pool)
    return templates.TemplateResponse("dashboard/corpus.html", {
        "request": request,
        "active": "corpus",
        "stats": stats,
    })


@router.get("/eval")
async def eval_page(request: Request):
    """Eval page: recall/faithfulness trend chart, run summary table, run comparison."""
    runs = read_eval_runs(EVAL_DIR)
    return templates.TemplateResponse("dashboard/eval.html", {
        "request": request,
        "active": "eval",
        "runs": runs,
    })


@router.get("/api/eval/{timestamp}")
async def eval_run_json(timestamp: str):
    """Return JSON for a single eval run by timestamp.

    Used by the run-comparison JS in eval.html.
    {timestamp} must match the metadata.timestamp field verbatim,
    e.g. '2026-03-21T09-32-29' (hyphens, not colons).
    Returns 404 if no matching run is found.
    """
    runs = read_eval_runs(EVAL_DIR)
    for run in runs:
        if run["timestamp"] == timestamp:
            return JSONResponse(run)
    raise HTTPException(status_code=404, detail="Run not found")


@router.get("/pipeline")
async def pipeline(request: Request):
    """Pipeline page: configuration from the latest eval run's metadata."""
    runs = read_eval_runs(EVAL_DIR)
    # Find the most recent run that has metadata
    latest_with_meta = next((r for r in runs if r["metadata"]), None)
    return templates.TemplateResponse("dashboard/pipeline.html", {
        "request": request,
        "active": "pipeline",
        "run": latest_with_meta,
    })


@router.get("/explorer")
async def explorer(request: Request):
    """Query Explorer page: live query box that calls the /query endpoint."""
    return templates.TemplateResponse("dashboard/explorer.html", {
        "request": request,
        "active": "explorer",
    })
