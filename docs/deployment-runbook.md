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
