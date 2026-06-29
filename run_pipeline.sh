#!/usr/bin/env bash
# Run this AFTER: kind create cluster --config kind/kind-config.yaml
# Builds the image, loads it into the kind node, then applies every stage
# in the correct dependency order (namespaces -> storage -> feature -> train
# -> eval -> serving -> monitoring -> retraining).
set -euo pipefail
cd "$(dirname "$0")"

mkdir -p /tmp/mlops-artifacts   # backs the shared hostPath PVs

echo "==> Building image"
docker build -t mlops-sim:local .

echo "==> Loading image into kind cluster 'mlops-sim'"
kind load docker-image mlops-sim:local --name mlops-sim

echo "==> 1) Namespaces"
kubectl apply -f namespaces/namespaces.yaml

echo "==> 2) Shared artifact storage (PV/PVC per namespace)"
kubectl apply -f namespaces/shared-storage.yaml

echo "==> 3) Feature engineering (Job)"
kubectl apply -f feature-engineering/job.yaml
kubectl wait --for=condition=complete job/feature-engineering -n mlops-data --timeout=120s

echo "==> 4) Model training (Job)"
kubectl apply -f training/job.yaml
kubectl wait --for=condition=complete job/model-training -n mlops-training --timeout=120s

echo "==> 5) Model evaluation (Job, gates deployment)"
kubectl apply -f evaluation/job.yaml
kubectl wait --for=condition=complete job/model-evaluation -n mlops-training --timeout=120s

echo "==> 6) Model serving (Deployment + Service)"
kubectl apply -f serving/deployment.yaml
kubectl rollout status deployment/model-serving -n mlops-serving --timeout=120s

echo "==> 7) Monitoring (drift detector + Prometheus)"
kubectl apply -f monitoring/deployment.yaml
kubectl apply -f monitoring/prometheus.yaml
kubectl rollout status deployment/drift-monitor -n mlops-monitoring --timeout=120s

echo "==> 8) Retraining CronJob"
kubectl apply -f retraining/cronjob.yaml

echo ""
echo "DONE. Try:"
echo "  curl -X POST http://localhost:30080/predict -H 'Content-Type: application/json' -d '{\"num_1\":55,\"num_2\":1.2,\"num_3\":40,\"cat_1\":\"device_1\",\"cat_2\":\"site_3\",\"cat_3\":\"campaign_2\",\"cat_4\":\"geo_1\"}'"
echo "  open http://localhost:30090 (Prometheus UI)"
