"""
Stage 4: Model Serving
FastAPI app loading model.joblib + feature_pipeline.joblib from the shared
artifact store, exposing /predict and /metrics (Prometheus format).
"""
import os, time, joblib
import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

ART_DIR = os.environ.get("ARTIFACT_DIR", "/mnt/artifacts")
model = joblib.load(os.path.join(ART_DIR, "model.joblib"))
pipeline = joblib.load(os.path.join(ART_DIR, "feature_pipeline.joblib"))

app = FastAPI(title="CTR Model Serving")

PRED_COUNT = Counter("predictions_total", "Total predictions served")
PRED_LATENCY = Histogram("prediction_latency_seconds", "Prediction latency")
PRED_SCORE = Histogram("prediction_score", "Distribution of predicted CTR scores",
                        buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])

class AdRequest(BaseModel):
    num_1: float
    num_2: float
    num_3: float
    cat_1: str
    cat_2: str
    cat_3: str
    cat_4: str

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/predict")
def predict(req: AdRequest):
    start = time.time()
    row = pd.DataFrame([req.dict()])
    row[pipeline["num_cols"]] = pipeline["scaler"].transform(row[pipeline["num_cols"]])
    row[pipeline["cat_cols"]] = pipeline["encoder"].transform(row[pipeline["cat_cols"]])
    score = float(model.predict_proba(row)[:, 1][0])

    PRED_COUNT.inc()
    PRED_SCORE.observe(score)
    PRED_LATENCY.observe(time.time() - start)
    return {"click_probability": score}

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
