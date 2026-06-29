"""
Feature definitions for CTR pipeline.
Offline source  = features.parquet written by feature_engineering.py
Online store    = Redis (materialized via feast materialize)
Entity          = ad_id (simulated from row index)
"""
from datetime import timedelta
from feast import Entity, FeatureView, Field, FileSource
from feast.types import Float32, Int64

# --- Entity ---
ad = Entity(name="ad_id", description="Ad identifier (row index)")

# --- Offline source (the parquet feature_engineering wrote) ---
ad_features_source = FileSource(
    path="/mnt/artifacts/features_with_ts.parquet",  # see materialize.py
    timestamp_field="event_timestamp",
)

# --- Feature View ---
ad_feature_view = FeatureView(
    name="ad_features",
    entities=[ad],
    ttl=timedelta(days=1),
    schema=[
        Field(name="num_1",  dtype=Float32),
        Field(name="num_2",  dtype=Float32),
        Field(name="num_3",  dtype=Float32),
        Field(name="cat_1",  dtype=Int64),
        Field(name="cat_2",  dtype=Int64),
        Field(name="cat_3",  dtype=Int64),
        Field(name="cat_4",  dtype=Int64),
    ],
    source=ad_features_source,
    online=True,    # materializable to Redis
)
