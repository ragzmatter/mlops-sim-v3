"""
Generates a synthetic CTR (click-through-rate) dataset, structurally similar
to Criteo-style ad data, but small enough to run fully on a laptop.

Columns:
  - 3 numeric features  (num_1, num_2, num_3)
  - 4 categorical features (cat_1..cat_4)  -> simulate ad/user/device ids
  - label (0/1) click, with a real underlying signal (not pure noise)
"""
import os
import numpy as np
import pandas as pd

ART_DIR = os.environ.get("ARTIFACT_DIR", "/home/claude/mlops-sim/data")
OUT_PATH = os.path.join(ART_DIR, "raw_ad_data.csv")

np.random.seed(42)
N = 50_000

num_1 = np.random.normal(50, 15, N)
num_2 = np.random.exponential(2.0, N)
num_3 = np.random.uniform(0, 100, N)

cat_1 = np.random.choice([f"device_{i}" for i in range(5)], N)      # device type
cat_2 = np.random.choice([f"site_{i}" for i in range(20)], N)       # publisher site
cat_3 = np.random.choice([f"campaign_{i}" for i in range(10)], N)   # ad campaign
cat_4 = np.random.choice([f"geo_{i}" for i in range(8)], N)         # geography

# build a real signal so the model has something to learn
cat_3_idx = np.array([int(c.split("_")[1]) for c in cat_3])
logit = (
    0.03 * (num_1 - 50)
    - 0.4 * num_2
    + 0.01 * num_3
    + 0.15 * cat_3_idx
    - 1.5
)
prob = 1 / (1 + np.exp(-logit))
label = np.random.binomial(1, prob)

df = pd.DataFrame({
    "num_1": num_1, "num_2": num_2, "num_3": num_3,
    "cat_1": cat_1, "cat_2": cat_2, "cat_3": cat_3, "cat_4": cat_4,
    "click": label,
})

os.makedirs(ART_DIR, exist_ok=True)
df.to_csv(OUT_PATH, index=False)
print(f"Saved {OUT_PATH}", df.shape, "CTR =", df.click.mean())
