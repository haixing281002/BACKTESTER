# Quant AI Researcher by Harshil Pahuja
"""'What changed vs the previous run': the card field diff, the script sha diff and a one-line verdict, written into
state.json, the workbook Notes and the results tab after every build (added 2026-10-30), so staleness is never a question.

Trade-affecting card sections (a change here must move the trades): signal, strategy, universe_translation, selection,
costs, data_requirements, backtest_plan.sample_start / sample_end / warmup_days / rebalance_rule / weights_rule /
explicit_weights, portfolio (except mandate_allow_cash). Everything else is verdict-only or prose.
"""
import glob
import json
import os

import pandas as pd
import yaml

from ros.metrics import core

from .paths import REPO, RUNS

TRADE_SECTIONS = {"signal", "strategy", "universe_translation", "selection", "costs", "data_requirements"}
TRADE_PLAN_KEYS = {"sample_start", "sample_end", "warmup_days", "rebalance_rule", "weights_rule", "explicit_weights"}
VERDICT_PORTFOLIO_KEYS = {"mandate_allow_cash"}


def flatten(d, prefix=""):
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flatten(v, f"{prefix}{k}."))
    elif isinstance(d, list):
        for i, v in enumerate(d):
            out.update(flatten(v, f"{prefix}{i}."))
    else:
        out[prefix[:-1]] = d
    return out


def is_trade_affecting(key):
    top = key.split(".")[0]
    if top in TRADE_SECTIONS:
        return True
    if top == "backtest_plan":
        return key.split(".")[1] in TRADE_PLAN_KEYS if "." in key else False
    if top == "portfolio":
        return key.split(".")[1] not in VERDICT_PORTFOLIO_KEYS if "." in key else True
    return False


