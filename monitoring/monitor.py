"""
Stage 5: Monitoring (drift detection)
Runs periodically (Deployment loop, or could be a CronJob). Compares a fresh
sample of "live" traffic distribution against the training distribution using
PSI (Population Stability Index) on num_1. If drift exceeds threshold, writes
a retrain_trigger.flag that the retraining CronJob checks for.
"""
import os, time, json
import numpy as np
import pandas as pd

ART_DIR = os.environ.get("ARTIFACT_DIR", "/mnt/artifacts")
TRAIN_FEATURES = os.path.join(ART_DIR, "features.parquet")
DRIFT_LOG = os.path.join(ART_DIR, "drift_log.json")
RETRAIN_FLAG = os.path.join(ART_DIR, "retrain_trigger.flag")
PSI_THRESHOLD = float(os.environ.get("PSI_THRESHOLD", "0.2"))
SLEEP_SECONDS = int(os.environ.get("CHECK_INTERVAL", "30"))

def psi(expected, actual, bins=10):
    breakpoints = np.percentile(expected, np.linspace(0, 100, bins + 1))
    breakpoints[0], breakpoints[-1] = -np.inf, np.inf
    e_perc = np.histogram(expected, breakpoints)[0] / len(expected) + 1e-6
    a_perc = np.histogram(actual, breakpoints)[0] / len(actual) + 1e-6
    return float(np.sum((a_perc - e_perc) * np.log(a_perc / e_perc)))

def simulate_live_traffic(baseline, drift_strength):
    # simulate live data slowly drifting away from training distribution
    return baseline + np.random.normal(drift_strength, 5, size=len(baseline))

def main():
    baseline = pd.read_parquet(TRAIN_FEATURES)["num_1"].values
    drift_strength = 0.0
    while True:
        drift_strength += 1.5  # simulate the world changing over time
        live = simulate_live_traffic(baseline, drift_strength)
        score = psi(baseline, live)
        drifted = score >= PSI_THRESHOLD

        log = {"timestamp": time.time(), "psi": score, "drifted": drifted}
        with open(DRIFT_LOG, "w") as f:
            json.dump(log, f, indent=2)
        print(f"[monitoring] PSI={score:.4f} drifted={drifted}")

        if drifted:
            with open(RETRAIN_FLAG, "w") as f:
                f.write("retrain\n")
            print("[monitoring] drift threshold exceeded -> retrain_trigger.flag written")

        time.sleep(SLEEP_SECONDS)

if __name__ == "__main__":
    main()
