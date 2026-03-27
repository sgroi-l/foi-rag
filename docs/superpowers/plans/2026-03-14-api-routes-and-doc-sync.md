# API Routes Refactor & Doc Sync Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sync the design doc with reality, refactor all routes into `src/api/routes/`, and implement the two missing endpoints (`GET /documents`, `GET /logs/{query_id}`).

**Architecture:** Pull all Pydantic models into `src/api/models.py` and each logical group of endpoints into its own file under `src/api/routes/`. `main.py` becomes a thin app setup file: lifespan + router registration. Missing endpoints read from `documents` and `query_logs` tables via direct `asyncpg` queries — no new abstraction layer needed.

**Tech Stack:** FastAPI, asyncpg, Pydantic — all already in the project.

---

## Chunk 1: Update design doc

### Task 1: Sync design doc with reality

**Files:**
- Modify: `docs/design.md`

No tests needed — this is a documentation-only task.

- [ ] **Step 1: Fix `/health` response**

In the `### GET /health` section, change:
```
Returns `{ "status": "ok", "chunks_indexed": N }`.
```
to:
```
Returns `{ "status": "ok" }`.
```

Also fix the Verification Plan bullet (line ~326):
```
**Docker smoke test:** `docker compose up -d` → `GET /health` returns 200 with chunk count > 0
```
to:
```
**Docker smoke test:** `docker compose up -d` → `GET /health` returns 200 `{"status": "ok"}`
```

- [ ] **Step 2: Fix `/query` request shape**

Replace the existing `POST /query` request example with the actual shape:
```json
// Request
{
  "query": "What is Camden's policy on temporary accommodation?",
  "top_k": 5,
  "date_from": "2022-01-01",
  "date_to": "2024-12-31"
}
```
(Field is `query` not `question`; filters are top-level not nested; `foi_reference` filter not yet supported.)

- [ ] **Step 3: Fix `/query` response citations shape**

Replace citation fields in the response example:
```json
// Response
{
  "answer": "Camden's policy states... [SOURCE 1].",
  "citations": [
    {
      "foi_reference": "CAM6854",
      "title": "the number of temporary accommodation properties",
      "page_number": 2,
      "chunk_id": "uuid-of-chunk"
    }
  ],
  "query_id": "uuid-to-look-up-full-log"
}
```

- [ ] **Step 4: Update `GET /documents` and `GET /logs/{query_id}` with actual response shapes**

For `GET /documents`, add:
```json
// Response — array of document objects
[
  {
    "id": "uuid",
    "filename": "01_CAM6551_asylum seeker accommodation.pdf",
    "foi_reference": "CAM6551",
    "date": "2023-12-20",
    "title": "Asylum seeker accommodation",
    "total_pages": 4,
    "indexed_at": "2024-01-15T10:30:00Z"
  }
]
```

For `GET /logs/{query_id}`, add:
```json
// Response
{
  "id": "uuid",
  "query": "What is Camden's policy?",
  "filters": {"date_from": "None", "date_to": "None"},
  "retrieved_chunk_ids": ["uuid1", "uuid2"],
  "prompt_sent": "...",
  "response": "...",
  "model": "claude-sonnet-4-6",
  "queried_at": "2024-01-15T10:30:00Z"
}
```

- [ ] **Step 5: Fix Design Decisions table — re-ranking row**

Change:
```
| Re-ranking | Skip (stretch goal) | Metadata filtering is the Day 1 improvement |
```
to:
```
| Re-ranking | Claude Haiku LLM re-ranker | Implemented in `src/retrieval/reranker.py`; uses Haiku to order candidates by relevance before generation |
```

- [ ] **Step 6: Fix Folder Structure section**

Replace the `src/` section with:
```
└── src/
    ├── db/
    │   └── schema.sql            # all CREATE TABLE / INDEX statements (IF NOT EXISTS)
    ├── ingestion/
    │   ├── metadata.py           # load_metadata(csv_path) → dict[filename, MetadataRow]
    │   ├── extractor.py          # PyMuPDF: extract_pages(pdf_path) → list[(page_num, text)]
    │   ├── chunker.py            # chunk_pages(pages, max_tokens=800) → list[Chunk]
    │   ├── embedder.py           # embed_texts(texts) → list[list[float]], batch size 128
    │   └── pipeline.py           # ingest_file(pdf_path, metadata, db_pool)
    ├── retrieval/
    │   ├── search.py             # vector_search(embedding, pool, top_k, filters) → list[SearchResult]
    │   ├── reranker.py           # rerank(query, results, top_k) → list[SearchResult] via Claude Haiku
    │   └── generator.py          # generate_answer(question, chunks) → GeneratedAnswer with citations
    └── api/
        ├── main.py               # FastAPI app, lifespan (DB pool init/close), router registration
        ├── models.py             # Pydantic request/response models
        └── routes/
            ├── query.py          # POST /query
            ├── ingest.py         # POST /ingest
            └── documents.py      # GET /documents, GET /logs/{id}
```

