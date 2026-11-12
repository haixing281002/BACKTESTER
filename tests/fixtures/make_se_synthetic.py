# Quant AI Researcher
"""Writes tests/fixtures/se_synthetic_daily.csv: SYNTHETIC daily returns for the SE Return Analytics tests. Seeded, so the
file is reproducible; it contains no real strategy or fund data. The window starts mid-year and mid-financial-year and
ends mid-month, so part-periods exist at both ends.

    python tests/fixtures/make_se_synthetic.py
"""
import os

import numpy as np
import pandas as pd

rng = np.random.default_rng(20261112)
idx = pd.bdate_range("2019-05-06", periods=1450)
b = rng.standard_t(5, 1450) * 0.009 + 4e-4
s = 0.8 * b + rng.standard_t(5, 1450) * 0.006 + 3e-4
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "se_synthetic_daily.csv")
pd.DataFrame({"date": idx.strftime("%Y-%m-%d"), "strategy": np.round(s, 10), "benchmark": np.round(b, 10)}).to_csv(out, index=False, lineterminator="\n")
print(out)
