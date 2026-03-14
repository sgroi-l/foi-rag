import asyncpg
import uuid
from fastapi import APIRouter, HTTPException, Request

from src.api.models import DocumentRecord, QueryLog

router = APIRouter()


@router.get("/documents", response_model=list[DocumentRecord])
async def list_documents(request: Request):
    pool: asyncpg.Pool = request.app.state.pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, filename, foi_reference, date, title, total_pages, indexed_at
               FROM documents
               ORDER BY indexed_at DESC"""
        )
    return [
        DocumentRecord(
            id=str(row["id"]),
            filename=row["filename"],
            foi_reference=row["foi_reference"],
            date=row["date"],
            title=row["title"],
            total_pages=row["total_pages"],
            indexed_at=row["indexed_at"],
        )
        for row in rows
    ]


@router.get("/logs/{query_id}", response_model=QueryLog)
async def get_log(query_id: uuid.UUID, request: Request):
    pool: asyncpg.Pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, query, filters, retrieved_chunk_ids,
                      prompt_sent, response, model, queried_at
               FROM query_logs
               WHERE id = $1""",
            query_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Query log not found")
    return QueryLog(
        id=str(row["id"]),
        query=row["query"],
        filters=row["filters"],
        retrieved_chunk_ids=[str(c) for c in row["retrieved_chunk_ids"]] if row["retrieved_chunk_ids"] else None,
        prompt_sent=row["prompt_sent"],
        response=row["response"],
        model=row["model"],
        queried_at=row["queried_at"],
    )
