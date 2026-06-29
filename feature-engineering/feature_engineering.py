"""
Stage 1: Feature Engineering
Reads raw CSV -> encodes categoricals, scales numerics -> writes feature parquet
+ a fitted encoder/scaler (joblib) into the shared artifact store.
"""
import os
import joblib
import pandas as pd
from sklearn.preprocessing import StandardScaler, OrdinalEncoder

ART_DIR = os.environ.get("ARTIFACT_DIR", "/mnt/artifacts")
RAW_PATH = os.path.join(ART_DIR, "raw_ad_data.csv")
OUT_FEATURES = os.path.join(ART_DIR, "features.parquet")
OUT_PIPELINE = os.path.join(ART_DIR, "feature_pipeline.joblib")

def main():
    print(f"[feature-engineering] reading {RAW_PATH}")
    df = pd.read_csv(RAW_PATH)

    num_cols = ["num_1", "num_2", "num_3"]
    cat_cols = ["cat_1", "cat_2", "cat_3", "cat_4"]

    scaler = StandardScaler()
    encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)

    df[num_cols] = scaler.fit_transform(df[num_cols])
    df[cat_cols] = encoder.fit_transform(df[cat_cols])

    df.to_parquet(OUT_FEATURES, index=False)
    joblib.dump({"scaler": scaler, "encoder": encoder,
                 "num_cols": num_cols, "cat_cols": cat_cols}, OUT_PIPELINE)

    print(f"[feature-engineering] wrote {OUT_FEATURES} shape={df.shape}")
    print(f"[feature-engineering] wrote {OUT_PIPELINE}")

if __name__ == "__main__":
    main()
