from fastapi import APIRouter

router = APIRouter()


@router.post("/ingest")
async def ingest():
    return {
        "detail": "Use `uv run scripts/ingest_all.py ./camden_foi_random_pdfs/` to ingest documents."
    }
