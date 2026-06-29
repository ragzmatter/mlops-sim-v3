# MLOps Sim — Full Pipeline Steps (All Stages, All Tools)

## Architecture Recap
```
Git Push → GitHub Actions → Docker Build → Local Registry
→ Kubeflow Pipeline DAG:
   Feature Engineering → Feast Materialize → Training → MLflow Log
   → Evaluation → MLflow Registry → Approval Gate
→ Argo CD Sync → Serving Deployment (Feast Online) → Prometheus → Grafana
→ Drift Detection → Retraining CronJob
```

## Port Map
| Service        | Port  |
|----------------|-------|
| Model API      | 30080 |
| MLflow UI      | 30500 |
| Prometheus     | 30090 |
| Grafana        | 30030 |
| Local Registry | 30050 |
| KFP UI         | 8888  |
| Argo CD UI     | 8080  |

---

## PHASE 0 — Prerequisites

```bash
# Install Docker Desktop (must be running before anything else)
docker ps   # confirm daemon responds

# Install kind
curl -Lo ./kind https://kind.sigs.k8s.io/dl/latest/kind-linux-amd64
chmod +x ./kind && sudo mv ./kind /usr/local/bin/kind
kind version   # expect: kind v0.x.x

# Install kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl && sudo mv kubectl /usr/local/bin/
kubectl version --client

# Install Python deps (for local testing outside cluster)
pip install pandas numpy scikit-learn joblib pyarrow \
            mlflow "feast[redis]" kfp fastapi uvicorn \
            prometheus_client pydantic

# Confirm all installed
python3 -c "import feast, mlflow, kfp; print('all ok')"
```

---

## PHASE 1 — Kind Cluster

```bash
cd mlops-sim

# 1. Create shared artifact dir on your laptop (backs all hostPath PVs)
mkdir -p /tmp/mlops-artifacts

# 2. Create cluster (1 control-plane + 1 worker, ports mapped)
kind create cluster --name mlops-sim --config kind/kind-config.yaml

# 3. Verify cluster
kubectl cluster-info --context kind-mlops-sim
kubectl get nodes -o wide
# Expected: 2 nodes, STATUS=Ready

# 4. Check node has the hostPath mount
docker exec mlops-sim-worker ls /mnt/artifacts
# Expected: empty dir (will fill as pipeline runs)

# 5. Set context
kubectl config use-context kind-mlops-sim
kubectl config current-context   # confirm: kind-mlops-sim
```

---

## PHASE 2 — Namespaces and Shared Storage

```bash
# 1. Apply all namespaces
kubectl apply -f namespaces/namespaces.yaml
kubectl get namespaces
# Expected: mlops-data, mlops-training, mlops-serving, mlops-monitoring, argocd

# 2. Apply PV/PVC pairs (one per namespace, all point at /mnt/artifacts)
kubectl apply -f namespaces/shared-storage.yaml
kubectl get pv
# Expected: 4 PVs, STATUS=Available or Bound
kubectl get pvc -A
# Expected: artifacts-pvc in each namespace, STATUS=Bound

# 3. Verify PVC binding
kubectl describe pvc artifacts-pvc -n mlops-data
# Look for: Status: Bound, Volume: artifacts-pv-data
```

---

## PHASE 3 — Local Docker Registry

```bash
# 1. Deploy in-cluster registry
kubectl apply -f registry/registry-grafana.yaml
kubectl rollout status deployment/local-registry -n kube-system --timeout=60s

# 2. Build the pipeline image
docker build -t mlops-sim:local .
# Watch each layer build — feast[redis] layer takes ~2 min first time

# 3. Tag for local registry
docker tag mlops-sim:local localhost:30050/mlops-sim:latest

# 4. Push to in-cluster registry
docker push localhost:30050/mlops-sim:latest
# Expected: pushed sha256:xxx

# 5. Verify image is in registry
curl http://localhost:30050/v2/mlops-sim/tags/list
# Expected: {"name":"mlops-sim","tags":["latest"]}

# 6. Also load directly into kind nodes (avoids pull latency in Jobs)
kind load docker-image mlops-sim:local --name mlops-sim
# Expected: Image: "mlops-sim:local" with ID "sha256:xxx" not yet present on node...
#           Loading image: mlops-sim:local ... done
```

