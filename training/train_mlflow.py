"""
Stage 2: Training — with MLflow logging
Reads features.parquet -> trains -> logs params/metrics/model to MLflow
-> registers model in MLflow Model Registry under "ctr-model"
"""
import os, json, joblib
import pandas as pd
import mlflow, mlflow.sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score

ART_DIR = os.environ.get("ARTIFACT_DIR", "/mnt/artifacts")
MLFLOW_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")
MODEL_NAME = "ctr-model"

mlflow.set_tracking_uri(MLFLOW_URI)
mlflow.set_experiment("ctr-pipeline")


def main():
    df = pd.read_parquet(os.path.join(ART_DIR, "features.parquet"))
    X, y = df.drop(columns=["click"]), df["click"]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    params = {"C": 1.0, "max_iter": 500, "solver": "lbfgs"}

    with mlflow.start_run(run_name="training") as run:
        mlflow.log_params(params)
        model = LogisticRegression(**params)
        model.fit(X_train, y_train)

        train_auc = roc_auc_score(y_train, model.predict_proba(X_train)[:, 1])
        mlflow.log_metric("train_auc", train_auc)
        print(f"[training] train_auc={train_auc:.4f}")

        # log + register model in MLflow registry
        mlflow.sklearn.log_model(
            model, artifact_path="model",
            registered_model_name=MODEL_NAME
        )
        # also write locally for serving pod (same pattern as before)
        joblib.dump(model, os.path.join(ART_DIR, "model.joblib"))

        test_df = X_test.copy(); test_df["click"] = y_test
        test_df.to_parquet(os.path.join(ART_DIR, "test_split.parquet"), index=False)

        # pass run_id downstream for evaluation to pick up
        with open(os.path.join(ART_DIR, "run_id.txt"), "w") as f:
            f.write(run.info.run_id)

        print(f"[training] run_id={run.info.run_id}")


if __name__ == "__main__":
    main()
