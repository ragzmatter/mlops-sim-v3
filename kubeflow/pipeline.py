"""
Kubeflow Pipeline: CTR MLOps end-to-end (KFP v2 SDK)
Each component = one K8s Job pod. KFP triggers the next only on success.
Run: python3 pipeline.py  -> compiles to pipeline.yaml, then submit via KFP UI or CLI.
"""
from kfp import dsl, compiler

IMAGE = "localhost:30050/mlops-sim:latest"  # local registry
MLFLOW_URI = "http://mlflow-svc.mlops-training.svc.cluster.local:5000"


@dsl.component(base_image=IMAGE)
def feature_engineering_op():
    import subprocess
    subprocess.run(["python3", "/app/feature_engineering.py"], check=True)


@dsl.component(base_image=IMAGE, packages_to_install=["mlflow"])
def training_op(mlflow_uri: str):
    import subprocess, os
    env = {**os.environ, "MLFLOW_TRACKING_URI": mlflow_uri}
    subprocess.run(["python3", "/app/train.py"], check=True, env=env)


@dsl.component(base_image=IMAGE, packages_to_install=["mlflow"])
def evaluation_op(mlflow_uri: str) -> str:
    import subprocess, os
    env = {**os.environ, "MLFLOW_TRACKING_URI": mlflow_uri}
    r = subprocess.run(["python3", "/app/evaluate.py"], env=env)
    if r.returncode != 0:
        raise RuntimeError("Evaluation gate FAILED — model not promoted")
    return "approved"


@dsl.component(base_image=IMAGE)
def deploy_trigger_op(approval: str):
    import subprocess
    if approval != "approved":
        raise RuntimeError("Skipping deploy — not approved")
    subprocess.run([
        "kubectl", "rollout", "restart",
        "deployment/model-serving", "-n", "mlops-serving"
    ], check=True)


@dsl.pipeline(name="ctr-mlops-pipeline", description="CTR end-to-end MLOps")
def ctr_pipeline(mlflow_uri: str = MLFLOW_URI):
    feat = feature_engineering_op()
    feat.set_caching_options(False)

    train = training_op(mlflow_uri=mlflow_uri)
    train.after(feat)
    train.set_caching_options(False)

    evl = evaluation_op(mlflow_uri=mlflow_uri)
    evl.after(train)
    evl.set_caching_options(False)

    deploy = deploy_trigger_op(approval=evl.output)
    deploy.after(evl)
    deploy.set_caching_options(False)


if __name__ == "__main__":
    compiler.Compiler().compile(ctr_pipeline, "pipeline.yaml")
    print("Compiled -> pipeline.yaml  (upload to KFP UI or use kfp run)")