---

## PHASE 4 — GitHub Repo + GitHub Actions (CI)

```bash
# 1. Create empty repo on github.com named "mlops-sim" (no README)

# 2. Init and push
git init
git add .
git commit -m "initial MLOps pipeline simulation"
git branch -M main
git remote add origin https://github.com/<YOUR_USERNAME>/mlops-sim.git
git push -u origin main

# 3. Watch Actions tab on GitHub — ci.yaml triggers automatically
#    Steps running in GitHub's cloud runner:
#    a. Checkout code
#    b. pip install deps
#    c. python data/generate_dataset.py
#    d. ARTIFACT_DIR=data python feature-engineering/feature_engineering.py
#    e. ARTIFACT_DIR=data python training/train_mlflow.py
#    f. ARTIFACT_DIR=data python evaluation/evaluate_mlflow.py
#    g. docker login ghcr.io
#    h. docker build + push to ghcr.io/<YOU>/mlops-sim:latest + :<sha>

# 4. Confirm image published
# Go to: github.com/<YOU> -> Packages -> mlops-sim

# 5. For every subsequent code change:
git add . && git commit -m "your message" && git push
# CI reruns all steps above automatically
```

---

## PHASE 5 — MLflow Tracking Server

```bash
# 1. Deploy MLflow into mlops-training namespace
kubectl apply -f mlflow/mlflow-deployment.yaml
kubectl rollout status deployment/mlflow -n mlops-training --timeout=120s

# 2. Verify pod is running
kubectl get pods -n mlops-training
# Expected: mlflow-xxxxxxxxx-xxxxx   1/1   Running

# 3. Check logs — should show MLflow server started
kubectl logs -n mlops-training deploy/mlflow
# Look for: [INFO] Listening at: http://0.0.0.0:5000

# 4. Access MLflow UI
# NodePort 30500 already mapped via kind-config.yaml
open http://localhost:30500
# Or: curl http://localhost:30500/health  -> {"status": "OK"}

# 5. Verify MLflow can write to artifact store
kubectl exec -n mlops-training deploy/mlflow -- \
  ls /mnt/artifacts/
# After first training run: mlflow/ and mlflow-artifacts/ dirs appear
```

---

## PHASE 6 — Redis (Online Feature Store Backend)

```bash
# 1. Deploy Redis
kubectl apply -f feast/redis-and-materialize-job.yaml
kubectl rollout status deployment/redis -n mlops-data --timeout=60s

# 2. Verify Redis is up
kubectl get pods -n mlops-data
# Expected: redis-xxxxxxxxx   1/1   Running

# 3. Ping Redis from inside cluster
kubectl exec -n mlops-data deploy/redis -- redis-cli ping
# Expected: PONG

# 4. Check Redis is empty before materialization
kubectl exec -n mlops-data deploy/redis -- redis-cli DBSIZE
# Expected: (integer) 0

# 5. Verify service DNS (other pods will use this hostname)
kubectl get svc -n mlops-data
# Expected: redis-svc   ClusterIP   ...   6379/TCP
# Full DNS: redis-svc.mlops-data.svc.cluster.local:6379
```

---

## PHASE 7 — Feature Engineering Stage

