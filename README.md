# Camden FOI RAG

A RAG system over Camden Council Freedom of Information request PDFs, backed by pgvector on PostgreSQL, FastAPI, OpenAI embeddings, and Claude for generation.

See [docs/design.md](docs/design.md) for architecture and [docs/workflow.md](docs/workflow.md) for a full build log.

---

## Setup

```bash
cp .env.example .env   # fill in OPENAI_API_KEY and ANTHROPIC_API_KEY
uv sync
```

---

## Command cheat sheet

### Docker

```bash
# Start the database
docker compose up -d db

# Start everything (db + api)
docker compose up -d

# Stop everything
docker compose down

# Stop and delete the database volume (full reset)
docker compose down -v

# View logs
docker compose logs -f api
docker compose logs -f db
```

### Database

```bash
# Open a psql shell
docker compose exec db psql -U foi -d foi

# Check tables exist
docker compose exec db psql -U foi -d foi -c "\dt"

# Check document and chunk counts
docker compose exec db psql -U foi -d foi -c "SELECT COUNT(*) FROM documents; SELECT COUNT(*) FROM chunks;"

# View recent query logs
docker compose exec db psql -U foi -d foi -c "SELECT query, queried_at FROM query_logs ORDER BY queried_at DESC LIMIT 5;"
```

### Corpus

```bash
# Download 40 FOI PDFs from Camden Open Data (creates camden_foi_random_pdfs/)
uv run python3 scripts/download_pdfs.py

# Ingest all PDFs into the database
uv run python3 scripts/ingest_all.py

# Ingest from a custom corpus directory
uv run python3 scripts/ingest_all.py /path/to/corpus
```

### API

```bash
# Run the API locally (with hot reload)
uv run uvicorn src.api.main:app --reload

# Health check
curl http://localhost:8000/health

# Query
curl -s -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "what enforcement action has Camden taken in the private rented sector?"}' \
  | python3 -m json.tool

# Query with date filter
curl -s -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "temporary accommodation", "date_from": "2023-01-01", "date_to": "2024-12-31"}' \
  | python3 -m json.tool

# List all indexed documents
curl -s http://localhost:8000/documents | python3 -m json.tool

# Get full log for a query (prompt sent, chunks retrieved, response)
curl -s http://localhost:8000/logs/<query_id> | python3 -m json.tool
```

---

## First-time setup walkthrough

```bash
# 1. Start the database
docker compose up -d db

# 2. Download the corpus
uv run python3 scripts/download_pdfs.py

# 3. Ingest
uv run python3 scripts/ingest_all.py

# 4. Start the API
uv run uvicorn src.api.main:app --reload

# 5. Test
curl http://localhost:8000/health
```
