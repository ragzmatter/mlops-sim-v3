"""
Stage 2: Model Training
Reads features.parquet -> trains a classifier -> writes model.joblib + metrics
"""
import os, json, joblib
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score

ART_DIR = os.environ.get("ARTIFACT_DIR", "/mnt/artifacts")
FEATURES_PATH = os.path.join(ART_DIR, "features.parquet")
MODEL_PATH = os.path.join(ART_DIR, "model.joblib")
TRAIN_METRICS_PATH = os.path.join(ART_DIR, "train_metrics.json")
TEST_SPLIT_PATH = os.path.join(ART_DIR, "test_split.parquet")  # held out for eval stage

def main():
    df = pd.read_parquet(FEATURES_PATH)
    X = df.drop(columns=["click"])
    y = df["click"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    model = LogisticRegression(max_iter=500)
    model.fit(X_train, y_train)

    train_auc = roc_auc_score(y_train, model.predict_proba(X_train)[:, 1])
    print(f"[training] train AUC = {train_auc:.4f}")

    joblib.dump(model, MODEL_PATH)
    with open(TRAIN_METRICS_PATH, "w") as f:
        json.dump({"train_auc": train_auc, "n_train": len(X_train)}, f)

    test_df = X_test.copy()
    test_df["click"] = y_test
    test_df.to_parquet(TEST_SPLIT_PATH, index=False)

    print(f"[training] wrote {MODEL_PATH}, {TRAIN_METRICS_PATH}, {TEST_SPLIT_PATH}")

if __name__ == "__main__":
    main()
