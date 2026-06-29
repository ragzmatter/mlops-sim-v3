"""
Stage 3: Model Evaluation
Loads model + held-out test split -> computes metrics -> gate decision
(writes eval_metrics.json + a "model_approved.flag" the serving stage checks for)
"""
import os, json, joblib
import pandas as pd
from sklearn.metrics import roc_auc_score, accuracy_score, precision_score, recall_score

ART_DIR = os.environ.get("ARTIFACT_DIR", "/mnt/artifacts")
MODEL_PATH = os.path.join(ART_DIR, "model.joblib")
TEST_SPLIT_PATH = os.path.join(ART_DIR, "test_split.parquet")
EVAL_METRICS_PATH = os.path.join(ART_DIR, "eval_metrics.json")
APPROVAL_FLAG_PATH = os.path.join(ART_DIR, "model_approved.flag")

AUC_THRESHOLD = float(os.environ.get("AUC_THRESHOLD", "0.55"))

def main():
    model = joblib.load(MODEL_PATH)
    df = pd.read_parquet(TEST_SPLIT_PATH)
    X_test = df.drop(columns=["click"])
    y_test = df["click"]

    probs = model.predict_proba(X_test)[:, 1]
    preds = (probs >= 0.5).astype(int)

    metrics = {
        "auc": roc_auc_score(y_test, probs),
        "accuracy": accuracy_score(y_test, preds),
        "precision": precision_score(y_test, preds, zero_division=0),
        "recall": recall_score(y_test, preds, zero_division=0),
    }
    print(f"[evaluation] metrics = {metrics}")

    with open(EVAL_METRICS_PATH, "w") as f:
        json.dump(metrics, f, indent=2)

    approved = metrics["auc"] >= AUC_THRESHOLD
    if approved:
        with open(APPROVAL_FLAG_PATH, "w") as f:
            f.write("approved\n")
        print(f"[evaluation] APPROVED (AUC {metrics['auc']:.4f} >= {AUC_THRESHOLD})")
    else:
        if os.path.exists(APPROVAL_FLAG_PATH):
            os.remove(APPROVAL_FLAG_PATH)
        print(f"[evaluation] REJECTED (AUC {metrics['auc']:.4f} < {AUC_THRESHOLD})")
        raise SystemExit(1)  # fail the Job -> blocks deployment

if __name__ == "__main__":
    main()
