# K8s Deployment Design — foi-rag

**Date:** 2026-03-13
**Status:** Approved

## Overview

Deploy the foi-rag FastAPI application to a fresh Hetzner CX33 server (`135.181.255.239`) using k3s Kubernetes, following the FAC Bare Metal to Kubernetes guide. The app will be accessible at `https://foi-rag.sgroi.dev` with automatic HTTPS via Let's Encrypt.

## Context

- **Server:** Hetzner CX33 (4 vCPU, 8GB RAM), fresh Ubuntu install, IP `135.181.255.239`
- **Domain:** `foi-rag.sgroi.dev` (DNS managed via Cloudflare, A record to be added manually)
- **Docker Hub:** `sgroil`
- **Reference repo:** `fac-ml-voice-agent` — existing k8s manifests and CI/CD pipeline used as pattern
- **Guide followed:** FAC "Deploying to Kubernetes Guide" — "Deploy an App to Kubernetes from Scratch" path

## Architecture

Single namespace `foi-rag` containing:

| Component | Kind | Image | Exposed |
|---|---|---|---|
| `foi-rag-api` | Deployment | `sgroil/foi-rag-api:{sha}` | Yes — via Ingress |
| `foi-rag-db` | Deployment + PVC | `pgvector/pgvector:pg16` | No — ClusterIP only |
| `foi-rag-ingest` | Job (manual) | `sgroil/foi-rag-api:{sha}` | No |

The same Docker image is reused for both the API and the ingestion Job; only the command differs.

## Components

### Dockerfile

