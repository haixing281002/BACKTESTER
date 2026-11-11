# Quant AI Researcher by Harshil Pahuja
"""Did the backtest do what the approved card says? An independent audit of the run's OWN hand-off files against the
card, computed by Lightyear after Phase B (added 2026-10-30). It does not trust the script's self-reported checks: it
re-reads holdings.csv, trades.csv, selection.csv, comparators.csv, daily_returns.csv and out/rebalance_log.csv and tests
each Gate A rule the card states. The result (spec_audit.json) is shown on the results tab and in the workbook Notes.

Every check is {"rule", "passed" (True / False / None = not checkable from the files), "detail"}. A failed check never
hides the result; it is shown in red above it. Gate B's statistics are a separate matter and are not touched here.
"""
import json
import os

import pandas as pd
import yaml

from .paths import REPO

WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4}


def _abs(p):
    return p if os.path.isabs(p) else os.path.join(REPO, p)


def _csv(run_dir, name, **kw):
    p = os.path.join(run_dir, name)
    if not os.path.exists(p):
        return None
    try:
        return pd.read_csv(p, **kw)
    except Exception:          # noqa: BLE001  a malformed optional file is "not checkable", not a crash
        return None


def run(run_dir, card_path, results=None):
    """Return the audit as a dict and write <run_dir>/spec_audit.json."""
    with open(_abs(card_path), encoding="utf-8") as fh:
        card = yaml.safe_load(fh) or {}
    sp = (card.get("signal") or {}).get("params") or {}
    bp = card.get("backtest_plan") or {}
    costs = card.get("costs") or {}
    port = card.get("portfolio") or {}
    out = []

    def add(rule, passed, detail):
        out.append({"rule": rule, "passed": passed, "detail": detail})

    dr = _csv(run_dir, "daily_returns.csv", parse_dates=["date"])
    tr = _csv(run_dir, "trades.csv", parse_dates=["date", "signal_date", "execution_date"])
    sel = _csv(run_dir, "selection.csv", parse_dates=["signal_date", "execution_date"])
    hold = _csv(run_dir, "holdings.csv", parse_dates=["date"])
    comp = _csv(run_dir, "comparators.csv", parse_dates=["date"])
    rb = _csv(run_dir, "out/rebalance_log.csv", parse_dates=["signal_date", "fill_date"])
    # The run's own trading calendar: the daily-returns dates plus every signal and fill date the run recorded, because the
    # first return is the session AFTER the first fill and a start rule may signal one session before the window.
    cal = None
    if dr is not None:
        extra = [tr[c] for c in ("signal_date", "execution_date") if tr is not None and c in tr.columns]
        cal = pd.DatetimeIndex(pd.concat([dr["date"], *extra]).dropna().unique()).sort_values()

    # ---- window
    if dr is not None and bp.get("sample_start") and bp.get("sample_end"):
        s, e = pd.Timestamp(bp["sample_start"]), pd.Timestamp(bp["sample_end"])
        first, last = dr["date"].min(), dr["date"].max()
        ok = (first >= s) and (last == e) and (first <= s + pd.Timedelta(days=7))
        add(f"Window {bp['sample_start']} to {bp['sample_end']}", bool(ok),
            f"daily returns run {first.date()} to {last.date()} ({len(dr)} sessions); first return is the first session after the start")
        if tr is not None:
            first_ok = pd.Timestamp(sp["first_signal_date"]) if sp.get("first_signal_date") else s
            late = int((tr["execution_date"] > e).sum()) + int((tr["signal_date"] < first_ok).sum())
            add("No trade outside the window", late == 0,
                f"{late} trades signalled before {first_ok.date()} or filled after the end")
            if sp.get("first_signal_date"):
                fs, ff = tr["signal_date"].min(), tr["execution_date"].min()
                add(f"Start rule: first signal {sp['first_signal_date']}, first fill on the sample start",
                    bool(fs == first_ok and s <= ff <= dr["date"].min()),
                    f"first signal {fs.date()}, first fill {ff.date()}; the book is invested from the first session of the window")

    # ---- signal day and lag
    wd = sp.get("signal_weekday")
    if tr is not None and cal is not None and wd is not None:
        wdi = WEEKDAYS.get(str(wd).lower(), wd if isinstance(wd, int) else None)
        if wdi is not None:
            sig = tr["signal_date"].drop_duplicates().sort_values()
            # expected signal = last session on or before that ISO week's chosen weekday
            exp = []
            for d in sig:
                target = pd.Timestamp.fromisocalendar(d.isocalendar()[0], d.isocalendar()[1], wdi + 1)
                prior = cal[cal <= target]
                exp.append(prior[-1] if len(prior) else pd.NaT)
            bad = int(sum(1 for d, x in zip(sig, exp) if pd.isna(x) or d != x))
            add(f"Signals on the {wd} close (previous session if a holiday)", bad == 0,
                f"{len(sig)} distinct signal dates; {bad} not the last session on or before that week's {wd}; "
                f"{int((sig.dt.dayofweek == wdi).sum())} fall on a {wd}")
            lag = int((card.get("signal") or {}).get("lag_days", 1) or 1)
            pos = {d: i for i, d in enumerate(cal)}
            nxt = [pos.get(d) for d in tr["signal_date"]]
            fills_ok = all(n is not None and n + lag < len(cal) and cal[n + lag] == f for n, f in zip(nxt, tr["execution_date"]))
            add(f"Every fill is exactly {lag} session after its signal", bool(fills_ok),
                f"{len(tr)} trades checked against the run's own calendar")

    # ---- filters at the moment of buying (selection.csv carries the values that decided every name)
    if sel is not None and "decision" in sel.columns:
        bought = sel[sel["decision"].astype(str).str.upper() == "BOUGHT"]
        if "biggest_move_90d" in sel.columns and sp.get("gap_limit") is not None:
            g = float(sp["gap_limit"])
            bad = int((bought["biggest_move_90d"] > g + 1e-12).sum())
            add(f"No buy with a one-day move above {g:.0%} in the look-back", bad == 0,
                f"{len(bought)} buys; {bad} had a bigger move; largest among buys {bought['biggest_move_90d'].max():.1%}")
        if "pct_vs_100d_avg" in sel.columns:
            bad = int((bought["pct_vs_100d_avg"] < -1e-12).sum())
            add("No buy below its trend average", bad == 0, f"{bad} of {len(bought)} buys were below the {sp.get('stock_trend_days', '?')}-day average")
        if "gate_open" in sel.columns and sp.get("index_filter_days"):
            bad = int((~bought["gate_open"].astype(bool)).sum())
            add(f"No buy while the index was below its {sp['index_filter_days']}-day average", bad == 0, f"{bad} of {len(bought)} buys with the gate shut")
        if "in_nifty500_list" in sel.columns:
            held_rows = sel[sel["decision"].astype(str).str.upper().isin(["BOUGHT", "KEPT"])]
            bad = int((~held_rows["in_nifty500_list"].astype(bool)).sum())
            add("Every bought or kept name was an index member at its signal date", bad == 0, f"{bad} of {len(held_rows)} held rows outside the list")
        if "rank" in sel.columns and "top_n" in sel.columns:
            bad = int((bought["rank"] > bought["top_n"]).sum())
            add(f"Every buy ranked inside the top {float(sp.get('hold_band_quantile', 0)) :.0%} band", bad == 0, f"{bad} of {len(bought)} buys ranked below the band")
        if {"atr_pct", "weight_after"} <= set(sel.columns) and sp.get("risk_factor") is not None:
            rf = float(sp["risk_factor"])
            b = bought[(bought["atr_pct"] > 0) & (bought["weight_after"] > 0)]
            ratio = b["weight_after"] / (rf / b["atr_pct"])
            # sized on the signal-day NAV, whole shares, then measured against the fill-day NAV: a few percent either way
            ok = bool(((ratio <= 1.10) & (ratio >= 0.85)).all()) if len(b) else None
            add(f"New positions sized at NAV x {rf:g} / ATR share of price (whole shares)", ok,
                f"weight / target over {len(b)} buys: min {ratio.min():.3f}, max {ratio.max():.3f} "
                "(sized on the signal-day NAV, measured on the fill-day NAV)" if len(b) else "no buys to check")

    # ---- cash is a drift, never renormalised
    if hold is not None and {"date", "weight"} <= set(hold.columns):
        gross = hold.groupby("date")["weight"].sum()
        add("Weights never renormalised to 100% (cash is a drift)", bool(gross.max() <= 1.0 + 1e-4 and gross.min() < 0.999),
            f"gross exposure per rebalance {gross.min():.1%} to {gross.max():.4%}; {int((gross < 0.999).sum())} of {len(gross)} rebalances below 100%")
    if rb is not None and {"n_held", "cash_share"} <= set(rb.columns):
        all_cash = rb[rb["n_held"] == 0]
        if len(all_cash) and dr is not None and "cash_rate" in (results or {}).get("_params", {}):
            pass
        cs = pd.to_numeric(rb["cash_share"], errors="coerce")
        add("Cash share reported at every rebalance", bool(len(cs)) and bool(cs.between(-1e-9, 1 + 1e-9).all()),
            f"{int(cs.isna().sum())} of {len(cs)} rebalances without a cash share; mean cash {rb['cash_share'].mean():.1%}, max {rb['cash_share'].max():.1%}, {len(all_cash)} all-cash rebalances")
        if port.get("allow_cash") is False and rb["cash_share"].max() > 0.01:
            add("Card forbids cash but the book held some", False, f"max cash share {rb['cash_share'].max():.1%}")

    # ---- costs: the headline is at the card's cost; any other costing differs only on trade days
    if costs.get("spread_bps") is not None:
        head = float(costs["spread_bps"])
        hb = (results or {}).get("headline_cost_bp")
        add(f"Headline charged at the card's {head:g}bp", hb is not None and abs(float(hb) - head) < 1e-9, f"results.headline_cost_bp = {hb}")
        if tr is not None and {"value_rs", "shares", "price"} <= set(tr.columns) and head == 0:
            rel = ((tr["value_rs"].abs() - tr["shares"].abs() * tr["price"]).abs() / tr["value_rs"].abs().clip(lower=1.0))
            add("Traded value = shares x price (no cost inside the fills)", bool((rel <= 1e-3).all()),
                f"largest relative gap {rel.max():.2e} over {len(tr)} fills (sells carry adjusted-unit rounding)")
        sweep = _csv(run_dir, "out/cost_sweep.csv")
        if sweep is not None and dr is not None and {"round_trip_cost_bp", "cagr"} <= set(sweep.columns):
            row = sweep[(sweep["round_trip_cost_bp"] - head).abs() < 1e-9]
            if len(row):
                years = (dr["date"].max() - dr["date"].min()).days / 365.25
                cagr = float((1 + dr["strategy"]).prod() ** (1 / years) - 1)
                add(f"Cost sweep's {head:g}bp row is the headline itself", abs(float(row['cagr'].iloc[0]) - cagr) < 2e-4,
                    f"sweep CAGR {float(row['cagr'].iloc[0]):.4%}, headline from daily_returns {cagr:.4%}")
        if comp is not None and dr is not None:
            for c in [c for c in comp.columns if "bp" in c.lower() and c != "date"]:
                tot_c = float((1 + comp[c]).prod()); tot_s = float((1 + dr["strategy"]).prod())
                add(f"'{c}' is a separate costed simulation and ends below the {head:g}bp headline", tot_c < tot_s,
                    f"growth of 1: {tot_c:.3f} vs headline {tot_s:.3f}")

    # ---- mandate flag read as the card says
    if port.get("mandate_allow_cash") is not None and results is not None:
        crit = {c["name"]: c for c in (results.get("gate_b") or {}).get("criteria", [])}
        m = crit.get("implementable within mandate")
        if m is not None:
            exp_pass = bool(port["mandate_allow_cash"]) or (rb is not None and rb["cash_share"].max() < 0.01)
            add(f"Mandate criterion judged with mandate_allow_cash = {port['mandate_allow_cash']}", bool(m.get("passed")) == exp_pass,
                f"gate_b criterion passed = {m.get('passed')}; {m.get('evidence', '')[:120]}")

    n_fail = sum(1 for c in out if c["passed"] is False)
    n_na = sum(1 for c in out if c["passed"] is None)
    summary = {"checks": out, "n_pass": sum(1 for c in out if c["passed"] is True), "n_fail": n_fail, "n_not_checkable": n_na,
               "card_path": card_path, "signature": "Quant AI Researcher by Harshil Pahuja"}
    with open(os.path.join(run_dir, "spec_audit.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1, default=str)
    return summary
