# Quant AI Researcher
"""Checks on the hand-off files each headless phase must write. A failed check stops the run with a clear
message instead of letting the page show half a result.

Added 2026-10-30 (Gate A -> Gate B audit): phase_a.json must be newer than the session that claims to have
written it, and Phase B's manifest.json must agree with the APPROVED card (sha and every parameter it states)."""
import hashlib
import json
import os
import re

import pandas as pd

from .paths import REPO

PHASE_A_KEYS = ["status", "reason", "paper_title", "slug", "card_path", "gate_a_path", "plain_summary"]
# presentation fields: a missing one is a warning shown on the page, never a failed run
PHASE_A_OPTIONAL = {"one_line": "", "how_it_works": [], "sleeves": [], "universe": "", "data": [], "approve": [],
                    "gaps": [], "success_looks_like": "", "data_verdict": "", "open_questions": [], "files": [],
                    "paper_reported": []}
WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
RESULTS_KEYS = ["strategy_name", "benchmark_name", "headline", "validation", "notes"]
RESULTS_OPTIONAL = {"strengths": [], "weaknesses": [], "tables": [], "assumptions": [], "files": [],
                    "sleeve_name": None,
                    "headline_cost_bp": None}


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


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_phase_a(run_dir, since=None):
    """`since`: a time.time() stamp taken before the session started. A phase_a.json older than that was written by
    an earlier session (a revision that died before writing, for instance) and must not be accepted as this one's."""
    p = os.path.join(run_dir, "phase_a.json")
    d = load_json(p)
    if since is not None and os.path.getmtime(p) < since - 2:
        raise ContractError("phase_a.json predates this session: the session ended without writing its hand-off, "
                            "so the Gate A shown would be the OLD one")
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
    # A run never decides. Runs no longer write a Gate B checklist (v1 was removed on 2026-11-13: Lightyear scores the gate
    # itself); an older run's results.json may still carry one, and a decision in it other than PENDING is refused.
    for where, d in (("gate_b", r.get("gate_b")), ("results.json", r)):
        if isinstance(d, dict) and str(d.get("decision", "PENDING")).upper() != "PENDING":
            raise ContractError(f"{where} decision must be PENDING (a human decides), got {d.get('decision')!r}")
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


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        if v.strip().lower() in WEEKDAYS:
            return float(WEEKDAYS[v.strip().lower()])
        try:
            return float(v.strip().replace(",", ""))
        except ValueError:
            return None
    return None


def _same(a, b):
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return abs(na - nb) <= 1e-9 * max(1.0, abs(na), abs(nb))
    return str(a).strip() == str(b).strip()


def check_card_consistency(run_dir, card_path, approval=None, results=None, comparator_columns=()):
    """Gate A -> Gate B wiring check (added 2026-10-30). The run must have been computed from the APPROVED card:

    - manifest.json exists (written by ros.data.lineage.write_run_manifest with the card among its inputs);
    - the card the script hashed is the card that was approved (approval.card_sha256) and is still on disk unchanged;
    - every parameter the card states and the manifest records agrees: backtest_plan.sample_start/sample_end,
      costs.spread_bps, universe.membership_source, n_configs_tried (the run's trial count may only be higher), and
      each signal.params key (the start rule's first_signal_date and first_signal_universe among them);
    - results.headline_cost_bp equals the card's cost;
    - a comparator or table priced at a DIFFERENT cost from the headline is labelled 'appendix' (Fix 4, 2026-10-30:
      the card decides the headline cost; other costings are allowed only as a clearly labelled appendix).

    Returns the list of checks made, each {'item', 'card', 'run', 'ok'}, so the Gate B page and the sign-off report
    can show what was verified. Raises ContractError on the first disagreement."""
    import yaml
    mp = os.path.join(run_dir, "manifest.json")
    if not os.path.exists(mp):
        raise ContractError("missing manifest.json: Phase B must record the card and its parameters with "
                            "ros.data.lineage.write_run_manifest(..., inputs={'card': <card path>, ...}, params=...)")
    m = load_json(mp)
    card_abs = _abs(card_path)
    if not os.path.exists(card_abs):
        raise ContractError(f"approved card not found on disk: {card_path}")
    with open(card_abs, encoding="utf-8") as fh:
        card = yaml.safe_load(fh) or {}
    checks = []

    def add(item, c, r, ok):
        checks.append({"item": item, "card": c, "run": r, "ok": bool(ok)})
        if not ok:
            raise ContractError(f"run disagrees with the approved card on {item}: card says {c!r}, run used {r!r}")

    disk_sha = sha256_file(card_abs)
    run_sha = ((m.get("inputs") or {}).get("card") or {}).get("sha256")
    approved_sha = (approval or {}).get("card_sha256")
    if run_sha is None:
        raise ContractError("manifest.json has no inputs.card.sha256: the script did not hash the card it ran")
    add("card sha256 (approved vs run)", approved_sha or disk_sha, run_sha, run_sha == (approved_sha or disk_sha))
    add("card sha256 (run vs file on disk now)", run_sha, disk_sha, run_sha == disk_sha)

    params = m.get("params") or {}
    bp = card.get("backtest_plan") or {}
    costs = card.get("costs") or {}
    if "start" in params and bp.get("sample_start"):
        add("window start", bp["sample_start"], params["start"], _same(bp["sample_start"], params["start"]))
    if "end" in params and bp.get("sample_end"):
        add("window end", bp["sample_end"], params["end"], _same(bp["sample_end"], params["end"]))
    if "cost_bp" in params and costs.get("spread_bps") is not None:
        add("round-trip cost (bp)", costs["spread_bps"], params["cost_bp"], _same(costs["spread_bps"], params["cost_bp"]))
    if "membership_source" in params:
        want = (card.get("universe") or {}).get("membership_source") or "holdings_workbook"
        add("universe.membership_source", want, params["membership_source"], _same(want, params["membership_source"]))
    if "n_trials" in params and card.get("n_configs_tried") is not None:
        ok = _num(params["n_trials"]) is not None and _num(params["n_trials"]) >= float(card["n_configs_tried"])
        add("trials for the deflated Sharpe (run >= card)", card["n_configs_tried"], params["n_trials"], ok)
    for k, v in ((card.get("signal") or {}).get("params") or {}).items():
        if k in params:
            add(f"signal.params.{k}", v, params[k], _same(v, params[k]))
    if results is not None and costs.get("spread_bps") is not None and results.get("headline_cost_bp") is not None:
        add("results.headline_cost_bp", costs["spread_bps"], results["headline_cost_bp"],
            _same(costs["spread_bps"], results["headline_cost_bp"]))

    # Fix 4: other costings only as a labelled appendix
    head = _num(costs.get("spread_bps"))
    names = list(comparator_columns or []) + [t.get("title", "") for t in (results or {}).get("tables", []) or []]
    for nm in names:
        for mt in re.finditer(r"(\d+(?:\.\d+)?)\s*bp", str(nm), re.IGNORECASE):
            if head is not None and abs(float(mt.group(1)) - head) > 1e-9 and "appendix" not in str(nm).lower():
                raise ContractError(f"'{nm}' is priced at {mt.group(1)}bp while the card's headline cost is {head:g}bp; "
                                    "a different costing is allowed only as an APPENDIX and its name must say so")
    checks.append({"item": "other costings labelled appendix", "card": f"{head:g}bp headline" if head is not None else "",
                   "run": "; ".join(n for n in names if re.search(r"\d\s*bp", str(n), re.IGNORECASE)) or "none", "ok": True})
    return checks