```bash
# 1. Apply feature engineering Job
kubectl apply -f feature-engineering/job.yaml

# 2. Watch it run
kubectl get pods -n mlops-data -w
# Pod transitions: Pending -> ContainerCreating -> Running -> Completed

# 3. Follow logs in real time
kubectl logs -n mlops-data job/feature-engineering -f
# Expected output:
# [feature-engineering] reading /mnt/artifacts/raw_ad_data.csv
# [feature-engineering] wrote /mnt/artifacts/features.parquet shape=(50000, 8)
# [feature-engineering] wrote /mnt/artifacts/feature_pipeline.joblib

# 4. Wait for completion
kubectl wait --for=condition=complete job/feature-engineering \
  -n mlops-data --timeout=120s

# 5. Verify artifacts written to shared store
docker exec mlops-sim-worker ls /mnt/artifacts/
# Expected: raw_ad_data.csv  features.parquet  feature_pipeline.joblib

# 6. Spot-check feature values
docker exec mlops-sim-worker python3 -c "
import pandas as pd
df = pd.read_parquet('/mnt/artifacts/features.parquet')
print(df.head(3))
print('shape:', df.shape)
"
```

---

## PHASE 8 — Feast Materialization (Offline -> Online)

```bash
# 1. Feast-materialize Job runs after feature-engineering (applied in Phase 6)
#    Check if it's already pending/running:
kubectl get jobs -n mlops-data
# If not running yet, it was already applied in Phase 6 YAML

# 2. Watch the Job pod
kubectl logs -n mlops-data job/feast-materialize -f
# Expected output:
# [feast] wrote /mnt/artifacts/features_with_ts.parquet shape=(50000, 9)
# [feast] apply done
# [feast] materialize done — features live in Redis

# 3. Wait for completion
kubectl wait --for=condition=complete job/feast-materialize \
  -n mlops-data --timeout=180s

# 4. Verify Feast registry was written
docker exec mlops-sim-worker ls /mnt/artifacts/feast/
# Expected: registry.db

# 5. Verify Redis now has feature data
kubectl exec -n mlops-data deploy/redis -- redis-cli DBSIZE
# Expected: (integer) 50000  (one key per ad_id)

# 6. Spot-check one key in Redis
kubectl exec -n mlops-data deploy/redis -- redis-cli KEYS "*" | head -5

# 7. Fetch one entity's features via Feast SDK (local, not in cluster)
# Port-forward Redis first:
kubectl port-forward svc/redis-svc -n mlops-data 6379:6379 &
python3 << 'EOF'
from feast import FeatureStore
store = FeatureStore(repo_path="feast/feature_repo")
result = store.get_online_features(
    features=["ad_features:num_1","ad_features:num_2","ad_features:num_3",
              "ad_features:cat_1","ad_features:cat_2","ad_features:cat_3",
              "ad_features:cat_4"],
    entity_rows=[{"ad_id": 42}]
).to_dict()
print(result)
EOF
# Expected: {"ad_id":[42], "num_1":[-0.3], "num_2":[0.7], ...}
```

---

## PHASE 9 — Model Training Stage + MLflow Logging

```bash
# 1. Apply training Job
kubectl apply -f training/job.yaml

# 2. Watch logs
kubectl logs -n mlops-training job/model-training -f
# Expected:
# [training] train_auc=0.7XXX
# [training] run_id=<uuid>

# 3. Wait for completion
kubectl wait --for=condition=complete job/model-training \
  -n mlops-training --timeout=120s

# 4. Verify artifacts
docker exec mlops-sim-worker ls /mnt/artifacts/
# Expected: + model.joblib  test_split.parquet  train_metrics.json  run_id.txt

# 5. Check MLflow UI — experiment logged
open http://localhost:30500
# Click: Experiments -> ctr-pipeline -> latest run
# Verify: params (C, max_iter, solver), metrics (train_auc), artifact (model/)

# 6. Read run_id from shared store
docker exec mlops-sim-worker cat /mnt/artifacts/run_id.txt

# 7. Fetch run details via MLflow API
curl http://localhost:30500/api/2.0/mlflow/runs/search \
  -d '{"experiment_ids":["1"]}' | python3 -m json.tool | head -40
```

---

## PHASE 10 — Model Evaluation + MLflow Registry Promotion

