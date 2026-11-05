# Quant AI Researcher by Harshil Pahuja
"""Phase 4: read the simulated statistics, and score gate v1 and every candidate for gate v2 against the brief's targets.

Writes docs/gate_b/calibration/{candidate_grid.csv, power_table.csv, proposal.json}. Nothing is written to config: a person
approves thresholds. Targets (from the brief): false pass at most 5% at true excess Sharpe 0, on the pure-factor case and on
the selection-bias case; pass rate at least 70% at true excess Sharpe 1.0.

    python scripts/gate_v2/analyse.py
"""
from __future__ import annotations

import itertools
import json
import os

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(REPO, "docs", "gate_b", "calibration")
FALSE_MAX, POWER_MIN = 0.05, 0.70
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
            "deflated Sharpe": d[f"dsr_{c['null']}_{c['basis']}_{c['floor']}"] >= c["dsr_min"],
            "sub-period": (d["sp_pos"] / d["sp_n"] > 0.5) & (d["sp_worst"] >= c["window_floor"]),
            "factor alpha": (d["alpha"] > 0) & (d["alpha_t"] >= c["t_min"]),
            "book correlation": d["book_corr"] <= c["corr_max"], "book IR gain": d["book_ir_gain"] >= c["ir_gain_min"]}


def v2_pass(d: pd.DataFrame, c: dict, book: bool = True) -> pd.Series:
    t = v2_tests(d, c)
    out = t["net edge"] & t["bootstrap"] & t["deflated Sharpe"] & t["sub-period"] & t["factor alpha"]
    return out & t["book correlation"] & t["book IR gain"] if book else out


def main() -> int:
    df = pd.read_csv(os.path.join(OUT, "sim_stats.csv.gz"))
    rows = []
    grid = itertools.product(["benchmark", "zero"], ["active", "raw"], ["1overT", "0p25", "1p0"], [0.80, 0.85, 0.90, 0.95], [-1.0, -0.75, -0.5, -0.25], [1.65, 2.0])
    for null, basis, floor, dmin, wf, t in grid:
        c = {"null": "bench" if null == "benchmark" else "zero", "basis": basis, "floor": floor, "dsr_min": dmin, "window_floor": wf, "t_min": t,
             "boot_p": 0.05, "corr_max": 0.80, "ir_gain_min": 0.05}
        row = {**c}
        for nm in CASES:
            d = case(df, nm)
            row[f"{nm} | book"] = float(v2_pass(d, c, True).mean())
            row[f"{nm} | no book"] = float(v2_pass(d, c, False).mean())
        for tag in ("book", "no book"):
            row[f"worst false | {tag}"] = max(row[f"{nm} | {tag}"] for nm in NULLS)
            row[f"meets targets | {tag}"] = row[f"worst false | {tag}"] <= FALSE_MAX and row[f"level 1 | {tag}"] >= POWER_MIN
        rows.append(row)
    g = pd.DataFrame(rows)
    g.to_csv(os.path.join(OUT, "candidate_grid.csv"), index=False, float_format="%.4f")

    ok = g[g["meets targets | no book"] & g["meets targets | book"]]
    print(f"{len(g)} candidates, {int(g['meets targets | no book'].sum())} meet the targets with no book, {int(g['meets targets | book'].sum())} with one, {len(ok)} with both")
    pick = (ok if len(ok) else g).sort_values(["level 1 | book", "level 1 | no book"], ascending=False)
    print(pick.head(12)[["null", "basis", "floor", "dsr_min", "window_floor", "t_min", "worst false | no book", "worst false | book", "level 1 | no book", "level 1 | book"]].to_string())

    # The proposal, by a stated rule and not by eye. The simulation is only a model of markets, so keep half the false-pass
    # target in reserve: worst false pass at most 2.5%. Among those, take the most power at true excess Sharpe 1.0, then the
    # strictest settings where power ties. Only the benchmark-based deflated Sharpe is eligible, as its row means something alone.
    safe = ok[(ok["null"] == "bench") & (ok["worst false | book"] <= FALSE_MAX / 2) & (ok["worst false | no book"] <= FALSE_MAX / 2)]
    chosen = safe.assign(power=safe["level 1 | book"].round(2)).sort_values(["power", "t_min", "dsr_min", "window_floor"], ascending=False).iloc[0].to_dict()
    c = {k: chosen[k] for k in ("null", "basis", "floor", "dsr_min", "window_floor", "t_min", "boot_p", "corr_max", "ir_gain_min")}

    table = []
    for nm in CASES:
        d = case(df, nm)
        for test, s in v1_tests(d).items():
            table.append({"gate": "v1", "test": test, "case": nm, "pass_rate": float(s.mean())})
        table.append({"gate": "v1", "test": "OVERALL, N = 1", "case": nm, "pass_rate": float(v1_pass(d, 1).mean())})
        table.append({"gate": "v1", "test": "OVERALL, N = 13", "case": nm, "pass_rate": float(v1_pass(d, 13).mean())})
        for test, s in v2_tests(d, c).items():
            table.append({"gate": "v2", "test": test, "case": nm, "pass_rate": float(s.mean())})
        table.append({"gate": "v2", "test": "OVERALL, no book", "case": nm, "pass_rate": float(v2_pass(d, c, False).mean())})
        table.append({"gate": "v2", "test": "OVERALL, with book", "case": nm, "pass_rate": float(v2_pass(d, c, True).mean())})
    t = pd.DataFrame(table)
    t.to_csv(os.path.join(OUT, "power_table.csv"), index=False, float_format="%.4f")
    print(t.pivot_table(index=["gate", "test"], columns="case", values="pass_rate", sort=False)[list(CASES)].round(3).to_string())

    # V floor: N = 10 near-identical versions, with and without a floor
    lv = df[df["scenario"] == "level"]
    fl = lv.groupby("level")[["dsr_n10_nofloor_bench", "dsr_n10_1overT_bench", "dsr_n10_0p25_bench", "dsr_n10_1p0_bench"]].agg(lambda s: float((s >= c["dsr_min"]).mean()))
    fl.to_csv(os.path.join(OUT, "v_floor_near_identical.csv"), float_format="%.4f")
    print(fl.round(3).to_string())

    hard = {nm: float(((case(df, nm)["edge"] > 0) & (case(df, nm)["boot_p"] <= c["boot_p"])).mean()) for nm in CASES}
    print("hard blocks alone:", {k: round(v, 3) for k, v in hard.items()})
    with open(os.path.join(OUT, "proposal.json"), "w", encoding="utf-8") as fh:
        json.dump({"thresholds": c, "n_simulated_per_case": int(case(df, "level 0").shape[0]), "any_candidate_meets_targets": bool(len(ok)), "n_candidates": len(g), "n_meeting_targets": len(ok), "hard_blocks_alone": hard,
               "false_max": FALSE_MAX, "power_min": POWER_MIN}, fh, indent=1)
    print(json.dumps(c))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