- [ ] **Step 7: Commit**

```bash
git add docs/design.md
git commit -m "docs: sync design.md with actual implementation"
```

---

## Chunk 2: Refactor API into routes

### Task 2: Create `src/api/models.py`

**Files:**
- Create: `src/api/models.py`
- Create: `src/api/routes/__init__.py` (empty)

The current `main.py` has `QueryRequest` and `QueryResponse` inline. Pull them out plus add models for the new endpoints.

- [ ] **Step 1: Write a test for model validation**

Create `tests/test_api_models.py`:
```python
from datetime import date
from src.api.models import QueryRequest, QueryResponse, DocumentRecord, QueryLog


def test_query_request_defaults():
    req = QueryRequest(query="test")
    assert req.top_k == 5
    assert req.date_from is None
    assert req.date_to is None


def test_query_request_with_dates():
    req = QueryRequest(query="test", date_from=date(2023, 1, 1), date_to=date(2024, 12, 31))
    assert req.date_from == date(2023, 1, 1)


def test_document_record_fields():
    doc = DocumentRecord(
        id="uuid",
        filename="file.pdf",
        foi_reference="CAM1234",
        date=date(2023, 1, 1),
        title="Test",
        total_pages=3,
        indexed_at="2024-01-15T10:30:00Z",
    )
    assert doc.foi_reference == "CAM1234"


def test_query_log_fields():
    log = QueryLog(
        id="uuid",
        query="test query",
        filters={"date_from": "None"},
        retrieved_chunk_ids=["id1"],
        prompt_sent="...",
        response="answer",
        model="claude-sonnet-4-6",
        queried_at="2024-01-15T10:30:00Z",
    )
    assert log.model == "claude-sonnet-4-6"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/laurie/ml/foi-rag
uv run pytest tests/test_api_models.py -v
```
Expected: FAIL — `ImportError: cannot import name 'DocumentRecord' from 'src.api.models'`

- [ ] **Step 3: Create `src/api/models.py`**

```python
from datetime import date, datetime
from pydantic import BaseModel


class QueryRequest(BaseModel):
    query: str
    top_k: int = 5
    date_from: date | None = None
    date_to: date | None = None


class CitationItem(BaseModel):
    foi_reference: str
    title: str
    page_number: int
    chunk_id: str


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationItem]
    query_id: str


class DocumentRecord(BaseModel):
    id: str
    filename: str
    foi_reference: str | None
    date: date | None
    title: str | None
    total_pages: int | None
    indexed_at: datetime | None


class QueryLog(BaseModel):
    id: str
    query: str
    filters: dict | None
    retrieved_chunk_ids: list[str] | None
    prompt_sent: str | None
    response: str | None
    model: str | None
    queried_at: datetime | None
```

- [ ] **Step 4: Create `src/api/routes/__init__.py`**

```python
```
(empty file)

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_api_models.py -v
```
Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add src/api/models.py src/api/routes/__init__.py tests/test_api_models.py
git commit -m "feat: add api models and routes package"
```

---

### Task 3: Create `src/api/routes/query.py`

Move the existing `/query` endpoint out of `main.py` into its own module. The logic is unchanged — just relocated.

**Files:**
- Create: `src/api/routes/query.py`
- Modify: `src/api/main.py` (later in Task 6)

- [ ] **Step 1: Create `src/api/routes/query.py`**

```python
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
            json.dumps({"date_from": str(body.date_from), "date_to": str(body.date_to)}),
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
```

Note: pool is read from `request.app.state.pool` (set in lifespan) instead of a module-level global — this avoids import-time coupling and is the idiomatic FastAPI pattern.

- [ ] **Step 2: Commit**

```bash
git add src/api/routes/query.py
git commit -m "feat: move /query endpoint into routes/query.py"
```

---

### Task 4: Create `src/api/routes/documents.py` with `GET /documents` and `GET /logs/{query_id}`

