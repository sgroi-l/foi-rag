# K8s Deployment Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the foi-rag FastAPI + pgvector app to a fresh Hetzner CX33 server using k3s Kubernetes with automated CI/CD and HTTPS.

**Architecture:** Single `foi-rag` namespace on k3s with a FastAPI deployment (built from a custom Docker image), a pgvector/pgvector:pg16 database deployment with persistent storage, and a manually-applied ingestion Job that downloads and ingests FOI PDFs. CI/CD via GitHub Actions builds and pushes the image on every push to main and rolls it out with zero downtime.

**Tech Stack:** Python 3.13, uv, FastAPI, asyncpg, pgvector, k3s, Traefik, cert-manager, Docker Hub, GitHub Actions

**Spec:** `docs/superpowers/specs/2026-03-13-k8s-deployment-design.md`

---

## Chunk 1: Dockerise the app

### Task 1: Create .dockerignore

**Files:**
- Create: `.dockerignore`

- [ ] **Step 1: Create `.dockerignore` at repo root**

```
.venv
__pycache__
*.pyc
.env*
camden_foi_random_pdfs/
.git
.DS_Store
.pytest_cache
```

- [ ] **Step 2: Commit**

```bash
git add .dockerignore
git commit -m "chore: add .dockerignore"
```

---

### Task 2: Create Dockerfile

**Files:**
- Create: `Dockerfile`

