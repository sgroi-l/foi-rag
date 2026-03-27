from pathlib import Path

import asyncpg
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from src.api.dashboard_utils import get_corpus_stats, parse_run_file, read_eval_runs

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

EVAL_DIR = Path(__file__).parent.parent.parent.parent / "eval"


@router.get("/health")
async def dashboard_health():
    """Stub health check — confirms dashboard router is wired up."""
    return {"status": "ok"}
