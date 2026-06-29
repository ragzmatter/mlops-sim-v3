"""
Stage 4: Model Serving — with Feast online feature retrieval
POST /predict accepts only {ad_id: int}
  -> fetches precomputed features from Redis via Feast
  -> runs model inference
  -> returns click probability

Also keeps /predict_raw for direct feature input (fallback / testing).
"""
import os, time, joblib
import pandas as pd
from feast import FeatureStore
from fastapi import FastAPI
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

ART_DIR   = os.environ.get("ARTIFACT_DIR", "/mnt/artifacts")
FEAST_REPO = os.environ.get("FEAST_REPO", "/app/feature_repo")

model  = joblib.load(os.path.join(ART_DIR, "model.joblib"))
store  = FeatureStore(repo_path=FEAST_REPO)

FEATURE_REFS = [
    "ad_features:num_1", "ad_features:num_2", "ad_features:num_3",
    "ad_features:cat_1", "ad_features:cat_2", "ad_features:cat_3",
    "ad_features:cat_4",
]
FEATURE_COLS = ["num_1","num_2","num_3","cat_1","cat_2","cat_3","cat_4"]

app = FastAPI(title="CTR Serving — Feast Online Store")

PRED_COUNT   = Counter("predictions_total", "Total predictions")
PRED_LATENCY = Histogram("prediction_latency_seconds", "Latency")
FEAST_HITS   = Counter("feast_online_hits_total", "Feast online lookups")

class AdIDRequest(BaseModel):
    ad_id: int          # lookup key -> Feast -> Redis -> features

class RawRequest(BaseModel):
    num_1: float; num_2: float; num_3: float
    cat_1: int;   cat_2: int;   cat_3: int;   cat_4: int

@app.get("/health")
def health(): return {"status": "ok"}

@app.post("/predict")
def predict_from_store(req: AdIDRequest):
    """Production path: feature lookup from Redis via Feast."""
    t0 = time.time()
    entity_rows = [{"ad_id": req.ad_id}]
    fv = store.get_online_features(features=FEATURE_REFS, entity_rows=entity_rows).to_dict()
    FEAST_HITS.inc()

    row = pd.DataFrame([{c: fv[c][0] for c in FEATURE_COLS}])
    score = float(model.predict_proba(row)[:, 1][0])

    PRED_COUNT.inc()
    PRED_LATENCY.observe(time.time() - t0)
    return {"ad_id": req.ad_id, "click_probability": score}

@app.post("/predict_raw")
def predict_raw(req: RawRequest):
    """Fallback / test path: caller supplies raw features directly."""
    t0 = time.time()
    row = pd.DataFrame([req.dict()])
    score = float(model.predict_proba(row)[:, 1][0])
    PRED_COUNT.inc()
    PRED_LATENCY.observe(time.time() - t0)
    return {"click_probability": score}

@app.get("/metrics")
def metrics(): return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