def _load_yaml(p):
    try:
        with open(p, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return None


def previous_run(st, search_dirs=None):
    """The most recent earlier run of the same slug that has a manifest.json, searched in RUNS and the archives."""
    dirs = search_dirs or [RUNS] + sorted(glob.glob(os.path.join(REPO, "outputs", "lightyear_archive_*")))
    best = None
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for rid in os.listdir(d):
            sp = os.path.join(d, rid, "state.json")
            if rid == st["id"] or not os.path.exists(sp) or not os.path.exists(os.path.join(d, rid, "manifest.json")):
                continue
            s = _load_json(sp)
            if s is None:
                continue
            if s.get("slug") != st.get("slug") or (s.get("created") or "") >= (st.get("created") or ""):
                continue
            if best is None or (s.get("created") or "") > (best[0].get("created") or ""):
                best = (s, os.path.join(d, rid))
    return best


def _metrics(rd):
    p = os.path.join(rd, "daily_returns.csv")
    if not os.path.exists(p):
        return None
    dr = pd.read_csv(p, parse_dates=["date"])
    r = pd.Series(dr["strategy"].to_numpy(dtype=float), index=pd.DatetimeIndex(dr["date"]))
    nav = core.value_from_returns(r)
    out = {"rows": len(dr), "first": str(dr["date"].min().date()), "last": str(dr["date"].max().date()),
           "cagr": core.cagr(nav), "vol": core.ann_vol(r), "max_dd": core.max_drawdown(nav),
           "returns_sha": _sha16(p)}
    t = os.path.join(rd, "trades.csv")
    if os.path.exists(t):
        out["trades"] = len(pd.read_csv(t))
    return out


def build(st, run_dir_now, search_dirs=None):
    """Return the change-log dict for this run (also used for the Notes lines)."""
    prev = previous_run(st, search_dirs)
    card_now = (st.get("phase_a") or {}).get("card_path") or ""
    man_now = _load_json(os.path.join(run_dir_now, "manifest.json")) or {}
    log = {"previous_run": None, "lines": []}
    if not prev:
        log["lines"].append("What changed vs the previous run: no earlier run of this card was found.")
        return log
    ps, prd = prev
    man_prev = _load_json(os.path.join(prd, "manifest.json")) or {}
    log["previous_run"] = ps["id"]
    sha_now = ((man_now.get("inputs") or {}).get("card") or {}).get("sha256")
    sha_prev = ((man_prev.get("inputs") or {}).get("card") or {}).get("sha256")
    script_now = (man_now.get("script") or {}).get("sha256")
    script_prev = (man_prev.get("script") or {}).get("sha256")

    # card field diff: this run's approved copy vs the previous run's approved copy (card_approved.yaml, kept since 2026-10-30)
    c_now = _load_yaml(os.path.join(run_dir_now, "card_approved.yaml")) or _load_yaml(os.path.join(REPO, card_now))
    c_prev = _load_yaml(os.path.join(prd, "card_approved.yaml"))
    changed_trade, changed_verdict = [], []
    if c_now is not None and c_prev is not None:
        f_now, f_prev = flatten(c_now), flatten(c_prev)
        for k in sorted(set(f_now) | set(f_prev)):
            if f_now.get(k) != f_prev.get(k):
                (changed_trade if is_trade_affecting(k) else changed_verdict).append(k)
        card_diff_known = True
    else:
        card_diff_known = False
    m_now, m_prev = _metrics(run_dir_now), _metrics(prd)
    same_returns = bool(m_now and m_prev and m_now["returns_sha"] == m_prev["returns_sha"])

    log.update(card_sha_now=sha_now, card_sha_prev=sha_prev, script_sha_now=script_now, script_sha_prev=script_prev,
               changed_trade_affecting=changed_trade, changed_verdict_only=changed_verdict, card_diff_known=card_diff_known,
               metrics_now=m_now, metrics_prev=m_prev, returns_identical=same_returns)
    L = log["lines"]
    L.append(f"What changed vs the previous run {ps['id']} (created {ps.get('created')}):")
    L.append(f"  card sha256 {str(sha_prev)[:12]} -> {str(sha_now)[:12]}" + (" (same card)" if sha_now == sha_prev else ""))
    if card_diff_known:
        L.append(f"  trade-affecting card fields changed: {', '.join(changed_trade) if changed_trade else 'none'}")
        L.append(f"  verdict-only / prose fields changed: {len(changed_verdict)}" + (f" ({', '.join(changed_verdict[:6])}{', ...' if len(changed_verdict) > 6 else ''})" if changed_verdict else ""))
    else:
        L.append("  card field diff: the previous run kept no approved-card copy; only the sha is compared")
    L.append(f"  script sha256 {str(script_prev)[:12]} -> {str(script_now)[:12]}" + (" (same script)" if script_now == script_prev else " (script changed)"))
    if m_now and m_prev:
        if same_returns:
            if card_diff_known and not changed_trade:
                L.append("  VERDICT: trades unchanged: no trade-affecting field changed, daily returns byte-identical.")
            elif not card_diff_known and sha_now == sha_prev:
                L.append("  VERDICT: trades unchanged: same card, daily returns byte-identical.")
            else:
                L.append("  VERDICT: daily returns byte-identical although the card changed on: "
                         + (", ".join(changed_trade) if changed_trade else "fields outside the trade-affecting sections"))
        else:
            diffs = []
            for k, label, pct in (("cagr", "CAGR", True), ("vol", "volatility", True), ("max_dd", "max drawdown", True), ("trades", "trades", False), ("rows", "return days", False)):
                a, b = m_prev.get(k), m_now.get(k)
                if a is not None and b is not None and a != b:
                    diffs.append(f"{label} {a:.2%} -> {b:.2%}" if pct else f"{label} {a} -> {b}")
            L.append("  VERDICT: results changed: " + ("; ".join(diffs) if diffs else "daily returns differ") + ".")
    return log


def _sha16(p):
    import hashlib
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:16]


def _load_json(p):
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
