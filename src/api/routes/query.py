import json

import asyncpg
from fastapi import APIRouter, HTTPException, Request

from src.api.models import CitationItem, QueryRequest, QueryResponse
from src.ingestion.embedder import embed_texts
from src.retrieval.generator import generate_answer
from src.retrieval.reranker import rerank
from src.retrieval.search import vector_search

router = APIRouter()


@router.post("/query", response_model=QueryResponse)
async def query(request: Request, body: QueryRequest):
    pool: asyncpg.Pool = request.app.state.pool

    embedding = embed_texts([body.query])[0]
    results = await vector_search(
        embedding, pool, top_k=20,
        date_from=body.date_from,
        date_to=body.date_to,
    )
    if not results:
        raise HTTPException(status_code=404, detail="No relevant documents found")

    reranked = rerank(body.query, results, top_k=body.top_k)
    answer = generate_answer(body.query, reranked)

    async with pool.acquire() as conn:
        query_id = await conn.fetchval(
            """INSERT INTO query_logs
               (query, filters, retrieved_chunk_ids, prompt_sent, response, model)
               VALUES ($1, $2, $3, $4, $5, $6)
               RETURNING id""",
            body.query,
            json.dumps({"date_from": body.date_from.isoformat() if body.date_from else None, "date_to": body.date_to.isoformat() if body.date_to else None}),
            [c.chunk_id for c in answer.citations],
            answer.prompt_sent,
            answer.answer,
            "claude-sonnet-4-6",
        )

    return QueryResponse(
        answer=answer.answer,
        citations=[
            CitationItem(
                foi_reference=c.foi_reference,
                title=c.title,
                page_number=c.page_number,
                chunk_id=c.chunk_id,
            )
            for c in answer.citations
        ],
        query_id=str(query_id),
    )