**Files:**
- Create: `src/api/routes/documents.py`
- Create: `tests/test_routes_documents.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_routes_documents.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_mock_pool():
    """Create a test app that bypasses lifespan and uses a mock pool."""
    from fastapi import FastAPI
    from src.api.routes.documents import router

    app = FastAPI()
    app.include_router(router)

    mock_pool = MagicMock()
    app.state.pool = mock_pool
    return app, mock_pool


def test_get_documents_returns_list(app_with_mock_pool):
    app, mock_pool = app_with_mock_pool

    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [
        {
            "id": "abc123",
            "filename": "01_CAM6551_test.pdf",
            "foi_reference": "CAM6551",
            "date": None,
            "title": "Test doc",
            "total_pages": 2,
            "indexed_at": None,
        }
    ]
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    client = TestClient(app)
    resp = client.get("/documents")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert data[0]["filename"] == "01_CAM6551_test.pdf"
    assert data[0]["foi_reference"] == "CAM6551"


def test_get_documents_returns_empty_list(app_with_mock_pool):
    app, mock_pool = app_with_mock_pool

    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = []
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    client = TestClient(app)
    resp = client.get("/documents")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_log_returns_log(app_with_mock_pool):
    app, mock_pool = app_with_mock_pool
    import uuid
    log_id = str(uuid.uuid4())

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "id": log_id,
        "query": "test question",
        "filters": {"date_from": "None", "date_to": "None"},
        "retrieved_chunk_ids": [],
        "prompt_sent": "prompt",
        "response": "answer",
        "model": "claude-sonnet-4-6",
        "queried_at": None,
    }
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    client = TestClient(app)
    resp = client.get(f"/logs/{log_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "test question"
    assert data["model"] == "claude-sonnet-4-6"


def test_get_log_returns_404_when_not_found(app_with_mock_pool):
    app, mock_pool = app_with_mock_pool
    import uuid
    log_id = str(uuid.uuid4())

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = None
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    client = TestClient(app)
    resp = client.get(f"/logs/{log_id}")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_routes_documents.py -v
```
Expected: FAIL — `ImportError: cannot import name 'router' from 'src.api.routes.documents'`

- [ ] **Step 3: Create `src/api/routes/documents.py`**

```python
import asyncpg
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
async def get_log(query_id: str, request: Request):
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
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_routes_documents.py -v
```
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/api/routes/documents.py tests/test_routes_documents.py
git commit -m "feat: add GET /documents and GET /logs/{id} endpoints"
```

---

### Task 5: Create `src/api/routes/ingest.py`

The ingest route currently lives in `main.py` as a call to an external script. Check whether there is an existing `/ingest` endpoint in `main.py` — if not, just create a stub that returns a clear error (actual ingestion is done via `scripts/ingest_all.py`).

**Files:**
- Create: `src/api/routes/ingest.py`

- [ ] **Step 1: Check whether /ingest exists in main.py**

Read `src/api/main.py` and check for a `POST /ingest` route. If it does not exist, create a stub.

- [ ] **Step 2: Create `src/api/routes/ingest.py`**

If no existing `/ingest` implementation exists in `main.py`, create:
```python
from fastapi import APIRouter

router = APIRouter()


@router.post("/ingest")
async def ingest():
    return {
        "detail": "Use `uv run scripts/ingest_all.py ./camden_foi_random_pdfs/` to ingest documents."
    }
```

If an existing implementation exists, move it here (following the same `request.app.state.pool` pattern as Task 3).

- [ ] **Step 3: Commit**

```bash
git add src/api/routes/ingest.py
git commit -m "feat: add /ingest stub route"
```

---

### Task 6: Slim down `main.py` and wire up routers

**Files:**
- Modify: `src/api/main.py`
- Modify: `tests/test_schema_init.py` (if `read_schema_sql` moves)

- [ ] **Step 1: Rewrite `main.py`**

```python
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
```

- [ ] **Step 2: Run existing tests to check nothing broke**

```bash
uv run pytest tests/ -v
```
Expected: all tests that were passing before still pass. `test_schema_init.py` imports `read_schema_sql` from `src.api.main` — that function stays in `main.py` so it should still pass.

- [ ] **Step 3: Smoke test the running app (if server is up)**

```bash
curl http://localhost:8000/health
curl http://localhost:8000/documents
```
Expected:
```json
{"status":"ok"}
[]
```
(empty list if nothing indexed yet)

- [ ] **Step 4: Commit**

```bash
git add src/api/main.py
git commit -m "refactor: move routes into routes/ package, pool via app.state"
```