- [ ] **Step 1: Create `Dockerfile` at repo root**

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.6.6 /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
CMD ["uv", "run", "uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Build the image locally to verify it compiles**

```bash
docker build -t foi-rag-api:local .
```

Expected: build succeeds, no errors. The final layer copies all source files.

- [ ] **Step 3: Smoke-test the image starts (without a real DB — just confirm it imports)**

```bash
docker run --rm -e DATABASE_URL=postgresql://x:x@localhost/x \
  -e OPENAI_API_KEY=x -e ANTHROPIC_API_KEY=x \
  foi-rag-api:local uv run python -c "from src.api.main import app; print('ok')"
```

Expected: prints `ok` (import succeeds; no DB connection attempted at import time).

- [ ] **Step 4: Commit**

```bash
git add Dockerfile
git commit -m "chore: add Dockerfile for FastAPI app"
```

---

## Chunk 2: Schema initialisation

The lifespan in `src/api/main.py` currently only creates the asyncpg pool. It must also apply `src/db/schema.sql` on startup so the database tables and pgvector extension exist before any request is handled.

### Task 3: Extract schema reader and write failing test

**Files:**
- Modify: `src/api/main.py`
- Create: `tests/test_schema_init.py`

- [ ] **Step 1: Write a failing test for the schema reader**

Create `tests/test_schema_init.py`:

```python
from pathlib import Path
from src.api.main import read_schema_sql


def test_read_schema_sql_returns_string():
    sql = read_schema_sql()
    assert isinstance(sql, str)
    assert len(sql) > 0


def test_read_schema_sql_contains_expected_tables():
    sql = read_schema_sql()
    assert "CREATE TABLE IF NOT EXISTS documents" in sql
    assert "CREATE TABLE IF NOT EXISTS chunks" in sql
    assert "CREATE TABLE IF NOT EXISTS query_logs" in sql
    assert "CREATE TABLE IF NOT EXISTS ingestion_log" in sql


def test_read_schema_sql_contains_vector_extension():
    sql = read_schema_sql()
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_schema_init.py -v
```

Expected: FAIL — `ImportError: cannot import name 'read_schema_sql' from 'src.api.main'`

---

### Task 4: Implement schema reader and lifespan update

**Files:**
- Modify: `src/api/main.py`

- [ ] **Step 1: Add `read_schema_sql` and update the lifespan in `src/api/main.py`**

Add this function after the imports (before the `pool` global):

```python
def read_schema_sql() -> str:
    schema_path = Path(__file__).parent.parent.parent / "src" / "db" / "schema.sql"
    return schema_path.read_text()
```

Update the lifespan to execute the schema on startup:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    async with pool.acquire() as conn:
        await conn.execute(read_schema_sql())
    yield
    await pool.close()
```

Also add `from pathlib import Path` to the imports if not already present (it isn't currently).

- [ ] **Step 2: Run the tests to verify they pass**

```bash
uv run pytest tests/test_schema_init.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 3: Run the full test suite to check nothing is broken**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add src/api/main.py tests/test_schema_init.py
git commit -m "feat: apply schema on API startup via lifespan"
```

---

## Chunk 3: Kubernetes manifests — database tier

### Task 5: Create database manifests

**Files:**
- Create: `k8s/db-pvc.yml`
- Create: `k8s/db-deployment.yml`
- Create: `k8s/db-service.yml`

- [ ] **Step 1: Create `k8s/db-pvc.yml`**

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: foi-rag-db-pvc
  namespace: foi-rag
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 5Gi
```

- [ ] **Step 2: Create `k8s/db-deployment.yml`**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: foi-rag-db
  namespace: foi-rag
spec:
  replicas: 1
  selector:
    matchLabels:
      app: foi-rag-db
  template:
    metadata:
      labels:
        app: foi-rag-db
    spec:
      containers:
        - name: foi-rag-db
          image: pgvector/pgvector:pg16
          ports:
            - containerPort: 5432
          envFrom:
            - secretRef:
                name: db-secrets
          volumeMounts:
            - name: db-data
              mountPath: /var/lib/postgresql/data
              subPath: pgdata
          livenessProbe:
            exec:
              command:
                - pg_isready
                - -U
                - foi
            initialDelaySeconds: 10
            periodSeconds: 15
          readinessProbe:
            exec:
              command:
                - pg_isready
                - -U
                - foi
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 768Mi
      volumes:
        - name: db-data
          persistentVolumeClaim:
            claimName: foi-rag-db-pvc
```

- [ ] **Step 3: Create `k8s/db-service.yml`**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: foi-rag-db
  namespace: foi-rag
spec:
  type: ClusterIP
  selector:
    app: foi-rag-db
  ports:
    - port: 5432
      targetPort: 5432
```

- [ ] **Step 4: Commit**

```bash
git add k8s/db-pvc.yml k8s/db-deployment.yml k8s/db-service.yml
git commit -m "chore: add k8s database manifests (pgvector)"
```

---

## Chunk 4: Kubernetes manifests — API, ingress, cluster issuer

### Task 6: Create API manifests

**Files:**
- Create: `k8s/api-deployment.yml`
- Create: `k8s/api-service.yml`

- [ ] **Step 1: Create `k8s/api-deployment.yml`**

Note: the image tag `latest` is a placeholder — CI/CD overwrites it with the exact git SHA on every deploy using `kubectl set image`.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: foi-rag-api
  namespace: foi-rag
spec:
  replicas: 1
  selector:
    matchLabels:
      app: foi-rag-api
  template:
    metadata:
      labels:
        app: foi-rag-api
    spec:
      containers:
        - name: foi-rag-api
          image: sgroil/foi-rag-api:latest
          imagePullPolicy: Always
          ports:
            - containerPort: 8000
          envFrom:
            - secretRef:
                name: app-secrets
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 15
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              cpu: 500m
              memory: 1Gi
            limits:
              cpu: "1"
              memory: 2Gi
```

- [ ] **Step 2: Create `k8s/api-service.yml`**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: foi-rag-api
  namespace: foi-rag
spec:
  type: ClusterIP
  selector:
    app: foi-rag-api
  ports:
    - port: 80
      targetPort: 8000
```

- [ ] **Step 3: Commit**

```bash
git add k8s/api-deployment.yml k8s/api-service.yml
git commit -m "chore: add k8s API deployment and service manifests"
```

---

### Task 7: Create ingress and cluster issuer

**Files:**
- Create: `k8s/ingress.yml`
- Create: `k8s/cluster-issuer.yml`

- [ ] **Step 1: Create `k8s/ingress.yml`**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: foi-rag
  namespace: foi-rag
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  rules:
    - host: foi-rag.sgroi.dev
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: foi-rag-api
                port:
                  number: 80
  tls:
    - hosts:
        - foi-rag.sgroi.dev
      secretName: foi-rag-tls
```

- [ ] **Step 2: Create `k8s/cluster-issuer.yml`**

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: laurie@agile.coop
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
      - http01:
          ingress:
            class: traefik
```

- [ ] **Step 3: Commit**

```bash
git add k8s/ingress.yml k8s/cluster-issuer.yml
git commit -m "chore: add k8s ingress and Let's Encrypt cluster issuer"
```

---

## Chunk 5: Ingestion Job manifest

The ingestion Job lives in `k8s/jobs/` — separate from `k8s/` — so CI/CD's `kubectl apply -f k8s/` does not accidentally apply it. Jobs are not idempotent (a completed Job cannot be re-applied without deleting first).

### Task 8: Create ingestion job manifest

**Files:**
- Create: `k8s/jobs/ingestion-job.yml`

- [ ] **Step 1: Create `k8s/jobs/ingestion-job.yml`**

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: foi-rag-ingest
  namespace: foi-rag
spec:
  template:
    spec:
      containers:
        - name: foi-rag-ingest
          image: sgroil/foi-rag-api:latest
          imagePullPolicy: Always
          command: ["/bin/sh", "-c"]
          args:
            - "uv run scripts/download_pdfs.py && uv run scripts/ingest_all.py"
          envFrom:
            - secretRef:
                name: app-secrets
          resources:
            requests:
              cpu: 500m
              memory: 1Gi
            limits:
              cpu: "1"
              memory: 2Gi
      restartPolicy: Never
  backoffLimit: 0
```

Note: `backoffLimit: 0` means the Job will not retry on failure. This prevents re-downloading and re-ingesting from a partial state. Check logs and re-apply manually if it fails.

The ingestion command runs in `/app` (the Dockerfile `WORKDIR`). `download_pdfs.py` writes PDFs to `/app/camden_foi_random_pdfs/pdfs/` and the metadata CSV to `/app/camden_foi_random_pdfs/downloaded_pdf_metadata.csv`. `ingest_all.py` reads from the same default path. Both resolve relative to `/app`.

- [ ] **Step 2: Commit**

```bash
git add k8s/jobs/ingestion-job.yml
git commit -m "chore: add k8s ingestion Job manifest"
```

---

## Chunk 6: CI/CD workflow and deployment runbook

### Task 9: Create GitHub Actions deploy workflow

**Files:**
- Create: `.github/workflows/deploy.yml`

- [ ] **Step 1: Create `.github/workflows/deploy.yml`**

```yaml
name: Deploy

on:
  push:
    branches:
      - main

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Log in to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}

      - name: Build and push image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ${{ secrets.DOCKERHUB_USERNAME }}/foi-rag-api:${{ github.sha }}

      - name: Set up kubectl
        uses: azure/setup-kubectl@v3

      - name: Configure kubeconfig
        run: |
          mkdir -p ~/.kube
          echo "${{ secrets.KUBECONFIG_DATA }}" | base64 -d > ~/.kube/config

      - name: Apply manifests
        run: kubectl apply -f k8s/

      - name: Update image
        run: |
          kubectl set image deployment/foi-rag-api \
            foi-rag-api=${{ secrets.DOCKERHUB_USERNAME }}/foi-rag-api:${{ github.sha }} \
            --namespace foi-rag

      - name: Wait for rollout
        run: |
          kubectl rollout status deployment/foi-rag-api \
            --namespace foi-rag \
            --timeout=120s
