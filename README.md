# MLOps Local Simulator — CTR Pipeline on kind + Argo CD

Simulates the full lifecycle: **feature engineering → training → evaluation →
serving → monitoring → drift-triggered retraining**, GitOps-managed by Argo
CD, fronted by a GitHub Actions CI pipeline.

```
GitHub repo --push--> GitHub Actions (build/test/push image)
                              |
                    Argo CD watches repo manifests
                              |
                    kind Kubernetes cluster
   ┌─────────────┬─────────────┬─────────────┬──────────────┬───────────────┐
   mlops-data    mlops-training mlops-training mlops-serving  mlops-monitoring
   feature-Job    training-Job   eval-Job       serving-Deploy  drift-Deploy
                  retrain-CronJob                              Prometheus
```

All stages share one **artifact store**: a hostPath directory on the kind
worker node (`/mnt/artifacts`, backed by `/tmp/mlops-artifacts` on your
laptop) mounted into every namespace via per-namespace PV/PVC pairs. This
stands in for a real model/feature registry (S3, MLflow) — same idea, just
local disk instead of cloud storage.

---
## 0. Prerequisites
- Docker Desktop (or Docker Engine) running
- `kubectl`
- `kind`
- (optional) `argocd` CLI, `git`, a GitHub account for the CI/CD part

### Install kind (macOS / Linux)
```bash
# macOS
brew install kind kubectl

# Linux (binary)
curl -Lo ./kind https://kind.sigs.k8s.io/dl/latest/kind-linux-amd64
chmod +x ./kind && sudo mv ./kind /usr/local/bin/kind
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl && sudo mv kubectl /usr/local/bin/
```

### Verify install
```bash
kind version
kubectl version --client
docker ps      # confirms docker daemon is reachable
```

---
## 1. Create the kind cluster
```bash
cd mlops-sim
kind create cluster --name mlops-sim --config kind/kind-config.yaml
kubectl cluster-info --context kind-mlops-sim
kubectl get nodes -o wide        # should show 1 control-plane + 1 worker, Ready
```
`kind/kind-config.yaml` also maps host ports 30080 (model API) and 30090
(Prometheus) straight into the cluster, and mounts `/tmp/mlops-artifacts`
from your laptop into the worker node at `/mnt/artifacts` — this is the
"shared artifact store" every namespace's PVC points at.

---
## 2. Run the whole pipeline end-to-end (one command)
```bash
./run_pipeline.sh
```
This script, in order:
1. `docker build` the single shared pipeline image (`mlops-sim:local`)
2. `kind load docker-image` — pushes it straight into the kind node's
   containerd (no registry needed for local dev)
3. Applies namespaces → shared storage → feature-engineering Job → training
   Job → evaluation Job (gate) → serving Deployment/Service → monitoring
   Deployment + Prometheus → retraining CronJob, **waiting for each stage to
   finish before starting the next** — exactly like a real pipeline DAG.

### Watch it happen, in another terminal
```bash
kubectl get all -A                                   # everything, every namespace
kubectl get jobs -n mlops-data
kubectl get jobs -n mlops-training
kubectl logs -n mlops-data job/feature-engineering
kubectl logs -n mlops-training job/model-training
kubectl logs -n mlops-training job/model-evaluation
kubectl get pods -n mlops-serving -w
kubectl logs -n mlops-monitoring deploy/drift-monitor -f
```

### Hit the deployed model
```bash
curl -X POST http://localhost:30080/predict \
  -H 'Content-Type: application/json' \
  -d '{"num_1":55,"num_2":1.2,"num_3":40,"cat_1":"device_1","cat_2":"site_3","cat_3":"campaign_2","cat_4":"geo_1"}'

curl http://localhost:30080/metrics | head -20   # Prometheus-format metrics
```

### Prometheus UI
Open `http://localhost:30090` → Status → Targets, confirm `model-serving`
target is UP. Try a query: `predictions_total`.

### Watch drift force a retrain
The monitor pod simulates increasing drift every 30s. Once PSI crosses 0.2 it
writes `/mnt/artifacts/retrain_trigger.flag`. The CronJob fires every 2 min,
sees the flag, reruns feature-engineering → training → evaluation, and
clears the flag if the new model passes the AUC gate.
```bash
cat /tmp/mlops-artifacts/drift_log.json
kubectl get cronjob -n mlops-training
kubectl get jobs -n mlops-training        # new retraining-cronjob-xxxxx Jobs appear
```

