"""
Stage 6: Retraining
CronJob entrypoint. Checks for retrain_trigger.flag written by the monitoring
pod. If present: re-runs feature engineering -> training -> evaluation in
sequence (in-process, same pod) and clears the flag.
"""
import os, subprocess, sys

ART_DIR = os.environ.get("ARTIFACT_DIR", "/mnt/artifacts")
FLAG = os.path.join(ART_DIR, "retrain_trigger.flag")

def run(cmd):
    print(f"[retraining] running: {cmd}")
    subprocess.run(cmd, shell=True, check=True)

def main():
    if not os.path.exists(FLAG):
        print("[retraining] no retrain_trigger.flag found, nothing to do")
        return
    print("[retraining] drift flag detected -> retraining pipeline")
    run("python3 /app/feature_engineering.py")
    run("python3 /app/train.py")
    try:
        run("python3 /app/evaluate.py")
    except subprocess.CalledProcessError:
        print("[retraining] new model REJECTED at evaluation gate, keeping old model")
        sys.exit(0)
    os.remove(FLAG)
    print("[retraining] complete, new model approved and flag cleared")

if __name__ == "__main__":
    main()