```

The container name `foi-rag-api` in `kubectl set image` must match the `name:` field under `containers:` in `k8s/api-deployment.yml` exactly.

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: add GitHub Actions deploy workflow"
```

---

### Task 10: Create deployment runbook

**Files:**
- Create: `docs/deployment-runbook.md`

- [ ] **Step 1: Create `docs/deployment-runbook.md`**

```markdown
# foi-rag Deployment Runbook

Complete checklist for deploying foi-rag to the Hetzner CX33 server.

**Server IP:** 135.181.255.239
**Domain:** foi-rag.sgroi.dev
**Docker Hub:** sgroil

---

## One-time server setup

- [ ] SSH in as root: `ssh root@135.181.255.239`
- [ ] Create deploy user:
  ```bash
  adduser --disabled-password deploy
  usermod -aG sudo deploy
  echo "deploy ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/deploy
  mkdir -p /home/deploy/.ssh
  cp /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
  chown -R deploy:deploy /home/deploy/.ssh
  chmod 700 /home/deploy/.ssh
  chmod 600 /home/deploy/.ssh/authorized_keys
  ```
- [ ] Test in a new terminal: `ssh deploy@135.181.255.239 && sudo whoami` (should print `root`)
- [ ] Harden SSH (`sudo nano /etc/ssh/sshd_config`):
  ```
  PermitRootLogin no
  PasswordAuthentication no
  PubkeyAuthentication yes
  ```
  Then: `sudo sshd -t && sudo systemctl restart ssh`
- [ ] Open firewall:
  ```bash
  sudo ufw allow 22/tcp
  sudo ufw allow 80/tcp
  sudo ufw allow 443/tcp
  sudo ufw allow 6443/tcp
  sudo ufw enable
  ```
- [ ] Install Docker:
  ```bash
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker deploy
  ```
- [ ] Log out and back in as deploy, then verify: `docker run hello-world`
- [ ] Install k3s:
  ```bash
  curl -sfL https://get.k3s.io | sh -
  ```
- [ ] Configure kubectl:
  ```bash
  mkdir -p ~/.kube
  sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
  sudo chown deploy:deploy ~/.kube/config
  echo 'export KUBECONFIG=~/.kube/config' >> ~/.bashrc
  export KUBECONFIG=~/.kube/config
  ```
- [ ] Verify: `kubectl get nodes` — node should show as Ready
- [ ] Install cert-manager:
  ```bash
  kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.14.4/cert-manager.yaml
  ```
- [ ] Wait for cert-manager pods: `kubectl get pods -n cert-manager --watch` (all three Running, Ctrl+C when done)
- [ ] Clone the repo on the server:
  ```bash
  git clone https://github.com/<your-org>/foi-rag.git
  cd foi-rag
  ```
- [ ] Apply ClusterIssuer: `kubectl apply -f k8s/cluster-issuer.yml`

---

## First deploy

- [ ] Add DNS A record in Cloudflare: `foi-rag.sgroi.dev` → `135.181.255.239`, TTL 300
- [ ] Add GitHub repo secrets (Settings → Secrets and variables → Actions):
  | Secret | Value |
  |---|---|
  | `DOCKERHUB_USERNAME` | `sgroil` |
  | `DOCKERHUB_TOKEN` | Docker Hub access token |
  | `KUBECONFIG_DATA` | base64-encoded kubeconfig (see below) |

  Get KUBECONFIG_DATA on the server:
  ```bash
  sudo cat /etc/rancher/k3s/k3s.yaml | sed "s/127.0.0.1/135.181.255.239/" | base64 -w 0
  ```
- [ ] Create namespace: `kubectl create namespace foi-rag`
- [ ] Create secrets on the server:
  ```bash
  kubectl create secret generic db-secrets \
    --namespace foi-rag \
    --from-literal=POSTGRES_USER=foi \
    --from-literal=POSTGRES_PASSWORD=<choose-a-secure-password> \
    --from-literal=POSTGRES_DB=foi

  kubectl create secret generic app-secrets \
    --namespace foi-rag \
    --from-literal=DATABASE_URL=postgresql://foi:<same-password>@foi-rag-db:5432/foi \
    --from-literal=OPENAI_API_KEY=<your-key> \
    --from-literal=ANTHROPIC_API_KEY=<your-key>
  ```
- [ ] Apply DB manifests first (so DB is ready before API starts):
  ```bash
  kubectl apply -f k8s/db-pvc.yml
  kubectl apply -f k8s/db-deployment.yml
  kubectl apply -f k8s/db-service.yml
  ```
- [ ] Wait for DB to be ready: `kubectl get pods -n foi-rag --watch` (foi-rag-db pod Running)
- [ ] Push to `main` — this triggers CI/CD, which builds the image, applies all `k8s/` manifests, and rolls out the API
- [ ] Wait for certificate: `kubectl get certificate -n foi-rag --watch` (READY = True, Ctrl+C when done)
- [ ] Verify API is live:
  ```bash
  curl https://foi-rag.sgroi.dev/health
  ```
  Expected: `{"status":"ok"}`

---

## Initial data load

- [ ] Apply ingestion job:
  ```bash
  kubectl apply -f k8s/jobs/ingestion-job.yml
  ```
- [ ] Monitor logs:
  ```bash
  kubectl logs -f job/foi-rag-ingest -n foi-rag
  ```
- [ ] Check job completed successfully:
  ```bash
  kubectl get job foi-rag-ingest -n foi-rag
  ```
  Expected: `COMPLETIONS 1/1`
- [ ] Verify data is queryable:
  ```bash
  curl -X POST https://foi-rag.sgroi.dev/query \
    -H "Content-Type: application/json" \
    -d '{"query": "housing policy"}'
  ```
  Expected: JSON response with `answer` and `citations` fields.

---

## Re-ingestion (when Camden publishes new FOI docs)

- [ ] Delete old job: `kubectl delete job foi-rag-ingest -n foi-rag`
- [ ] Re-apply: `kubectl apply -f k8s/jobs/ingestion-job.yml`
- [ ] Monitor: `kubectl logs -f job/foi-rag-ingest -n foi-rag`

---

## Updating secrets

Kubernetes secrets cannot be edited in place. Delete and recreate:

```bash
kubectl delete secret app-secrets --namespace foi-rag
kubectl create secret generic app-secrets \
  --namespace foi-rag \
  --from-literal=DATABASE_URL=... \
  --from-literal=OPENAI_API_KEY=... \
  --from-literal=ANTHROPIC_API_KEY=...
