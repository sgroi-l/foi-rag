.PHONY: dev up down reset logs psql download ingest api generate-eval-set eval generate-prod eval-prod

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

# Generate synthetic evaluation question set locally
generate-eval-set:
	uv run python3 eval/generate_questions.py

# Run the evaluation harness locally
eval:
	uv run python3 scripts/evaluate.py

# Generate eval question set from production k8s DB, copy back locally
generate-prod:
	kubectl exec -n foi-rag deployment/foi-rag-api -- rm -f eval/question_set_v2.json
	kubectl exec -n foi-rag deployment/foi-rag-api -- uv run eval/generate_questions.py
	POD=$$(kubectl get pod -n foi-rag -l app=foi-rag-api -o jsonpath='{.items[0].metadata.name}') && \
		kubectl cp foi-rag/$$POD:/app/eval/question_set_v2.json eval/question_set_v2.json

# Run eval harness on production k8s, copy results back locally
eval-prod:
	kubectl exec -n foi-rag deployment/foi-rag-api -- uv run scripts/evaluate.py
	POD=$$(kubectl get pod -n foi-rag -l app=foi-rag-api -o jsonpath='{.items[0].metadata.name}') && \
		kubectl cp foi-rag/$$POD:/app/eval/ eval/
