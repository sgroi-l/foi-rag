import os
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

from src.api.routes import documents, ingest, query


def read_schema_sql() -> str:
    schema_path = Path(__file__).parent.parent.parent / "src" / "db" / "schema.sql"
    return schema_path.read_text()


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    async with pool.acquire() as conn:
        await conn.execute(read_schema_sql())
    app.state.pool = pool
    yield
    await pool.close()


app = FastAPI(title="Camden FOI RAG", lifespan=lifespan)

app.include_router(query.router)
app.include_router(documents.router)
app.include_router(ingest.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