```bash
# 1. Apply evaluation Job
kubectl apply -f evaluation/job.yaml

# 2. Watch logs
kubectl logs -n mlops-training job/model-evaluation -f
# Expected:
# [evaluation] {'test_auc': 0.7X, 'accuracy': 0.7X, 'precision': 0.XX, 'recall': 0.XX}
# [evaluation] APPROVED — promoted ctr-model v1 to Production

# 3. Wait — exit 0 = approved, exit 1 = rejected (blocks deployment)
kubectl wait --for=condition=complete job/model-evaluation \
  -n mlops-training --timeout=120s

# 4. Confirm approval flag
docker exec mlops-sim-worker cat /mnt/artifacts/model_approved.flag
# Expected: approved

# 5. Check model promoted in MLflow registry
open http://localhost:30500
# Click: Models -> ctr-model -> Version 1 -> Stage: Production

# 6. Fetch via MLflow API
curl "http://localhost:30500/api/2.0/mlflow/registered-models/get?name=ctr-model" \
  | python3 -m json.tool
# Look for: "current_stage": "Production"

# 7. What happens if model is rejected:
# - evaluate.py exits with code 1
# - K8s Job status = Failed
# - model_approved.flag NOT written
# - serving deployment in next phase will not roll out new model
# - check: kubectl describe job/model-evaluation -n mlops-training
```

---

## PHASE 11 — Kubeflow Pipelines (Orchestration)

```bash
# 1. Install KFP standalone into cluster
kubectl apply -k \
  "github.com/kubeflow/pipelines/manifests/kustomize/cluster-scoped-resources?ref=2.0.0"
kubectl apply -k \
  "github.com/kubeflow/pipelines/manifests/kustomize/env/platform-agnostic-pns?ref=2.0.0"

# 2. Wait for all KFP pods
kubectl rollout status deployment/ml-pipeline -n kubeflow --timeout=300s
kubectl get pods -n kubeflow
# All should be Running

# 3. Access KFP UI
kubectl port-forward svc/ml-pipeline-ui -n kubeflow 8888:80 &
open http://localhost:8888

# 4. Compile the pipeline
python3 kubeflow/pipeline.py
# Produces: pipeline.yaml

# 5. Upload via UI
# http://localhost:8888 -> Pipelines -> Upload Pipeline -> select pipeline.yaml

# 6. Or submit via Python SDK
python3 << 'EOF'
import kfp
client = kfp.Client(host="http://localhost:8888")
run = client.create_run_from_pipeline_package(
    "pipeline.yaml",
    arguments={"mlflow_uri": "http://mlflow-svc.mlops-training.svc.cluster.local:5000"}
)
print("Run ID:", run.run_id)
EOF

# 7. Watch DAG in KFP UI
# http://localhost:8888 -> Runs -> select run -> see live DAG
# Each node = one K8s pod in mlops-training namespace
# Green = complete, Blue = running, Red = failed

# 8. Check pods created by KFP
kubectl get pods -n kubeflow
# Each pipeline step creates a pod named: <pipeline-run-id>-<step-name>

# 9. View logs per step from KFP UI
# Click node in DAG -> Logs tab -> real pod logs streamed

# 10. After run completes: all artifacts in /mnt/artifacts, model in MLflow
```

---

## PHASE 12 — Argo CD (GitOps)

```bash
# 1. Install Argo CD
kubectl apply -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl rollout status deployment/argocd-server -n argocd --timeout=180s

# 2. Get admin password
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d; echo

# 3. Access UI
kubectl port-forward svc/argocd-server -n argocd 8080:443 &
open https://localhost:8080
# Login: admin / <password from step 2>

# 4. Edit application.yaml — set your repo URL
sed -i 's|<YOUR_GH_USERNAME>|<YOUR_ACTUAL_USERNAME>|g' argocd/application.yaml

# 5. Register app with Argo CD
kubectl apply -f argocd/application.yaml

# 6. Watch sync in UI
# https://localhost:8080 -> Applications -> mlops-sim
# Status should move: OutOfSync -> Syncing -> Synced + Healthy

# 7. Verify Argo CD deployed manifests
kubectl get all -n mlops-serving
kubectl get all -n mlops-monitoring
# All resources should match what's in your git repo

# 8. Test selfHeal (Argo CD reverts manual changes)
kubectl scale deployment/model-serving -n mlops-serving --replicas=5
# Wait 30 seconds
kubectl get deployment/model-serving -n mlops-serving
# replicas should be back to 2 (reverted by Argo CD)

# 9. Test GitOps update flow
# Edit retraining/cronjob.yaml — change schedule from "*/2 * * * *" to "*/5 * * * *"
git add retraining/cronjob.yaml
git commit -m "change retrain schedule to every 5 min"
git push
# Watch Argo CD UI — detects change, syncs automatically within ~3 min
kubectl get cronjob -n mlops-training
# schedule should now show: */5 * * * *
```

