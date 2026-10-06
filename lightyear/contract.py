"""Checks on the hand-off files each headless phase must write. A failed check stops the run with a clear
message instead of letting the page show half a result."""
import json
import os

import pandas as pd

from .paths import REPO

PHASE_A_KEYS = ["status", "reason", "paper_title", "slug", "card_path", "gate_a_path", "plain_summary"]
# presentation fields: a missing one is a warning shown on the page, never a failed run
PHASE_A_OPTIONAL = {"one_line": "", "how_it_works": [], "sleeves": [], "universe": "", "data": [], "approve": [],
                    "gaps": [], "success_looks_like": "", "data_verdict": "", "open_questions": [], "files": []}
RESULTS_KEYS = ["strategy_name", "benchmark_name", "headline", "evidence_supports", "gate_b", "validation", "notes"]
RESULTS_OPTIONAL = {"strengths": [], "weaknesses": [], "tables": [], "assumptions": [], "files": [],
                    "sleeve_name": None, "decisive_criterion": "", "gate_b_brief_path": None}


class ContractError(Exception):
    pass


def _abs(p):
    return p if os.path.isabs(p) else os.path.join(REPO, p)


def load_json(path):
    if not os.path.exists(path):
        raise ContractError(f"missing hand-off file: {path}")
    try:
        return json.load(open(path, encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ContractError(f"{os.path.basename(path)} is not valid JSON: {e}")


def check_phase_a(run_dir):
    d = load_json(os.path.join(run_dir, "phase_a.json"))
    missing = [k for k in PHASE_A_KEYS if k not in d]
    if missing:
        raise ContractError(f"phase_a.json is missing keys: {missing}")
    if d["status"] not in ("ok", "stopped"):
        raise ContractError(f"phase_a.json status must be ok or stopped, got {d['status']!r}")
    if d["status"] == "ok":
        for k in ("card_path", "gate_a_path"):
            if not d.get(k) or not os.path.exists(_abs(d[k])):
                raise ContractError(f"phase_a.json {k} does not exist on disk: {d.get(k)}")
    return _defaults(d, PHASE_A_OPTIONAL)


def _defaults(d, optional):
    warn = []
    for k, v in optional.items():
        if d.get(k) is None:
            if v is not None:
                warn.append(k)
            d[k] = v
    if warn:
        d["contract_warnings"] = [f"missing: {k}" for k in warn]
    return d


def check_results(run_dir):
    r = load_json(os.path.join(run_dir, "results.json"))
    missing = [k for k in RESULTS_KEYS if k not in r]
    if missing:
        raise ContractError(f"results.json is missing keys: {missing}")
    gb = r["gate_b"]
    if not isinstance(gb, dict) or "criteria" not in gb:
        raise ContractError("results.json gate_b must be gate_b(...).to_dict() with a 'criteria' list")
    if str(gb.get("decision", "PENDING")).upper() != "PENDING":
        raise ContractError(f"gate_b.decision must be PENDING (a human decides), got {gb.get('decision')!r}")
    if r["evidence_supports"] not in ("PROMOTE", "OBSERVE", "REJECT"):
        raise ContractError("evidence_supports must be PROMOTE, OBSERVE or REJECT")
    for t in r.get("tables", []) or []:
        if not os.path.exists(_abs(t.get("csv", ""))):
            raise ContractError(f"table CSV not found: {t.get('csv')}")

    path = os.path.join(run_dir, "daily_returns.csv")
    if not os.path.exists(path):
        raise ContractError("missing hand-off file: daily_returns.csv")
    df = pd.read_csv(path, parse_dates=["date"])
    for col in ("strategy", "benchmark"):
        if col not in df.columns:
            raise ContractError(f"daily_returns.csv needs a '{col}' column; has {list(df.columns)}")
    if len(df) < 60:
        raise ContractError(f"daily_returns.csv has only {len(df)} rows")
    if not df["date"].is_monotonic_increasing or df["date"].duplicated().any():
        raise ContractError("daily_returns.csv dates must be strictly increasing")
    big = (df[["strategy", "benchmark"]].abs() > 0.5).any(axis=1).sum()
    if big:
        raise ContractError(f"{big} daily returns exceed 50%: are they percentages instead of fractions?")
    return _defaults(r, RESULTS_OPTIONAL), df
