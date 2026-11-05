# Quant AI Researcher by Harshil Pahuja
"""Phase 0: record what Gate B v1 said for every past Lightyear run, one row per criterion.

Read-only over the run folders. Nothing is recomputed: each value is what the run's own gate_b() wrote in results.json.

    python scripts/gate_v2/freeze_gate_v1.py --outputs <repo>/outputs
"""
import argparse
import csv
import glob
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
from lightyear.gates import rows
from ros.versions import GATE_VERSION

FIELDS = ["run_id", "folder", "strategy", "gate_version", "gate_passed", "decision", "criterion", "value", "threshold", "blocking", "result"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outputs", default=os.path.join(REPO, "outputs"))
    ap.add_argument("--out", default=os.path.join(REPO, "docs", "gate_b", "gate_v1_baseline.csv"))
    a = ap.parse_args()
    assert GATE_VERSION == "v1", "this file freezes v1 and must not be rewritten by a later gate"
    out, without = [], []
    for root in sorted(glob.glob(os.path.join(a.outputs, "lightyear*"))):
        if not os.path.isdir(root):
            continue
        for rid in sorted(os.listdir(root)):
            d = os.path.join(root, rid)
            if not os.path.isdir(d):
                continue
            p = os.path.join(d, "results.json")
            if not os.path.exists(p):
                without.append(f"{os.path.basename(root)}/{rid}")
                continue
            with open(p, encoding="utf-8") as fh:
                res = json.load(fh)
            st = {}
            if os.path.exists(os.path.join(d, "state.json")):
                with open(os.path.join(d, "state.json"), encoding="utf-8") as fh:
                    st = json.load(fh)
            gb = res.get("gate_b") or {}
            for g in rows(gb.get("criteria", [])):
                out.append({"run_id": rid, "folder": os.path.basename(root), "strategy": st.get("slug") or res.get("strategy_name"),
                            "gate_version": "v1", "gate_passed": gb.get("passed"),
                            "decision": (st.get("decision") or {}).get("decision") or gb.get("decision") or "PENDING",
                            "criterion": g["name"], "value": g["value_raw"], "threshold": g["threshold_raw"],
                            "blocking": g["blocking"], "result": g["result"]})
    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        fh.write("# Quant AI Researcher by Harshil Pahuja\n")
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    print(f"{len(out)} criterion rows from {len({r['run_id'] for r in out})} runs -> {a.out}")
    print(f"{len(without)} run folders never reached results.json: {', '.join(without)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