---

## PHASE 13 — Model Serving (FastAPI + Feast Online)

```bash
# 1. Apply serving deployment (feast-enabled version)
kubectl apply -f serving/deployment_feast.yaml
kubectl rollout status deployment/model-serving -n mlops-serving --timeout=120s

# 2. Check pods
kubectl get pods -n mlops-serving
# Expected: 2 pods, STATUS=Running

# 3. Check readiness probe passed
kubectl describe pod -n mlops-serving -l app=model-serving | grep -A5 Conditions
# Ready: True

# 4. Check serving logs — model and Feast store loading
kubectl logs -n mlops-serving deploy/model-serving
# Expected: Loaded model.joblib, FeatureStore initialized, Uvicorn running on port 8000

# 5. Health check
curl http://localhost:30080/health
# {"status": "ok"}

# 6. Predict using Feast online store (production path)
curl -X POST http://localhost:30080/predict \
  -H 'Content-Type: application/json' \
  -d '{"ad_id": 42}'
# {"ad_id": 42, "click_probability": 0.32}

# 7. Predict using raw features (test/fallback path)
curl -X POST http://localhost:30080/predict_raw \
  -H 'Content-Type: application/json' \
  -d '{"num_1":0.5,"num_2":1.2,"num_3":0.8,"cat_1":1,"cat_2":3,"cat_3":2,"cat_4":1}'
# {"click_probability": 0.29}

# 8. Load test (generate traffic for Prometheus to scrape)
for i in $(seq 1 200); do
  curl -s -X POST http://localhost:30080/predict \
    -H 'Content-Type: application/json' \
    -d "{\"ad_id\": $((RANDOM % 1000))}" > /dev/null
done
echo "200 predictions sent"

# 9. Check raw Prometheus metrics from serving
curl -s http://localhost:30080/metrics | grep -E "predictions_total|latency|feast"
# predictions_total 200
# feast_online_hits_total 200
# prediction_latency_seconds_bucket{...}

# 10. Verify Feast lookup actually hit Redis
kubectl exec -n mlops-data deploy/redis -- redis-cli INFO stats | grep keyspace_hits
# keyspace_hits: should be > 0 and growing
```

---

## PHASE 14 — Prometheus

```bash
# 1. Apply Prometheus (if not already)
kubectl apply -f monitoring/prometheus.yaml
kubectl rollout status deployment/prometheus -n mlops-monitoring --timeout=60s

# 2. Verify Prometheus config was picked up
kubectl logs -n mlops-monitoring deploy/prometheus | head -20
# Look for: Server is ready to receive web requests

# 3. Open Prometheus UI
open http://localhost:30090

# 4. Check targets are UP
# http://localhost:30090/targets
# model-serving endpoint must show State=UP
# If DOWN: check service DNS resolves inside cluster:
kubectl exec -n mlops-monitoring deploy/prometheus -- \
  wget -qO- http://model-serving-svc.mlops-serving.svc.cluster.local:80/metrics | head -5

# 5. Run queries in Prometheus UI (http://localhost:30090/graph)

# Total predictions served:
predictions_total

# Request rate per second (over last 5 min):
rate(predictions_total[5m])

# Prediction latency 99th percentile:
histogram_quantile(0.99, rate(prediction_latency_seconds_bucket[5m]))

# Feast online store hit rate:
rate(feast_online_hits_total[5m])

# Distribution of predicted scores (how many high-confidence predictions):
prediction_score_bucket

# 6. Verify metrics persist across pod restarts
kubectl rollout restart deployment/model-serving -n mlops-serving
# Send a few more predictions, metrics should continue accumulating
```