---
## 3. GitOps with Argo CD (manual manifest sync, no CI yet)
### Install Argo CD into the cluster
```bash
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl rollout status deployment/argocd-server -n argocd --timeout=180s
```
### Access the UI
```bash
kubectl port-forward svc/argocd-server -n argocd 8080:443
# in another terminal, get the auto-generated admin password:
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d; echo
```
Open `https://localhost:8080`, login as `admin` / (password above).

### Push this repo to your own GitHub repo, then register it
```bash
git init
git add .
git commit -m "initial MLOps pipeline simulation"
git branch -M main
git remote add origin https://github.com/<YOU>/mlops-sim.git
git push -u origin main
```
Edit `argocd/application.yaml` → set `repoURL` to your repo, then:
```bash
kubectl apply -f argocd/application.yaml
```
Argo CD now continuously reconciles the cluster to match
`kustomization.yaml` in your repo. Any `git push` that changes a manifest
gets auto-applied (`selfHeal: true` also reverts any manual `kubectl edit`
you make directly against the cluster — try it, and watch Argo CD undo it).

---
## 4. CI with GitHub Actions
`.github/workflows/ci.yaml` triggers on every push to `main`:
1. checks out code
2. smoke-tests the pipeline scripts directly (no Kubernetes — fast feedback)
3. builds the Docker image
4. pushes it to `ghcr.io/<you>/mlops-sim:<sha>` and `:latest`

This is the realistic CI half of CI/CD: it doesn't touch your local kind
cluster (GitHub's runners can't reach your laptop). In real production, a
component like **Argo CD Image Updater** or a separate "bump the tag in
git" CI step would close that loop automatically. For this local
simulation, the deliberate manual step is:
```bash
docker build -t mlops-sim:local .
kind load docker-image mlops-sim:local --name mlops-sim
kubectl rollout restart deployment/model-serving -n mlops-serving
```
That hand-off (CI publishes an artifact → something promotes it into the
cluster) is exactly the boundary interviewers like to probe — now you've
built both sides of it and can point to precisely where the seam is.

---
## 5. The full stage-by-stage map (what runs where)

| Stage | Namespace | K8s kind | File | Python entrypoint |
|---|---|---|---|---|
| Feature engineering | `mlops-data` | Job (+ initContainer seeds raw data) | `feature-engineering/job.yaml` | `feature_engineering.py` |
| Training | `mlops-training` | Job | `training/job.yaml` | `train.py` |
| Evaluation (gate) | `mlops-training` | Job | `evaluation/job.yaml` | `evaluate.py` |
| Serving | `mlops-serving` | Deployment + Service (NodePort) | `serving/deployment.yaml` | `app.py` (FastAPI/uvicorn) |
| Monitoring | `mlops-monitoring` | Deployment + Prometheus | `monitoring/deployment.yaml`, `monitoring/prometheus.yaml` | `monitor.py` |
| Retraining | `mlops-training` | CronJob | `retraining/cronjob.yaml` | `retrain.py` |

Every Python file talks to the **same artifact directory**
(`$ARTIFACT_DIR`, mounted at `/mnt/artifacts`) instead of to each other
directly — that decoupling (write-to-store / read-from-store) is exactly
how real pipeline stages on Kubernetes hand off state across Jobs/Pods that
don't share memory or a filesystem by default.

---
## 6. Tear down
```bash
kind delete cluster --name mlops-sim
rm -rf /tmp/mlops-artifacts
```

## 7. Talking points for interviews
- **Why Jobs vs Deployments vs CronJobs**: Jobs = run-to-completion batch
  work (feature eng, training, eval); Deployments = long-running services
  that need replicas/self-healing (serving, monitoring); CronJobs =
  scheduled recurring batch work (retraining).
- **Why a gate (evaluation Job can fail on purpose)**: mirrors real
  promotion gates — a model that doesn't beat a metric threshold should
  never reach serving. Here it's enforced by the Job exiting non-zero,
  which is what a real Argo Workflows/Tekton/Airflow DAG would also key off.
- **Why namespaces**: isolation + RBAC boundary + clean mental model of
  pipeline stage ownership, same as separate teams/environments would own
  in prod (data eng owns `mlops-data`, ML eng owns `mlops-training`, SRE/MLOps
  owns `mlops-serving`/`mlops-monitoring`).
- **Why a shared volume here but registries/object stores in real prod**:
  same contract (write artifact, read artifact by path), just swap hostPath
  for S3/GCS + MLflow model registry — the YAML structure barely changes.
- **Where GitOps fits**: Argo CD is the only thing with write access to the
  cluster's desired state; CI never runs `kubectl apply` directly — it only
  publishes images/manifests. That separation is the entire point of GitOps.
