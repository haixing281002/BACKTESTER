# Quant AI Researcher by Harshil Pahuja
"""Phase 5: re-score every past Lightyear run under Gate v2 and set it beside what v1 said.

v1 comes from each run's own results.json, as recorded; v2 is computed now from the run's own hand-off files. Thresholds are
read from config. Writes docs/gate_b/v1_vs_v2.csv.

    python scripts/gate_v2/rescore.py --outputs <repo>/outputs --also outputs
"""
import argparse
import glob
import json
import os
import sys

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
from lightyear import contract, gate_run, workbook


def row_for(d: str, folder: str) -> dict | None:
    p = os.path.join(d, "results.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        res = json.load(fh)
    st = {}
    if os.path.exists(os.path.join(d, "state.json")):
        with open(os.path.join(d, "state.json"), encoding="utf-8") as fh:
            st = json.load(fh)
    v1 = res.get("gate_b") or {}
    failed_v1 = [c["name"] for c in v1.get("criteria", []) if c.get("blocking") and not c.get("passed")]
    out = {"run": os.path.basename(d), "folder": folder, "strategy": st.get("slug") or res.get("strategy_name"), "v1": "PASS" if v1.get("passed") else "FAIL", "v1_failed": "; ".join(failed_v1)}
    card = (st.get("phase_a") or {}).get("card_path") or ""
    dr = os.path.join(d, "daily_returns.csv")
    if not os.path.exists(dr):
        return {**out, "v2": "not scored", "why": "this run kept no daily_returns.csv"}
    if not card or not os.path.exists(card if os.path.isabs(card) else os.path.join(REPO, card)):
        return {**out, "v2": "not scored", "why": f"its card is not in this repository: {card or 'none recorded'}"}
    df = pd.read_csv(dr, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    extra, _ = contract.load_optional(d, df["date"])
    tr = extra.get("trades")
    if tr is None and "holdings" in extra:
        tr = workbook.derive_trades(extra["holdings"])
    spec = (st.get("spec_audit") or {}).get("n_fail")
    g = gate_run.score(d, card, res.get("headline_cost_bp"), df, tr, extra.get("holdings"), spec)
    gross = gate_run.score(d, card, res.get("headline_cost_bp"), df, tr, extra.get("holdings"), spec, use_net=False)
    s = g["summary"]
    failed_v2 = [r["name"] for r in g["hard_blocks"] if r["status"] == "FAIL"]
    red = [r["name"] for r in g["scorecard"] if r["status"] == "red"]
    green = [r["name"] for r in g["scorecard"] if r["status"] == "green"]
    if g["status"] == "PASS":
        why = "Passes every hard block that could be run."
        if out["v1"] == "FAIL":
            why += " v1's deflated Sharpe and worst-window bars are gone or eased, and alpha no longer blocks."
    else:
        why = "Fails: " + ", ".join(failed_v2) + "."
    if red:
        why += " Red on the scorecard: " + ", ".join(red) + "."
    return {**out, "v2": g["status"], "v2_gross": gross["status"], "basis": g["basis"], "net_edge": s["net_edge"], "bootstrap_p": s["bootstrap_p"], "gross_edge": gross["summary"]["net_edge"], "gross_bootstrap_p": gross["summary"]["bootstrap_p"],
            "alpha": s["alpha"], "alpha_t": s["alpha_t"], "windows_ahead": s["sub_period_positive"], "worst_window": s["sub_period_worst"], "post_publication_edge": s["post_publication_edge"],
            "scorecard_green": "; ".join(green), "scorecard_red": "; ".join(red), "tests_not_run": "; ".join(g["tests_not_run"]), "why": why}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outputs", default=os.path.join(REPO, "outputs"))
    ap.add_argument("--also", default="")
    a = ap.parse_args()
    rows, seen = [], set()
    for base in [x for x in (a.also, a.outputs) if x]:
        for root in sorted(glob.glob(os.path.join(base, "lightyear*"))):
            if not os.path.isdir(root):
                continue
            for rid in sorted(os.listdir(root)):
                d = os.path.join(root, rid)
                if rid in seen or not os.path.isdir(d):
                    continue
                r = row_for(d, os.path.basename(root))
                if r:
                    seen.add(rid)
                    rows.append(r)
                    print(rid, r.get("v1"), r.get("v2"), r.get("v2_gross", ""), flush=True)
    t = pd.DataFrame(rows).sort_values("run")
    out = os.path.join(REPO, "docs", "gate_b", "v1_vs_v2.csv")
    t.to_csv(out, index=False, float_format="%.4f")
    print(len(t), "runs ->", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