def load_optional(run_dir, dates):
    """holdings.csv, trades.csv, selection.csv, comparators.csv: optional, checked, and returned as (frames, warnings)."""
    out, warn = {}, []
    p = os.path.join(run_dir, "holdings.csv")
    if os.path.exists(p):
        h = pd.read_csv(p)
        need = {"date", "symbol", "weight"}
        if need - set(h.columns):
            warn.append(f"holdings.csv needs columns {sorted(need)}; has {list(h.columns)}")
        else:
            h["weight"] = pd.to_numeric(h["weight"], errors="coerce")
            if h["weight"].abs().max() > 5:
                warn.append("holdings.csv weights look like percentages; expected fractions of capital")
            out["holdings"] = h.dropna(subset=["weight"])
    p = os.path.join(run_dir, "trades.csv")
    if os.path.exists(p):
        t = pd.read_csv(p)
        need = {"date", "symbol", "action", "weight_before", "weight_after"}
        if need - set(t.columns):
            warn.append(f"trades.csv needs columns {sorted(need)}; has {list(t.columns)}")
        else:
            out["trades"] = t
    p = os.path.join(run_dir, "selection.csv")
    if os.path.exists(p):
        try:
            sel = pd.read_csv(p)
            need = {"signal_date", "symbol", "decision", "why"}
            if need - set(sel.columns):
                warn.append(f"selection.csv needs columns {sorted(need)}; has {list(sel.columns)}")
            else:
                out["selection"] = sel
        except pd.errors.EmptyDataError:
            warn.append("selection.csv is empty")
    p = os.path.join(run_dir, "comparators.csv")
    if os.path.exists(p):
        c = pd.read_csv(p, parse_dates=["date"])
        if "date" not in c.columns or len(c.columns) < 2:
            warn.append("comparators.csv needs a date column and one column per comparator")
        elif (c.drop(columns="date").abs() > 0.5).any().any():
            warn.append("comparators.csv has daily returns above 50%: percentages instead of fractions?")
        else:
            out["comparators"] = c[c["date"].isin(set(dates))].reset_index(drop=True)
    return out, warn


_RELABEL = ((re.compile(r"\(geometric, (\d+(?:\.\d+)?%) hurdle\)"), r"(risk-free rate \1)"),
            (re.compile(r"(\d+(?:\.\d+)?%) hurdle"), r"risk-free rate \1"),
            (re.compile(r"over the Sharpe hurdle"), "over the risk-free rate"))


def relabel(rows):
    """Labels only: rows a run wrote before 2026-11-11 said "5% hurdle"; the page and workbook say "risk-free rate 5%", and
    the geometric headline carries no qualifier. Values, sources and order are untouched."""
    out = []
    for r in rows or []:
        if isinstance(r, dict) and isinstance(r.get("label"), str):
            lab = r["label"]
            for pat, new in _RELABEL:
                lab = pat.sub(new, lab)
            r = {**r, "label": lab}
        out.append(r)
    return out
