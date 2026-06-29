"""
Kubeflow Pipeline: CTR MLOps end-to-end
Each component = one K8s Job pod. KFP triggers the next only on success.
Run: python3 pipeline.py  -> compiles to pipeline.yaml, then submit via KFP UI or CLI.
"""
import kfp
from kfp import dsl
from kfp.components import create_component_from_func

IMAGE = "localhost:5000/mlops-sim:latest"  # local registry
ARTIFACT_DIR = "/mnt/artifacts"
MLFLOW_URI = "http://mlflow-svc.mlops-training.svc.cluster.local:5000"


def feature_engineering_op():
    import subprocess
    subprocess.run(["python3", "/app/feature_engineering.py"], check=True)

def training_op(mlflow_uri: str):
    import subprocess, os
    env = {**dict(__import__("os").environ), "MLFLOW_TRACKING_URI": mlflow_uri}
    subprocess.run(["python3", "/app/train.py"], check=True, env=env)

def evaluation_op(mlflow_uri: str) -> str:
    import subprocess, os
    env = {**dict(__import__("os").environ), "MLFLOW_TRACKING_URI": mlflow_uri}
    r = subprocess.run(["python3", "/app/evaluate.py"], env=env)
    if r.returncode != 0:
        raise RuntimeError("Evaluation gate FAILED — model not promoted")
    return "approved"

def deploy_trigger_op(approval: str):
    """Runs only if evaluation_op returns 'approved'. Patches the serving deployment."""
    import subprocess
    if approval != "approved":
        raise RuntimeError("Skipping deploy — not approved")
    subprocess.run([
        "kubectl", "rollout", "restart",
        "deployment/model-serving", "-n", "mlops-serving"
    ], check=True)


# Wrap plain functions as KFP components
feature_comp = create_component_from_func(
    feature_engineering_op, base_image=IMAGE,
    packages_to_install=[]
)
training_comp = create_component_from_func(
    training_op, base_image=IMAGE,
    packages_to_install=["mlflow"]
)
evaluation_comp = create_component_from_func(
    evaluation_op, base_image=IMAGE,
    packages_to_install=["mlflow"]
)
deploy_comp = create_component_from_func(
    deploy_trigger_op, base_image=IMAGE,
    packages_to_install=[]
)


@dsl.pipeline(name="ctr-mlops-pipeline", description="CTR end-to-end MLOps")
def ctr_pipeline(mlflow_uri: str = MLFLOW_URI):
    # --- shared PVC passed via volume (same /mnt/artifacts concept) ---
    pvc = dsl.PipelineVolume(pvc="artifacts-pvc")

    feat = feature_comp()
    feat.add_pvolumes({ARTIFACT_DIR: pvc})

    train = training_comp(mlflow_uri=mlflow_uri)
    train.add_pvolumes({ARTIFACT_DIR: pvc})
    train.after(feat)

    evl = evaluation_comp(mlflow_uri=mlflow_uri)
    evl.add_pvolumes({ARTIFACT_DIR: pvc})
    evl.after(train)

    deploy = deploy_comp(approval=evl.output)
    deploy.after(evl)


if __name__ == "__main__":
    kfp.compiler.Compiler().compile(ctr_pipeline, "pipeline.yaml")
    print("Compiled -> pipeline.yaml  (upload to KFP UI or use kfp run)")
