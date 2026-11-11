# Quant AI Researcher by Harshil Pahuja
"""Read the simulated statistics and score gate v1 and the approved gate v2. Thresholds come from config, never from here.

Writes docs/gate_b/calibration/{candidate_grid_no_dsr.csv, power_table_approved.csv}. Targets from the brief: false pass at
most 5% at true excess Sharpe 0 and on the pure-factor case, pass rate at least 70% at true excess Sharpe 1.0. The
selection-bias target cannot be met with the deflated Sharpe out of the gate, by the operator's ruling of 2026-11-05: the
table shows the cost. The first proposal, with the deflated Sharpe in, is kept in gate-b-v2-calibration.pdf.

    python scripts/gate_v2/analyse.py
"""
from __future__ import annotations

import itertools
import os

import pandas as pd
import yaml

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(REPO, "docs", "gate_b", "calibration")
CASES = {"level 0": ("level", 0.0, 1), "level 0.25": ("level", 0.25, 1), "level 0.5": ("level", 0.5, 1), "level 0.75": ("level", 0.75, 1), "level 1": ("level", 1.0, 1),
         "pure factor": ("pure_factor", 0.0, 1), "best of 20": ("selection", 0.0, 20), "best of 100": ("selection", 0.0, 100)}
NULLS = ["level 0", "pure factor", "best of 20", "best of 100"]


def case(df: pd.DataFrame, name: str) -> pd.DataFrame:
    s, lv, n = CASES[name]
    return df[(df["scenario"] == s) & (df["level"] == lv) & (df["n"] == n)]


def v1_tests(d: pd.DataFrame, n_trials: int = 1) -> dict[str, pd.Series]:
    return {"deflated Sharpe": d[f"v1_dsr_n{n_trials}"] >= 0.95, "worst window": d["v1_oos_worst"] >= 0.30, "bootstrap": d["v1_boot_p"] <= 0.05, "factor alpha": d["alpha_t"].abs() >= 2.0}


def v1_pass(d: pd.DataFrame, n_trials: int = 1) -> pd.Series:
    """v1's blocking tests that can vary here. With a book supplied, its two book tests also block."""
    t = v1_tests(d, n_trials)
    return t["deflated Sharpe"] & t["worst window"] & t["bootstrap"] & t["factor alpha"]


def v2_tests(d: pd.DataFrame, c: dict) -> dict[str, pd.Series]:
    return {"net edge": d["edge"] > 0, "bootstrap": d["boot_p"] <= c["boot_p"],
            "sub-period": (d["sp_pos"] >= c["min_windows"]) & (d["sp_worst"] >= c["window_floor"]),
            "factor alpha": (d["alpha"] > 0) & (d["alpha_t"] >= c["t_min"]),
            "book correlation": d["book_corr"] <= c["corr_max"], "book IR gain": d["book_ir_gain"] >= c["ir_gain_min"]}


def hard_pass(d: pd.DataFrame, c: dict) -> pd.Series:
    t = v2_tests(d, c)
    return t["net edge"] & t["bootstrap"]


def v2_pass(d: pd.DataFrame, c: dict, book: bool = True) -> pd.Series:
    """Hard blocks plus a green scorecard, the brief's test of a strong result."""
    t = v2_tests(d, c)
    out = t["net edge"] & t["bootstrap"] & t["sub-period"] & t["factor alpha"]
    return out & t["book correlation"] & t["book IR gain"] if book else out


def approved() -> dict:
    with open(os.path.join(REPO, "config", "gate_thresholds.yaml"), encoding="utf-8") as fh:
        th = yaml.safe_load(fh)
    return {"boot_p": th["bootstrap"]["p_max"], "min_windows": 4 * th["sub_period"]["min_windows_ahead_share"], "window_floor": th["sub_period"]["window_floor"],
            "t_min": th["factor_alpha"]["t_green_min"], "corr_max": th["book"]["corr_green_max"], "ir_gain_min": th["book"]["ir_gain_green_min"]}


def main() -> int:
    df = pd.read_csv(os.path.join(OUT, "sim_stats.csv.gz"))
    c = approved()
    rows = []
    grid = itertools.product([0.05, 0.075, 0.10, 0.15], [1.0, 1.28, 1.65, 2.0], [-1.25, -1.0, -0.75, -0.5], [2, 3])
    for p, t_min, wf, k in grid:
        g = {**c, "boot_p": p, "t_min": t_min, "window_floor": wf, "min_windows": k}
        row = {"boot_p": p, "t_min": t_min, "window_floor": wf, "min_windows": k}
        for nm in CASES:
            row[nm] = float(v2_pass(case(df, nm), g, False).mean())
        row["false, no skill and factor"] = max(row["level 0"], row["pure factor"])
        rows.append(row)
    pd.DataFrame(rows).to_csv(os.path.join(OUT, "candidate_grid_no_dsr.csv"), index=False, float_format="%.4f")

    table = []
    for nm in CASES:
        d = case(df, nm)
        for test, s in v1_tests(d).items():
            table.append({"gate": "v1", "test": test, "case": nm, "pass_rate": float(s.mean())})
        table.append({"gate": "v1", "test": "OVERALL, N = 1", "case": nm, "pass_rate": float(v1_pass(d, 1).mean())})
        table.append({"gate": "v1", "test": "OVERALL, N = 13", "case": nm, "pass_rate": float(v1_pass(d, 13).mean())})
        for test, s in v2_tests(d, c).items():
            table.append({"gate": "v2", "test": test, "case": nm, "pass_rate": float(s.mean())})
        table.append({"gate": "v2", "test": "STATUS PASS, hard blocks", "case": nm, "pass_rate": float(hard_pass(d, c).mean())})
        table.append({"gate": "v2", "test": "PASS and green, no book", "case": nm, "pass_rate": float(v2_pass(d, c, False).mean())})
        table.append({"gate": "v2", "test": "PASS and green, with book", "case": nm, "pass_rate": float(v2_pass(d, c, True).mean())})
    t = pd.DataFrame(table)
    t.to_csv(os.path.join(OUT, "power_table_approved.csv"), index=False, float_format="%.4f")
    print(t.pivot_table(index=["gate", "test"], columns="case", values="pass_rate", sort=False)[list(CASES)].round(3).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
