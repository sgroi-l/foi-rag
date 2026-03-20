.PHONY: dev up down reset logs psql download ingest api

# Start db + run API locally with hot reload
dev:
	docker compose up -d db
	uv run uvicorn src.api.main:app --reload

# Start everything in Docker (db + api)
up:
	docker compose up -d

# Stop everything
down:
	docker compose down

# Full reset: stop and delete database volume
reset:
	docker compose down -v

# Follow API logs (use `make logs s=db` for db logs)
logs:
	docker compose logs -f $(or $(s),api)

# Open a psql shell
psql:
	docker compose exec db psql -U foi -d foi

# Download FOI PDFs
download:
	uv run python3 scripts/download_pdfs.py

# Ingest PDFs into the database
ingest:
	uv run python3 scripts/ingest_all.py