---

## PHASE 15 — Grafana Dashboard

```bash
# 1. Grafana already deployed via registry/registry-grafana.yaml (Phase 3)
kubectl rollout status deployment/grafana -n mlops-monitoring --timeout=60s
kubectl get pods -n mlops-monitoring

# 2. Open Grafana
open http://localhost:30030
# Login: admin / admin (set GF_SECURITY_ADMIN_PASSWORD=admin in manifest)

# 3. Add Prometheus data source
# Left sidebar -> Connections -> Data Sources -> Add new -> Prometheus
# URL: http://prometheus-svc.mlops-monitoring.svc.cluster.local:9090
# Click: Save & Test -> "Successfully queried the Prometheus API"

# 4. Create dashboard — New -> Add visualization
# Panel 1: Total Predictions
#   Query: predictions_total
#   Visualization: Stat

# Panel 2: Request Rate
#   Query: rate(predictions_total[5m])
#   Visualization: Time series

# Panel 3: p99 Latency
#   Query: histogram_quantile(0.99, rate(prediction_latency_seconds_bucket[5m]))
#   Visualization: Time series
#   Unit: seconds

# Panel 4: Prediction Score Distribution
#   Query: prediction_score_bucket
#   Visualization: Heatmap

# Panel 5: Feast Cache Hit Rate
#   Query: rate(feast_online_hits_total[5m])
#   Visualization: Time series

# 5. Save dashboard as "CTR Model Monitoring"

# 6. Set auto-refresh
# Top right -> refresh dropdown -> select 10s

# 7. Import a pre-built dashboard (optional shortcut)
# Grafana.com dashboard ID 1860 (Node Exporter Full) works for infra metrics
# Dashboards -> Import -> Enter ID 1860 -> Load -> Select Prometheus -> Import
```

---

## PHASE 16 — Drift Detection (Monitoring Pod)

```bash
# 1. Apply monitoring deployment
kubectl apply -f monitoring/deployment.yaml
kubectl rollout status deployment/drift-monitor -n mlops-monitoring --timeout=60s

# 2. Watch drift build up in real time
kubectl logs -n mlops-monitoring deploy/drift-monitor -f
# Every 30s:
# [monitoring] PSI=0.0412 drifted=False
# [monitoring] PSI=0.1023 drifted=False
# [monitoring] PSI=0.1876 drifted=False
# [monitoring] PSI=0.2341 drifted=True   <- threshold crossed
# [monitoring] drift threshold exceeded -> retrain_trigger.flag written

# 3. Check drift log file
docker exec mlops-sim-worker cat /mnt/artifacts/drift_log.json
# {"timestamp": 1234567890.0, "psi": 0.2341, "drifted": true}

# 4. Confirm flag was written
docker exec mlops-sim-worker cat /mnt/artifacts/retrain_trigger.flag
# retrain

# 5. Understanding PSI values
# PSI < 0.1  = no drift, distribution stable
# PSI 0.1-0.2 = minor drift, worth monitoring
# PSI > 0.2  = significant drift -> retrain

# 6. To reset drift and test from scratch (simulate stable period)
kubectl exec -n mlops-monitoring deploy/drift-monitor -- \
  rm -f /mnt/artifacts/retrain_trigger.flag
kubectl rollout restart deployment/drift-monitor -n mlops-monitoring
```

---

## PHASE 17 — Retraining CronJob

