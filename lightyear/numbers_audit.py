# Quant AI Researcher
"""The spec audit's numbers half: recompute what the run reports from the hand-off files and the SOURCE data only,
never from the script's own derived columns (Wave 2, item 6).

1. NAV rebuild: trades.csv (execution date, action, value, adjusted close) x Ace adjusted closes (the same demerger-
   adjusted panel every run reads) + cash at the run's cash rate and cost: every daily strategy return in
   daily_returns.csv must match within TOLERANCE (0.5bp).
2. Filters from source: every BUY passed the gap limit and was above its trend average at its signal date, recomputed
   from Ace prices with the card's parameters; every holding was an index member, from the membership source.
3. Fill price: every trade's price equals the Ace unadjusted price the card's signal.params.fill_price names
   ('open' or 'close') on the execution date. A card that does not name it fails this rule.

A check that cannot run (no Ace file on this machine, a run without ISINs or adjusted closes) is reported as not run
(passed = None), never as a pass.
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd

TOLERANCE = 0.5e-4          # 0.5bp on a daily return
FFILL_LIMIT = 5             # signals read a stale close at most 5 sessions (as the runs do)


def _row(rule, passed, detail):
    return {"rule": rule, "passed": passed, "detail": detail}


def _read(run_dir, name, **kw):
    p = os.path.join(run_dir, name)
    return pd.read_csv(p, **kw) if os.path.isfile(p) else None


def _prices(isins, start, end, demergers=True):
    from ros.data import ace
    long = ace.load_long(["close", "unadj_open", "unadj_close"], start=start, end=end, demergers=demergers)
    long = long[long["isin"].isin(set(isins))]
    return {f: long.pivot(index="date", columns="isin", values=f).sort_index() for f in ("close", "unadj_open", "unadj_close")}


def nav_rebuild(dr, tr, px, params) -> dict:
    """Rebuild the book's NAV day by day from the trades alone and compare its daily returns with daily_returns.csv."""
    close = px["close"].ffill()                                       # a held name is valued at its last close
    day_rate = (1.0 + float(params.get("cash_rate", 0.0))) ** (1.0 / 252.0) - 1.0
    half = float(params.get("cost_bp", 0.0)) / 2.0 / 1e4
    cash = float(params.get("start_capital", 1.0))
    units = {}
    by_day = {d: g for d, g in tr.groupby("execution_date")}
    order = {"SELL": 0, "TRIM": 1, "ADD": 2, "BUY": 3}
    days = close.index[(close.index >= dr["date"].min() - pd.Timedelta(days=10)) & (close.index <= dr["date"].max())]
    start = tr["execution_date"].min() if len(tr) else dr["date"].min()
    first_nav_day = max(d for d in days if d < dr["date"].min()) if (days < dr["date"].min()).any() else start
    days = days[days >= min(first_nav_day, start)]
    nav = {}
    for d in days:
        cash *= 1.0 + day_rate
        g = by_day.get(d)
        if g is not None:
            for r in sorted(g.itertuples(), key=lambda r: order.get(r.action, 9)):
                v, p = float(r.value_rs), float(r.adjusted_close)
                if r.action == "BUY" or r.action == "ADD":
                    cash -= v * (1 + half)
                    units[r.isin] = units.get(r.isin, 0.0) + v / p
                elif r.action == "TRIM":
                    cash += v * (1 - half)
                    units[r.isin] = units.get(r.isin, 0.0) - v / p
                elif r.action == "SELL":
                    cash += v * (1 - half)
                    units[r.isin] = 0.0
        held = sum(u * close.at[d, i] for i, u in units.items() if u > 0 and np.isfinite(close.at[d, i]))
        nav[d] = cash + held
    nav = pd.Series(nav)
    rebuilt = nav.pct_change().reindex(dr["date"].to_numpy())
    diff = (rebuilt.to_numpy() - dr["strategy"].to_numpy())
    worst = float(np.nanmax(np.abs(diff))) if len(diff) else np.nan
    missing = int(np.isnan(rebuilt.to_numpy()).sum())
    ok = bool(missing == 0 and worst <= TOLERANCE)
    return _row(f"NAV rebuilt from trades x Ace prices matches every daily return (within {TOLERANCE * 1e4:g}bp)", ok,
                f"worst daily gap {worst * 1e4:.3f}bp over {len(dr)} sessions; {missing} session(s) not rebuilt")