Single-stage build at the repo root using Python 3.13 slim + uv. Pin the uv version for reproducibility:

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.6.6 /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
CMD ["uv", "run", "uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

A `.dockerignore` at the repo root excludes `.venv`, `__pycache__`, `.env*`, `camden_foi_random_pdfs/`, `.git`, `.DS_Store`.

Note: `camden_foi_random_pdfs/` is excluded from the image. The ingestion Job downloads PDFs at runtime into the container's ephemeral filesystem (`/app/camden_foi_random_pdfs/`), then ingests them into the database. Both scripts use hardcoded relative paths resolved against the process working directory (`/app`, set by `WORKDIR`). Both steps run sequentially in the same container, so no persistent volume is needed for the PDFs.

### Schema Initialisation (required code change)

`src/api/main.py` **must be modified** — the lifespan function needs to read `src/db/schema.sql` and execute it against the connection pool on startup, before yielding. Currently the lifespan only creates the pool. The schema uses `CREATE TABLE IF NOT EXISTS` throughout, making this idempotent and safe on every pod restart. Without this change the app will crash on first query because the tables don't exist.

Note: `schema.sql` also runs `CREATE EXTENSION IF NOT EXISTS vector`. This requires superuser privileges in PostgreSQL. The `POSTGRES_USER` env var in the official postgres/pgvector Docker image creates that user as the database superuser, so the `foi` user will have the required privilege. No separate init step is needed.

### Kubernetes Manifests

**`k8s/` — applied by CI/CD on every deploy:**

- **`db-pvc.yml`** — 5Gi PersistentVolumeClaim for pgvector data, `ReadWriteOnce`.
- **`db-deployment.yml`** — `pgvector/pgvector:pg16`, mounts PVC at `/var/lib/postgresql/data` with `subPath: pgdata`, reads `db-secrets`, `pg_isready` liveness/readiness probes.
- **`db-service.yml`** — ClusterIP, port 5432, named `foi-rag-db`. Used as hostname in `DATABASE_URL`.
- **`api-deployment.yml`** — `sgroil/foi-rag-api:latest` as placeholder (overridden to `{sha}` by CI/CD on every deploy). Container name must be `foi-rag-api` (this name is used in the `kubectl set image` command). `imagePullPolicy: Always`. Reads `app-secrets`. Liveness/readiness on `GET /health` port 8000. Resources: 500m CPU / 1Gi memory requests, 1 CPU / 2Gi limits.
- **`api-service.yml`** — ClusterIP, `port: 80` → `targetPort: 8000`.
- **`ingress.yml`** — Host `foi-rag.sgroi.dev`, annotation `cert-manager.io/cluster-issuer: letsencrypt-prod`, TLS secret `foi-rag-tls`, backend `foi-rag-api` service on port 80.
- **`cluster-issuer.yml`** — ACME ClusterIssuer `letsencrypt-prod` with email `laurie@agile.coop`, http01 solver via Traefik ingress class.

**`k8s/jobs/` — applied manually, NOT included in CI/CD `kubectl apply -f k8s/`:**

- **`ingestion-job.yml`** — One-off Job. Uses `sgroil/foi-rag-api:latest`, `imagePullPolicy: Always`. Overrides command using shell form so `&&` is interpreted by the shell:
  ```yaml
  command: ["/bin/sh", "-c"]
  args: ["uv run scripts/download_pdfs.py && uv run scripts/ingest_all.py"]
  ```
  Reads `app-secrets`. `restartPolicy: Never`.

The `k8s/jobs/` subdirectory is intentionally excluded from the `kubectl apply -f k8s/` CI step — Jobs are not idempotent and must be deleted before re-applying. Keeping them separate prevents CI from erroring on an existing completed Job.

### Secrets

Created manually on the server before first deploy:

```bash
kubectl create secret generic db-secrets \
  --namespace foi-rag \
  --from-literal=POSTGRES_USER=foi \
  --from-literal=POSTGRES_PASSWORD=<secure-password> \
  --from-literal=POSTGRES_DB=foi

kubectl create secret generic app-secrets \
  --namespace foi-rag \
  --from-literal=DATABASE_URL=postgresql://foi:<secure-password>@foi-rag-db:5432/foi \
  --from-literal=OPENAI_API_KEY=<key> \
  --from-literal=ANTHROPIC_API_KEY=<key>
```

### CI/CD (`.github/workflows/deploy.yml`)

Triggers on push to `main`. Runs independently of `test.yml` (tests also run on main push in parallel — same pattern as `fac-ml-voice-agent`). Steps:

1. Checkout
2. Docker Hub login (`DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` secrets)
3. Build and push `sgroil/foi-rag-api:{github.sha}` from repo root
4. Decode `KUBECONFIG_DATA` → `~/.kube/config`
5. `kubectl apply -f k8s/` — creates or updates all non-Job resources. On first deploy this creates the API deployment; on subsequent deploys it's a no-op for unchanged manifests. Does NOT apply `k8s/jobs/`.
6. `kubectl set image deployment/foi-rag-api foi-rag-api=sgroil/foi-rag-api:{github.sha} --namespace foi-rag` — container name `foi-rag-api` must match the `name:` field in `api-deployment.yml`.
7. `kubectl rollout status deployment/foi-rag-api --namespace foi-rag --timeout=120s`

The DB and ingestion Job are not managed by CI/CD.

## Deployment Runbook

Saved as `docs/deployment-runbook.md`. Full ordered checklist:

### One-time server setup

- [ ] SSH in as root: `ssh root@135.181.255.239`
- [ ] Create `deploy` user with passwordless sudo, copy SSH key, test login
- [ ] Harden SSH: disable root login, disable password auth, restart sshd
- [ ] Open firewall: `ufw allow 22,80,443,6443/tcp && ufw enable`
- [ ] Install Docker: `curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker deploy`
- [ ] Log out and back in as `deploy` to activate docker group
- [ ] Install k3s: `curl -sfL https://get.k3s.io | sh -`
- [ ] Configure kubectl for deploy user:
  ```bash
  mkdir -p ~/.kube
  sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
  sudo chown deploy:deploy ~/.kube/config
  echo 'export KUBECONFIG=~/.kube/config' >> ~/.bashrc
  export KUBECONFIG=~/.kube/config
  ```
- [ ] Verify: `kubectl get nodes` — should show one node as Ready
- [ ] Install cert-manager: `kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.14.4/cert-manager.yaml`
- [ ] Wait for cert-manager pods: `kubectl get pods -n cert-manager --watch` (all three Running)
- [ ] Apply ClusterIssuer: `kubectl apply -f k8s/cluster-issuer.yml`

### Per-deploy setup (first time only)

- [ ] Add DNS A record in Cloudflare: `foi-rag.sgroi.dev` → `135.181.255.239`
- [ ] Add GitHub repo secrets: `DOCKERHUB_USERNAME=sgroil`, `DOCKERHUB_TOKEN`, `KUBECONFIG_DATA`
  - Get kubeconfig: `sudo cat /etc/rancher/k3s/k3s.yaml | sed "s/127.0.0.1/135.181.255.239/" | base64 -w 0`
- [ ] SSH to server: `kubectl create namespace foi-rag`
- [ ] Create `db-secrets` and `app-secrets` (see Secrets section above)
- [ ] Apply DB manifests first (so DB is ready before API starts):
  ```bash
  kubectl apply -f k8s/db-pvc.yml
  kubectl apply -f k8s/db-deployment.yml
  kubectl apply -f k8s/db-service.yml
  ```
- [ ] Push to `main` — CI/CD builds image, applies all `k8s/` manifests, rolls out API
- [ ] Wait for certificate: `kubectl get certificate -n foi-rag --watch` (READY = True)
- [ ] Verify API is live: `curl https://foi-rag.sgroi.dev/health` → `{"status":"ok"}`

### Initial data load

- [ ] Apply ingestion job: `kubectl apply -f k8s/jobs/ingestion-job.yml`
- [ ] Monitor: `kubectl logs -f job/foi-rag-ingest -n foi-rag`
- [ ] Check job completed successfully: `kubectl get job foi-rag-ingest -n foi-rag`
- [ ] Verify data is queryable: `curl -X POST https://foi-rag.sgroi.dev/query -H "Content-Type: application/json" -d '{"query":"test"}'`

### Re-ingestion (when Camden publishes new FOI docs)

- [ ] Delete old job: `kubectl delete job foi-rag-ingest -n foi-rag`
- [ ] Re-apply: `kubectl apply -f k8s/jobs/ingestion-job.yml`
- [ ] Monitor: `kubectl logs -f job/foi-rag-ingest -n foi-rag`

## Files Changed / Created

| Path | Action |
|---|---|
| `Dockerfile` | Create |
| `.dockerignore` | Create |
| `src/api/main.py` | **Modify** — add schema init to lifespan (required, currently missing) |
| `k8s/cluster-issuer.yml` | Create |
| `k8s/api-deployment.yml` | Create |
| `k8s/api-service.yml` | Create |
| `k8s/db-deployment.yml` | Create |
| `k8s/db-service.yml` | Create |
| `k8s/db-pvc.yml` | Create |
| `k8s/ingress.yml` | Create |
| `k8s/jobs/ingestion-job.yml` | Create |
| `.github/workflows/deploy.yml` | Create |
| `docs/deployment-runbook.md` | Create |