```bash
# 1. Apply retraining CronJob
kubectl apply -f retraining/cronjob.yaml

# 2. Verify CronJob registered
kubectl get cronjob -n mlops-training
# NAME                  SCHEDULE      SUSPEND   ACTIVE   LAST SCHEDULE
# retraining-cronjob    */2 * * * *   False     0        <none>

# 3. Wait for first scheduled run (up to 2 min)
kubectl get jobs -n mlops-training -w
# retraining-cronjob-<timestamp>   0/1   ...   -> 1/1  Complete

# 4. Watch retraining logs
kubectl logs -n mlops-training job/retraining-cronjob-<timestamp> -f
# If flag present:
# [retraining] drift flag detected -> retraining pipeline
# [retraining] running: python3 /app/feature_engineering.py
# [retraining] running: python3 /app/train.py
# [retraining] running: python3 /app/evaluate.py
# [retraining] complete, new model approved and flag cleared
#
# If no flag:
# [retraining] no retrain_trigger.flag found, nothing to do

# 5. After retraining completes, verify:
# a. Flag is cleared
docker exec mlops-sim-worker ls /mnt/artifacts/ | grep flag
# model_approved.flag only (retrain_trigger.flag gone)

# b. New model written
docker exec mlops-sim-worker ls -lt /mnt/artifacts/model.joblib
# timestamp should be recent

# c. New MLflow run created
open http://localhost:30500
# ctr-pipeline experiment -> new run from retraining

# 6. Trigger rollout to pick up new model.joblib
kubectl rollout restart deployment/model-serving -n mlops-serving
kubectl rollout status deployment/model-serving -n mlops-serving

# 7. Verify new model is serving
curl -X POST http://localhost:30080/predict \
  -H 'Content-Type: application/json' \
  -d '{"ad_id": 42}'
# Should respond normally with updated model

# 8. Trigger a manual retraining run immediately (without waiting for schedule)
kubectl create job --from=cronjob/retraining-cronjob \
  manual-retrain-$(date +%s) -n mlops-training
kubectl logs -n mlops-training job/manual-retrain-<timestamp> -f
```

---

## PHASE 18 — Full CI/CD Loop Test (Everything Together)

```bash
# Simulate a real code change triggering the entire pipeline end-to-end

# 1. Make a meaningful change (lower AUC threshold to force promotion)
sed -i 's/AUC_THRESHOLD = 0.55/AUC_THRESHOLD = 0.50/' evaluation/evaluate_mlflow.py
git add evaluation/evaluate_mlflow.py
git commit -m "lower eval threshold to 0.50 for production"
git push origin main
# -> GitHub Actions fires: install -> smoke test -> docker build -> push to GHCR

# 2. Watch CI pass on GitHub Actions tab

# 3. Rebuild and reload image locally (simulates what CD would do)
docker build -t mlops-sim:local .
kind load docker-image mlops-sim:local --name mlops-sim

# 4. Argo CD picks up manifest changes from git (if you changed a YAML)
# For code-only changes (no manifest change), manually restart:
kubectl rollout restart deployment/model-serving -n mlops-serving

# 5. Re-run full Kubeflow pipeline with new evaluation threshold
python3 << 'EOF'
import kfp
client = kfp.Client(host="http://localhost:8888")
run = client.create_run_from_pipeline_package(
    "pipeline.yaml",
    arguments={"mlflow_uri": "http://mlflow-svc.mlops-training.svc.cluster.local:5000"},
    run_name="post-threshold-change-run"
)
print("Run ID:", run.run_id)
EOF

# 6. Watch KFP DAG: http://localhost:8888
# 7. Watch MLflow: new run appears, model v2 promoted to Production
# 8. Watch Argo CD: stays Synced (no manifest change)
# 9. Verify serving returns predictions: curl http://localhost:30080/predict -d '{"ad_id":99}'
# 10. Watch Grafana: prediction rate restarts after rollout
```

---

## PHASE 19 — Observability Checks (Full Health View)

