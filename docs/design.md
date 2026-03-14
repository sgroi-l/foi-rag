# FOI RAG System — Production Design & Implementation Plan

## Context

Building a production-grade RAG system over Camden Council Freedom of Information request PDFs (~40 documents, expandable). This replaces a simple prototype (ChromaDB + flat text files) with a robust pipeline backed by pgvector on PostgreSQL, FastAPI, OpenAI embeddings, and Claude for generation. The goal is a system that can be demoed and extended: robust ingestion with idempotency, metadata-filtered retrieval, cited answers, full query logging, and a clean API.

---

## Corpus

Downloaded via `scripts/download_pdfs.py`, which fetches from the [Camden Open Data FOI API](https://opendata.camden.gov.uk/resource/fkj6-gqb4.csv) and saves:

```
camden_foi_random_pdfs/
├── pdfs/                             # 40 PDFs, named e.g. 01_CAM6551_<title>.pdf
└── downloaded_pdf_metadata.csv       # one row per PDF
```

**Metadata CSV columns:** `saved_filename`, `Identifier` (FOI ref e.g. `CAM6551`), `Document Date` (ISO datetime), `Document Title`, `Document Text` (full response letter text), `Document Link`, `Last Uploaded`.

**Key finding:** `Document Text` contains the full response letter for all 40 documents (never null, avg ~3,600 chars). No metadata regex extraction from PDFs is needed — all structured fields come from the CSV. PDFs may contain additional attachments/tables beyond the letter, so PyMuPDF is still used for content extraction.

---

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Vector store | pgvector on PostgreSQL | Required by brief; enables SQL metadata filtering natively |
| Embeddings | OpenAI text-embedding-3-small | Good quality, 1536-dim, consistent with prototype patterns |
| PDF extraction | PyMuPDF | Fast, free, gets tables and attachments beyond the response letter |
| Metadata source | CSV (not regex) | `Identifier`, `Document Date`, `Document Title` are already structured |
| Chunking | Page-based (split if >800 tokens) | Natural citation unit — "document X, page 3" is human-readable |
| Retrieval improvement | Pre-filter by metadata before vector search | Clean SQL WHERE clause, exposed as optional API params |
| Re-ranking | Claude Haiku LLM re-ranker | Implemented in `src/retrieval/reranker.py`; uses Haiku to order candidates by relevance before generation |
| Generation | Claude claude-sonnet-4-6 | Anthropic API required by brief |
| API | FastAPI | Required by brief |

---

## Architecture

```
camden_foi_random_pdfs/
├── pdfs/                    ← PDF files
└── downloaded_pdf_metadata.csv  ← structured metadata
    │
    ▼
[CSV Loader] metadata.py: filename → {foi_reference, date, title, response_text}
    │
    ▼
[Extractor] extractor.py: PyMuPDF → list[(page_num, text)]
    │
    ▼
[Chunker] chunker.py: page-based, split long pages at sentence boundary (max 800 tokens)
    │
    ▼
[Embedder] embedder.py: OpenAI text-embedding-3-small, batched (128/request)
    │
    ▼
[PostgreSQL + pgvector] documents + chunks + ingestion_log + query_logs
    │
    ▼
[FastAPI]
    ├── POST /ingest      → pipeline above (idempotent)
    ├── POST /query       → pre-filter + vector search + Claude → cited answer
    ├── GET  /documents   → list indexed docs
    ├── GET  /logs/{id}   → full query log (chunks retrieved, prompt, response)
    └── GET  /health
```

Docker Compose: two services — `db` (postgres:16 + pgvector) and `api` (FastAPI app).

---

## Database Schema

```sql
-- Document-level metadata (one row per PDF)
CREATE TABLE documents (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename      TEXT NOT NULL UNIQUE,
    foi_reference TEXT,           -- from CSV Identifier column, e.g. "CAM6551"
    date          DATE,           -- from CSV Document Date
    title         TEXT,           -- from CSV Document Title
    response_text TEXT,           -- from CSV Document Text (full response letter)
    total_pages   INT,
    indexed_at    TIMESTAMPTZ DEFAULT now()
);

-- Chunk-level data (one row per page, or sub-chunk if page is long)
CREATE TABLE chunks (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id  UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number  INT NOT NULL,
    chunk_index  INT NOT NULL DEFAULT 0,  -- 0 = whole page, 1+ = sub-chunks
    content      TEXT NOT NULL,
    embedding    VECTOR(1536),
    token_count  INT,
    created_at   TIMESTAMPTZ DEFAULT now()
);

-- HNSW index for cosine similarity
CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops);

-- Idempotency: skip files already ingested, detect changed files
CREATE TABLE ingestion_log (
    filename     TEXT PRIMARY KEY,
    file_hash    TEXT NOT NULL,   -- sha256 of file bytes
    status       TEXT NOT NULL,   -- 'success' | 'failed' | 'processing'
    error        TEXT,
    ingested_at  TIMESTAMPTZ DEFAULT now()
);

-- Full observability for every query
CREATE TABLE query_logs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query               TEXT NOT NULL,
    filters             JSONB,
    retrieved_chunk_ids UUID[],
    prompt_sent         TEXT,
    response            TEXT,
    model               TEXT,
    queried_at          TIMESTAMPTZ DEFAULT now()
);
```

---

## Folder Structure

```
foi-rag/
├── docker-compose.yml
├── .env.example                  # OPENAI_API_KEY, ANTHROPIC_API_KEY, DATABASE_URL
├── pyproject.toml                # uv, python 3.13+, all deps
├── camden_foi_random_pdfs/       # corpus (gitignored)
│   ├── pdfs/
│   └── downloaded_pdf_metadata.csv
├── docs/
│   └── design.md
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
scripts/
    └── ingest_all.py             # CLI: uv run scripts/ingest_all.py ./camden_foi_random_pdfs/
```

---

## API Reference

### `POST /ingest`
```json
// Request
{ "pdfs_dir": "./camden_foi_random_pdfs/pdfs/",
  "metadata_csv": "./camden_foi_random_pdfs/downloaded_pdf_metadata.csv" }

// Response
{ "status": "ok", "ingested": 38, "skipped": 2, "failed": 0 }
```
Skips files whose hash matches ingestion_log. Re-ingests if hash changed.

### `POST /query`
```json
// Request
{
  "query": "What is Camden's policy on temporary accommodation?",
  "top_k": 5,
  "date_from": "2022-01-01",
  "date_to": "2024-12-31"
}

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

### `GET /documents`
Returns list of all indexed documents with metadata.

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

### `GET /logs/{query_id}`
Returns full query log: filters applied, retrieved chunk contents, full prompt sent to Claude, full response.

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

### `GET /health`
Returns `{ "status": "ok" }`.

---

## Implementation Phases

### Phase 1: Infrastructure (Docker + DB)
1. Create `docker-compose.yml` with `pgvector/pgvector:pg16` and `api` services
2. Create `.env.example` with `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DATABASE_URL`
3. Create `pyproject.toml` with deps: `fastapi`, `uvicorn`, `asyncpg`, `openai`, `anthropic`, `pymupdf`, `tiktoken`, `python-dotenv`
4. Write `src/db/schema.sql` — all tables and HNSW index
5. Write `src/db/connection.py` — asyncpg pool
6. Add schema migration step to FastAPI lifespan (run schema.sql on startup if tables don't exist)
7. Verify: `docker compose up`, connect to postgres, confirm tables exist

### Phase 2: Ingestion Pipeline
1. `src/ingestion/metadata.py` — `load_metadata(csv_path) -> dict[str, MetadataRow]` keyed by `saved_filename`; parses ISO date, extracts `Identifier`, `Document Title`, `Document Text`
2. `src/ingestion/extractor.py` — `extract_pages(pdf_path) -> list[tuple[int, str]]` using PyMuPDF
3. `src/ingestion/chunker.py` — `chunk_pages(pages, max_tokens=800) -> list[Chunk]` splitting long pages at sentence boundaries using tiktoken
4. `src/ingestion/embedder.py` — `embed_texts(texts) -> list[list[float]]` using OpenAI, batch size 128
5. `src/ingestion/pipeline.py` — `ingest_file(pdf_path, metadata_row, db_pool)`: sha256 hash check → skip if unchanged → extract → chunk → embed → upsert documents + chunks + log
6. `scripts/ingest_all.py` — load CSV, walk pdfs dir, call `ingest_file` for each
7. Verify: run on all 40 PDFs, check rows in documents + chunks tables, run twice to confirm idempotency

### Phase 3: Retrieval & Generation
1. `src/retrieval/retriever.py` — `retrieve(query_embedding, filters, top_k, db_pool) -> list[ChunkResult]`
   - Build parameterised WHERE clause from filters (`date_from`, `date_to`, `foi_reference`)
   - Use pgvector `ORDER BY embedding <=> $1 LIMIT $2`
2. `src/retrieval/generator.py` — `generate(question, chunks) -> GeneratedAnswer`
   - Number each chunk `[1]...[N]` in context with filename, page, FOI ref
   - Prompt Claude to cite every claim with `[N]`
   - Parse response, map refs back to chunk objects for citations array
3. Verify: run a query end-to-end from Python shell, check citations trace to real PDF pages

### Phase 4: FastAPI & Logging
1. `src/api/models.py` — Pydantic models for all request/response types
2. `src/api/routes/ingest.py` — `POST /ingest`, calls pipeline
3. `src/api/routes/query.py` — `POST /query`: embed question → retrieve → generate → write to query_logs → return
4. `src/api/routes/documents.py` — `GET /documents`, `GET /logs/{id}`
5. `src/api/main.py` — assemble app, lifespan, routers
6. Verify: `curl` all endpoints, confirm cited answers, check query_logs table populated

---

## Metadata Loading

`metadata.py` loads the CSV once at ingestion time and returns a dict keyed by `saved_filename`:

```python
@dataclass
class MetadataRow:
    foi_reference: str        # e.g. "CAM6551"
    date: date | None         # parsed from "2023-12-20T00:00:00.000"
    title: str
    response_text: str        # full letter text from Document Text column
```

All fields are stored in the `documents` table. If a filename is not found in the CSV, ingest proceeds with nulls (never fail on missing metadata).

---

## Chunking Strategy

```
For each page p in document:
    tokens = count_tokens(page_text)
    if tokens <= 800:
        yield Chunk(page=p, chunk_index=0, content=page_text)
    else:
        split into sentences, accumulate until 800 tokens, yield with 1-sentence overlap
        chunk_index increments from 1
```

Citation always uses `(document.filename, page_number)` — chunk_index is stored but not shown to users.

---

## Generation Prompt Template

```
You are an assistant answering questions about Freedom of Information requests
made to Camden Council.

Answer the question using ONLY the provided context chunks. If the context does
not contain enough information, say so. Do not speculate beyond what is in the
documents.

For every claim, cite the source chunk using [N] notation. Every sentence that
makes a factual claim must have a citation.

Context:
[1] Document: 01_CAM6551_asylum seeker accommodation.pdf | Page: 2 | FOI Ref: CAM6551
---
{chunk_1_text}

[2] Document: 03_CAM6854_temporary accommodation.pdf | Page: 1 | FOI Ref: CAM6854
---
{chunk_2_text}

Question: {question}

Answer:
```

---

## Verification Plan

1. **Docker smoke test:** `docker compose up -d` → `GET /health` returns 200 `{"status": "ok"}`
2. **Ingestion idempotency:** run `ingest_all.py` twice → second run: all skipped, 0 failed
3. **Citation traceability:** take `[N]` from an answer → `GET /logs/{query_id}` → find chunk → open PDF page N → text matches
4. **Metadata filtering:** query with `date_from=2023-01-01` → all citation docs dated 2023+
5. **Logging completeness:** `GET /logs/{query_id}` shows full prompt, response, chunk contents

---

## Stretch Goals

- Cross-encoder re-ranking (sentence-transformers) after vector retrieval
- Hybrid search: combine pgvector with PostgreSQL full-text search (`tsvector`)
- Query expansion: Claude reformulates question into multiple search queries before retrieval
- Conversational retrieval: maintain chat history, resolve pronoun references
- Swap corpus: only `src/ingestion/` should need changes for a different document set