kubectl rollout restart deployment/foi-rag-api --namespace foi-rag
```

---

## Useful kubectl commands

```bash
kubectl get pods -n foi-rag                                          # list pods
kubectl logs deployment/foi-rag-api -n foi-rag                      # API logs
kubectl logs deployment/foi-rag-api -n foi-rag --previous           # last crash logs
kubectl logs -f job/foi-rag-ingest -n foi-rag                       # follow job logs
kubectl describe pod -l app=foi-rag-api -n foi-rag                  # pod detail / events
kubectl get events -n foi-rag --sort-by='.lastTimestamp'            # recent events
kubectl rollout restart deployment/foi-rag-api -n foi-rag           # restart API pods
kubectl rollout undo deployment/foi-rag-api -n foi-rag              # rollback
kubectl get certificate -n foi-rag                                   # TLS cert status
kubectl get secrets -n foi-rag                                       # list secrets
```
```

- [ ] **Step 2: Commit**

```bash
git add docs/deployment-runbook.md
git commit -m "docs: add deployment runbook"
```

---

## Final verification checklist

Before calling this done, verify the following locally:

- [ ] `docker build -t foi-rag-api:local .` succeeds
- [ ] `uv run pytest tests/ -v` — all tests pass
- [ ] All `k8s/*.yml` files present: `db-pvc.yml`, `db-deployment.yml`, `db-service.yml`, `api-deployment.yml`, `api-service.yml`, `ingress.yml`, `cluster-issuer.yml`
- [ ] `k8s/jobs/ingestion-job.yml` present
- [ ] `.github/workflows/deploy.yml` present
- [ ] `docs/deployment-runbook.md` present