```bash
# One-liner cluster health view
kubectl get all -A | grep -v Running | grep -v Complete

# Check all deployments are ready
kubectl get deployments -A

# Check all Jobs succeeded
kubectl get jobs -A

# Check CronJob history
kubectl get jobs -n mlops-training --sort-by=.metadata.creationTimestamp

# Tail all pipeline-related logs at once (requires stern)
# Install: https://github.com/stern/stern
stern -n mlops-data -n mlops-training -n mlops-serving -n mlops-monitoring .

# Check artifact store contents + sizes
docker exec mlops-sim-worker du -sh /mnt/artifacts/*

# Check Redis memory usage
kubectl exec -n mlops-data deploy/redis -- redis-cli INFO memory | grep used_memory_human

# Check MLflow experiment runs count
curl -s http://localhost:30500/api/2.0/mlflow/runs/search \
  -d '{"experiment_ids":["1"]}' | python3 -c "
import json,sys; d=json.load(sys.stdin)
print('Total runs:', len(d.get('runs',[])))
for r in d.get('runs',[]): print(r['info']['run_name'], r['data']['metrics'])
"
```

---

## PHASE 20 — Teardown

```bash
# Delete cluster (removes all pods, services, volumes)
kind delete cluster --name mlops-sim

# Clean up artifact store
rm -rf /tmp/mlops-artifacts

# Clean up local Docker images
docker rmi mlops-sim:local localhost:30050/mlops-sim:latest

# Clean up port-forwards (if any are still running)
pkill -f "kubectl port-forward"

# Confirm cluster is gone
kind get clusters   # should be empty
kubectl config get-contexts   # kind-mlops-sim context should be gone
```

---

## Summary Table

| Phase | What happens | Key command |
|-------|-------------|-------------|
| 0 | Install all tools | `pip install feast[redis] kfp mlflow` |
| 1 | Kind cluster up | `kind create cluster --config kind/kind-config.yaml` |
| 2 | Namespaces + PVCs | `kubectl apply -f namespaces/` |
| 3 | Local registry + image | `docker build` + `kind load` |
| 4 | GitHub CI pipeline | `git push` -> Actions auto-triggers |
| 5 | MLflow server | `kubectl apply -f mlflow/mlflow-deployment.yaml` |
| 6 | Redis online store | `kubectl apply -f feast/redis-and-materialize-job.yaml` |
| 7 | Feature engineering | `kubectl apply -f feature-engineering/job.yaml` |
| 8 | Feast materialization | `kubectl wait job/feast-materialize` -> 50k keys in Redis |
| 9 | Training + MLflow log | `kubectl apply -f training/job.yaml` |
| 10 | Evaluation + registry | model promoted to Production in MLflow |
| 11 | Kubeflow DAG | `python3 kubeflow/pipeline.py` -> upload -> run |
| 12 | Argo CD GitOps | `kubectl apply -f argocd/application.yaml` |
| 13 | Serving (Feast online) | `curl /predict {ad_id:42}` |
| 14 | Prometheus scraping | `http://localhost:30090/targets` = UP |
| 15 | Grafana dashboard | 5 panels: rate, latency, scores, feast hits |
| 16 | Drift detection | PSI > 0.2 -> `retrain_trigger.flag` written |
| 17 | Retraining CronJob | Fires every 2 min, checks flag, reruns pipeline |
| 18 | Full CI/CD loop | code change -> CI -> image -> KFP run -> new model live |
| 19 | Health checks | `kubectl get all -A`, Redis, MLflow API |
| 20 | Teardown | `kind delete cluster --name mlops-sim` |

## Total time estimate
| Section | Time |
|---------|------|
| Phases 0–3 (infra up, image built) | 2–3 hrs |
| Phases 4–5 (GitHub CI + MLflow) | 1 hr |
| Phases 6–10 (Feast + pipeline stages) | 2–3 hrs |
| Phases 11–12 (KFP + Argo CD) | 2 hrs |
| Phases 13–15 (Serving + Prometheus + Grafana) | 1–2 hrs |
| Phases 16–17 (Drift + retraining observed) | 1 hr |
| Phase 18–19 (Full loop test) | 1 hr |
| **Total** | **~10–13 hrs** |