def filters_from_source(tr, hold, px, sp, membership) -> list[dict]:
    """Gap limit and trend average at each BUY's signal date, recomputed from Ace; membership of every holding row."""
    out = []
    close = px["close"].ffill(limit=FFILL_LIMIT)
    buys = tr[tr["action"] == "BUY"]
    if {"gap_limit", "gap_days"} <= set(sp):
        biggest = close.pct_change(fill_method=None).abs().rolling(int(sp["gap_days"]), min_periods=1).max()
        bad = [r for r in buys.itertuples() if r.isin in biggest and r.signal_date in biggest.index
               and biggest.at[r.signal_date, r.isin] > float(sp["gap_limit"])]
        out.append(_row(f"No buy after a one-day move over {float(sp['gap_limit']):.0%} in {sp['gap_days']} days (from Ace prices)",
                        not bad, f"{len(bad)} of {len(buys)} buys; e.g. {[(str(b.signal_date.date()), b.isin) for b in bad[:3]]}"))
    if "stock_trend_days" in sp:
        n = int(sp["stock_trend_days"])
        sma = close.rolling(n, min_periods=n).mean()
        bad = [r for r in buys.itertuples() if r.isin in sma and r.signal_date in sma.index
               and np.isfinite(sma.at[r.signal_date, r.isin]) and close.at[r.signal_date, r.isin] < sma.at[r.signal_date, r.isin]]
        out.append(_row(f"No buy below its {n}-day average (from Ace prices)", not bad, f"{len(bad)} of {len(buys)} buys"))
    if membership is not None and hold is not None and len(hold):
        bad = 0
        for r in hold.itertuples():
            ok = membership.at[r.date, r.isin] if (r.date in membership.index and r.isin in membership.columns) else False
            bad += int(not ok)
        out.append(_row("Every holding was an index member at its signal date (from the membership source)", bad == 0,
                        f"{bad} of {len(hold)} holding rows"))
    return out


def fill_price_check(tr, px, sp) -> dict:
    field = str(sp.get("fill_price") or "").lower()
    if field not in ("open", "close"):
        return _row("Trades fill at the price the card names (signal.params.fill_price)", False,
                    "the card does not state fill_price ('open' or 'close')")
    ref = px[f"unadj_{field}"]
    bad = 0
    for r in tr.itertuples():
        want = ref.at[r.execution_date, r.isin] if (r.execution_date in ref.index and r.isin in ref.columns) else np.nan
        bad += int(not (np.isfinite(want) and abs(float(r.price) / want - 1) <= 1e-6))
    return _row(f"Every trade fills at the {field} of its execution date (card: fill_price = {field})", bad == 0,
                f"{bad} of {len(tr)} trades off the Ace unadjusted {field}")


def run(run_dir, card) -> list[dict]:
    sp = (card.get("signal") or {}).get("params") or {}
    dr = _read(run_dir, "daily_returns.csv", parse_dates=["date"])
    tr = _read(run_dir, "trades.csv", parse_dates=["date", "signal_date", "execution_date"])
    hold = _read(run_dir, "holdings.csv", parse_dates=["date"])
    man = {}
    if os.path.isfile(os.path.join(run_dir, "manifest.json")):
        with open(os.path.join(run_dir, "manifest.json"), encoding="utf-8") as fh:
            man = json.load(fh)
    params = man.get("params") or {}
    need = {"isin", "action", "value_rs", "adjusted_close", "execution_date", "price"}
    if dr is None or tr is None or not need <= set(tr.columns) or "strategy" not in dr.columns:
        return [_row("Numbers audit (NAV rebuild, filters from source, fill price)", None,
                     "not run: the run has no trades.csv with ISINs and adjusted closes, or no daily returns")]
    try:
        # the price basis the run used: demerger-adjusted only if its manifest hashed the demerger table
        basis = "demergers_table" in (man.get("inputs") or {})
        px = _prices(set(tr["isin"]) | set(hold["isin"] if hold is not None and "isin" in hold.columns else []),
                     tr["execution_date"].min() - pd.Timedelta(days=400), dr["date"].max(), demergers=basis)
    except (FileNotFoundError, OSError) as e:
        return [_row("Numbers audit (NAV rebuild, filters from source, fill price)", None, f"not run: {e}")]
    unpriced = sorted(set(tr["isin"]) - set(px["close"].columns))
    if unpriced:
        return [_row("Numbers audit (NAV rebuild, filters from source, fill price)", None,
                     f"not run: {len(unpriced)} traded ISIN(s) have no Ace price, e.g. {unpriced[:3]}")]
    membership = None
    try:
        from ros.data import nifty500
        src = ((card.get("universe") or {}).get("membership_source")) or "holdings_workbook"
        m = nifty500.load_membership(source=src)
        dates = pd.DatetimeIndex(sorted(set(hold["date"]))) if hold is not None else pd.DatetimeIndex([])
        membership = nifty500.membership_panel(dates, columns=sorted(set(hold["isin"])), m=m).fillna(False).astype(bool)
    except (FileNotFoundError, OSError, KeyError) as e:
        membership = None
        out_m = _row("Every holding was an index member (from the membership source)", None, f"not run: {e}")
    rows = [nav_rebuild(dr, tr, px, params), *filters_from_source(tr, hold, px, sp, membership), fill_price_check(tr, px, sp)]
    if membership is None:
        rows.append(out_m)
    return rows
