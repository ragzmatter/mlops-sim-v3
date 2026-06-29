"""
Stage 3: Evaluation — logs metrics to same MLflow run, promotes model in registry
"""
import os, json, joblib
import pandas as pd
import mlflow
from mlflow.tracking import MlflowClient
from sklearn.metrics import roc_auc_score, accuracy_score, precision_score, recall_score

ART_DIR = os.environ.get("ARTIFACT_DIR", "/mnt/artifacts")
MLFLOW_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")
AUC_THRESHOLD = float(os.environ.get("AUC_THRESHOLD", "0.55"))
MODEL_NAME = "ctr-model"

mlflow.set_tracking_uri(MLFLOW_URI)
client = MlflowClient()


def main():
    run_id = open(os.path.join(ART_DIR, "run_id.txt")).read().strip()
    model = joblib.load(os.path.join(ART_DIR, "model.joblib"))
    df = pd.read_parquet(os.path.join(ART_DIR, "test_split.parquet"))
    X_test, y_test = df.drop(columns=["click"]), df["click"]

    probs = model.predict_proba(X_test)[:, 1]
    preds = (probs >= 0.5).astype(int)
    metrics = {
        "test_auc": roc_auc_score(y_test, probs),
        "accuracy": accuracy_score(y_test, preds),
        "precision": precision_score(y_test, preds, zero_division=0),
        "recall": recall_score(y_test, preds, zero_division=0),
    }
    print(f"[evaluation] {metrics}")

    with mlflow.start_run(run_id=run_id):
        mlflow.log_metrics(metrics)

    if metrics["test_auc"] < AUC_THRESHOLD:
        print(f"[evaluation] REJECTED — AUC {metrics['test_auc']:.4f} < {AUC_THRESHOLD}")
        raise SystemExit(1)

    # promote latest version to "Production" in MLflow registry
    versions = client.get_latest_versions(MODEL_NAME, stages=["None", "Staging"])
    if versions:
        v = versions[-1].version
        client.transition_model_version_stage(MODEL_NAME, v, "Production")
        print(f"[evaluation] APPROVED — promoted {MODEL_NAME} v{v} to Production")

    with open(os.path.join(ART_DIR, "model_approved.flag"), "w") as f:
        f.write("approved\n")


if __name__ == "__main__":
    main()
