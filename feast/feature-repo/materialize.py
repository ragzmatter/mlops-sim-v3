"""
Feast Materialization Job
Reads features.parquet -> adds required columns (ad_id, event_timestamp)
-> runs `feast materialize` to push features into Redis (online store)

Run order: after feature_engineering Job, before serving Deployment starts.
"""
import os, subprocess
import pandas as pd
from datetime import datetime, timezone

ART_DIR = os.environ.get("ARTIFACT_DIR", "/mnt/artifacts")
FEAST_REPO = os.environ.get("FEAST_REPO", "/app/feature_repo")

def main():
    df = pd.read_parquet(os.path.join(ART_DIR, "features.parquet"))
    df = df.drop(columns=["click"], errors="ignore")

    # Feast needs an entity column + timestamp column in the parquet source
    df["ad_id"] = range(len(df))
    df["event_timestamp"] = datetime.now(timezone.utc)

    # cast cat cols to int (OrdinalEncoder already did this, ensure dtype)
    for c in ["cat_1","cat_2","cat_3","cat_4"]:
        df[c] = df[c].astype(int)
    for c in ["num_1","num_2","num_3"]:
        df[c] = df[c].astype("float32")

    out_path = os.path.join(ART_DIR, "features_with_ts.parquet")
    df.to_parquet(out_path, index=False)
    print(f"[feast] wrote {out_path} shape={df.shape}")

    # Apply feature definitions
    subprocess.run(["feast", "-c", FEAST_REPO, "apply"], check=True)
    print("[feast] apply done")

    # Materialize all features into Redis online store
    subprocess.run([
        "feast", "-c", FEAST_REPO, "materialize-incremental",
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    ], check=True)
    print("[feast] materialize done — features live in Redis")

if __name__ == "__main__":
    main()
