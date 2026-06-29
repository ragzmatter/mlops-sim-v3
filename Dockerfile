FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    pandas numpy scikit-learn joblib pyarrow \
    fastapi uvicorn prometheus_client pydantic

COPY data/generate_dataset.py /app/generate_dataset.py
COPY feature-engineering/feature_engineering.py /app/feature_engineering.py
COPY training/train.py /app/train.py
COPY evaluation/evaluate.py /app/evaluate.py
COPY serving/app.py /app/serving_app.py
COPY monitoring/monitor.py /app/monitor.py
COPY retraining/retrain.py /app/retrain.py

ENV ARTIFACT_DIR=/mnt/artifacts

# Default command does nothing useful on its own; each K8s manifest
# overrides `command`/`args` to pick the stage to run.
CMD ["python3", "--version"]
