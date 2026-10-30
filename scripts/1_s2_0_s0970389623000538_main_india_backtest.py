"""Step 04 to 07 for cards/1_s2_0_s0970389623000538_main.yaml (Saraf & Kayal 2023, 'How much does volatility
influence stock market returns? Empirical evidence from India'), run AS DRAFTED and approved at Gate A.

Sources: NSE bhavcopy (data/raw/master/bhavcopy_screener_master.csv), the NIFTY 500 close from the index
workbook, a flat 6% a year for the Sharpe numeraire. Screener industry labels (screener_industry_snapshot.csv)
are used only for the sector-concentration diagnostic. Nothing is fetched.

What it runs
  MAIN       every quarter-end close: the top 500 NSE stocks by mean traded value over the last 63 sessions
             (no look-ahead), at least 200 valid daily returns in the last 252 sessions; beta to NIFTY 500 over
             those 252 sessions; five equal-count groups (1 = lowest beta); HOLD groups 1-3 equal weighted,
             fully invested, long-only; traded at the NEXT session's close; 30bp round trip charged on every
             traded rupee (buys and sells), names that stop trading are sold at their last price at cost.
  comparators  high-risk book (groups 4-5), each single group Q1..Q5, equal-weight eligible universe (no sort),
             inverse-vol eligible universe, variance-sorted version of the main book, Q2-Q3, Q1, Q1-Q2.
  sweeps     126-day window, monthly and semi-annual rebalance, cost 0-150bp, cash rate 4-8%, random-selection
             placebo (same size, same dates), drop-the-best-quarter.
The books are built by build_basket() (plain, testable code, same as the ssrn_962461 script) with equal weights.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", message="Mean of empty slice")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER = os.path.join(REPO, "data", "raw", "master", "bhavcopy_screener_master.csv")
INDUSTRY = os.path.join(REPO, "data", "raw", "master", "screener_industry_snapshot.csv")
INDEX_PATH = os.path.join(REPO, "data", "raw", "NSE_Broad_Factor_Indices_Historical_Data.xlsx")
CARD = os.path.join(REPO, "cards", "1_s2_0_s0970389623000538_main.yaml")
OUT = os.path.join(REPO, "outputs")
SLUG = "1_s2_0_s0970389623000538_main"

TOP_N, UNIV_WINDOW, UNIV_MIN = 500, 63, 40
WINDOW, MIN_VALID = 252, 200
MIN_ELIGIBLE = 150
FIRST_FORMATION = pd.Timestamp("2022-12-30")     # card: first formation end-December 2022
LIVE_END = pd.Timestamp("2026-09-18")            # card: last day NIFTY 500 is held
SPREAD_BPS, CASH_RATE = 30.0, 0.06
N_CONFIGS_TRIED = 16                             # the card's own count (a floor)
BLOCK = 63
N_GROUPS = 5


# ---------------------------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------------------------
def load_panel(path: str = MASTER):
    m = pd.read_csv(path, usecols=["date", "security_id", "symbol", "adj_close", "adv"], parse_dates=["date"])
    px = m.pivot(index="date", columns="security_id", values="adj_close").sort_index()
    adv = m.pivot(index="date", columns="security_id", values="adv").reindex(px.index)
    names = m.sort_values("date").groupby("security_id")["symbol"].last().to_dict()
    return px, adv, names


def load_nifty500():
    from universal_backtester.data import load_banner_workbook
    d, _ = load_banner_workbook(INDEX_PATH, sheet="Broad Market")
    return d["NIFTY 500 Close"].dropna()


# ---------------------------------------------------------------------------------------------
# Signal: trailing beta / variance, point-in-time universe, quintiles
# ---------------------------------------------------------------------------------------------
def risk_stats(Rn: np.ndarray, Mn: np.ndarray, i: int, window: int):
    """Beta to the market and variance of each column over the `window` sessions ending at row i
    (inclusive), using only sessions where both the stock's return and the market's return exist.
    Returns beta, variance, number of valid returns. Rn is NaN where a return cannot be computed
    (no price yesterday or today) -- a gap is never filled."""
    lo = max(0, i - window + 1)
    X, mk = Rn[lo:i + 1], Mn[lo:i + 1]
    valid = ~np.isnan(X) & ~np.isnan(mk)[:, None]
    n = valid.sum(0).astype(float)
    Xz = np.where(valid, X, 0.0)
    mz = np.where(valid, mk[:, None], 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mx, mm = Xz.sum(0) / n, mz.sum(0) / n
        cov = (Xz * mz).sum(0) / n - mx * mm
        vm = (mz ** 2).sum(0) / n - mm ** 2
        vx = ((Xz ** 2).sum(0) / n - mx ** 2) * n / (n - 1)
        beta = cov / vm
    return beta, vx, n


def universe_at(An: np.ndarray, i: int, top_n: int = TOP_N):
    """Boolean mask: top `top_n` columns by mean traded value over the UNIV_WINDOW sessions ending at row i
    (inclusive; the formation close is known), with at least UNIV_MIN sessions of data."""
    w = An[max(0, i - UNIV_WINDOW + 1):i + 1]
    cnt = (~np.isnan(w)).sum(0)
    with np.errstate(invalid="ignore"):
        mean = np.where(cnt >= UNIV_MIN, np.nanmean(np.where(np.isnan(w), np.nan, w), axis=0), np.nan)
    ok = np.where(~np.isnan(mean))[0]
    order = ok[np.lexsort((ok, -mean[ok]))]       # highest traded value first, ties by column (security id)
    mask = np.zeros(An.shape[1], dtype=bool)
    mask[order[:top_n]] = True
    return mask


def formation_selection(Rn, Mn, An, idx_list, window=WINDOW, min_valid=MIN_VALID, measure="beta"):
    """For each formation row index: eligible columns, group number 1..5 (1 = lowest risk), score."""
    sel, carried = {}, []
    prev = None
    for i in idx_list:
        beta, var, n = risk_stats(Rn, Mn, i, window)
        score = beta if measure == "beta" else var
        elig = universe_at(An, i) & (n >= min_valid) & np.isfinite(score)
        k = int(elig.sum())
        if k < MIN_ELIGIBLE:
            carried.append(i)
            if prev is not None:
                sel[i] = prev
            continue
        cols = np.where(elig)[0]
        order = cols[np.lexsort((cols, score[cols]))]        # ascending risk, ties by column (security id)
        grp = np.zeros(len(score), dtype=int)
        grp[order] = (np.arange(k) * N_GROUPS) // k + 1
        sel[i] = {"elig": elig, "group": grp, "score": score, "beta": beta, "var": var, "k": k}
        prev = sel[i]
    return sel, carried


def formation_rows(cal: pd.DatetimeIndex, freq: str):
    """Row indices of the last session of each month / quarter / half-year from FIRST_FORMATION, with a next
    session inside the window (the trade day)."""
    s = pd.Series(np.arange(len(cal)), index=cal)
    last = s.groupby(cal.to_period("M")).max()
    months = {"monthly": None, "quarterly": (3, 6, 9, 12), "semiannual": (6, 12)}[freq]
    rows = []
    for per, i in last.items():
        d = cal[i]
        if d < FIRST_FORMATION or i + 1 >= len(cal):
            continue
        if months is None or per.month in months:
            rows.append(int(i))
    return rows


# ---------------------------------------------------------------------------------------------
# Book: equal-weight basket, net of costs (same accounting as scripts/ssrn_962461_india_backtest.py)
# ---------------------------------------------------------------------------------------------
def build_basket(pv: pd.DataFrame, weight_base, members: pd.DataFrame, recon_dates, cap: float, half: float,
                 record: bool = False):
    """A daily book level, net of its own trading costs.

    At each trade day close: target weights over that day's members with a price, proportional to `weight_base`
    or equal if None; trading the drifted book to the target costs `half` x traded (traded = sum of absolute
    weight changes, buys plus sells). Between trade days the book drifts with prices. A held name whose price
    disappears (delisted, suspended more than 5 sessions) is sold at its last price at cost and the proceeds
    reinvested pro rata, also at cost -- never quietly zeroed."""
    dates = pv.index
    cols = members.columns[members.any()]
    P = pv[cols].to_numpy(dtype=float)
    M = members[cols].to_numpy(dtype=bool)
    B = weight_base[cols].reindex(dates).to_numpy(dtype=float) if weight_base is not None else None
    rset = set(pd.DatetimeIndex(recon_dates))
    L, units, lastp, bcash = 1.0, np.zeros(len(cols)), np.full(len(cols), np.nan), 0.0
    level, diag, forced = [], [], 0
    W = np.zeros((len(dates), len(cols)), dtype=np.float32) if record else None
    for i, d in enumerate(dates):
        p = P[i]
        if i > 0 and (units > 0).any():
            held = units > 0
            gone = held & np.isnan(p)
            live = held & ~gone
            val_live = float(np.sum(units[live] * p[live]))
            if gone.any():
                proceeds = float(np.sum(units[gone] * lastp[gone])) * (1 - half)
                units[gone] = 0.0
                forced += int(gone.sum())
                if val_live > 0:
                    units[live] += proceeds * (1 - half) * (units[live] * p[live] / val_live) / p[live]
                    val_live += proceeds * (1 - half)
                else:
                    bcash += proceeds
            L = val_live + bcash
        if d in rset:
            ok = M[i] & ~np.isnan(p)
            if B is not None:
                ok &= np.isfinite(B[i]) & (B[i] > 0)
            if ok.any():
                base = B[i][ok] if B is not None else np.ones(ok.sum())
                w = np.zeros(len(cols))
                w[ok] = base / base.sum()
                drift = np.where(units > 0, units * np.nan_to_num(p) / L, 0.0) if L > 0 and i > 0 else np.zeros(len(cols))
                traded = float(np.abs(w - drift).sum())
                L *= 1 - half * traded
                units = np.where(w > 0, L * w / np.where(ok, p, 1.0), 0.0)
                bcash = 0.0
                diag.append({"date": d, "names": int(ok.sum()), "members_without_price": int((M[i] & ~ok).sum()),
                             "max_weight": float(w.max()), "traded": traded if i > 0 else float("nan")})
        lastp = np.where(np.isnan(p), lastp, p)
        level.append(L)
        if record and L > 0:
            W[i] = np.where(units > 0, units * np.nan_to_num(p) / L, 0.0)
    out = (pd.Series(level, index=dates), pd.DataFrame(diag), forced)
    if record:
        return out + (pd.DataFrame(W, index=dates, columns=cols),)
    return out


def members_from(sel, groups, trade_dates, cal, columns):
    """Boolean date x security mask: True on each trade date for the names in the chosen groups."""
    m = np.zeros((len(cal), len(columns)), dtype=bool)
    pos = {d: j for j, d in enumerate(cal)}
    for i, td in trade_dates.items():
        s = sel.get(i)
        if s is None:
            continue
        if groups == "all":
            m[pos[td]] = s["elig"]
        else:
            m[pos[td]] = np.isin(s["group"], groups)
    return pd.DataFrame(m, index=cal, columns=columns)


# ---------------------------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------------------------
def rf_series(index, rate):
    return pd.Series((1 + rate) ** (1 / 252) - 1, index=index)


def live_slice(level: pd.Series, start, end):
    v = level.loc[(level.index >= start) & (level.index <= end)]
    v = v / v.iloc[0]
    return v, v.pct_change(fill_method=None).iloc[1:]


def stats(v, r, label, rate=CASH_RATE):
    from universal_backtester.metrics import ann_vol, cagr, max_drawdown, sharpe
    c, vol = cagr(v), ann_vol(r)
    return {"name": label, "cagr": c, "vol": vol, "sharpe_vs_6pct": (c - CASH_RATE) / vol if vol > 0 else float("nan"),
            "sharpe_excess_daily": sharpe(v, r, rf_series(r.index, rate)), "max_dd": max_drawdown(v),
            "n_obs": len(r), "start": str(v.index.min().date()), "end": str(v.index.max().date())}


def paired(a: pd.Series, b: pd.Series, n_boot: int):
    from universal_backtester.validation import bootstrap_sharpe_ci
    d = (a - b.reindex(a.index)).fillna(0.0)
    r = bootstrap_sharpe_ci(d, block_size=BLOCK, n_resamples=n_boot, seed=0)
    return {"ci_low": r.ci_low, "ci_high": r.ci_high, "point": r.point_estimate, "p_not_positive": 1 - r.fraction_positive}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-charts", action="store_true")
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--n-placebo", type=int, default=100)
    ap.add_argument("--handoff", default=os.path.join(OUT, "lightyear", "20261013-144347-3bf7"))
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    from ros.validation.portfolio import factor_fingerprint
    from universal_backtester.engine import LookaheadError, assert_causal
    from universal_backtester.validation import (
        bootstrap_sharpe_ci,
        deflated_sharpe_from_returns,
        oos_stability_summary,
        walk_forward_windows,
    )
    res: dict = {}
    half = SPREAD_BPS / 1e4 / 2
    pr = lambda *x, **k: print(*x, flush=True, **k)

    pr("Card: 1_s2_0_s0970389623000538_main  (AS DRAFTED and approved at Gate A)")
    # ---------------- Stage 04: point-in-time inputs ------------------------------------------
    pr("\n" + "=" * 100 + "\nSTAGE 04 -- POINT-IN-TIME INPUTS\n" + "=" * 100)
    px, adv, names = load_panel()
    nifty = load_nifty500()
    end = min(nifty.index.max(), px.index.max(), LIVE_END)
    cal = px.index[px.index <= end]
    px, adv = px.loc[cal], adv.loc[cal]
    pv = px.ffill(limit=5)
    cols = px.columns
    nl = nifty.reindex(cal)
    res["nifty_days_missing_on_calendar"] = int(nl.isna().sum())
    pr(f"Master: {px.shape[1]} securities, {cal.min().date()} -> {cal.max().date()} ({len(cal)} sessions); "
       f"NIFTY 500 workbook ends {nifty.index.max().date()}; NIFTY 500 days missing on the bhavcopy calendar: "
       f"{res['nifty_days_missing_on_calendar']} (carried forward for the benchmark; beta uses only days it has)")
    R = px.pct_change(fill_method=None)       # NaN across any gap in the stock's own prices
    Rn = R.to_numpy(dtype=float)
    Mn = nl.pct_change(fill_method=None).to_numpy(dtype=float)
    An = adv.to_numpy(dtype=float)
    nifty_lvl = nl.ffill()
    last_px = px.apply(lambda s: s.last_valid_index())
    stopped = int((last_px < cal[-1] - pd.Timedelta(days=30)).sum())
    pr(f"Securities whose last price is more than 30 days before {cal[-1].date()} (stopped trading, kept in the panel): {stopped}")

    def run_variant(freq="quarterly", window=WINDOW, measure="beta"):
        rows = formation_rows(cal, freq)
        mv = MIN_VALID if window == WINDOW else int(round(MIN_VALID * window / WINDOW))
        sel, carried = formation_selection(Rn, Mn, An, rows, window, mv, measure)
        tdates = {i: cal[i + 1] for i in sel}
        return rows, sel, carried, tdates

    rows_q, sel_q, carried_q, td_q = run_variant()
    first_trade = td_q[rows_q[0]]
    pr(f"Quarterly formations: {len(rows_q)} from {cal[rows_q[0]].date()} to {cal[rows_q[-1]].date()}; first trade "
       f"{first_trade.date()}; formations with fewer than {MIN_ELIGIBLE} eligible names (book carried): {len(carried_q)}")
    elig_n = pd.Series({cal[i].date(): s["k"] for i, s in sel_q.items()})
    pr(f"Eligible names per formation: min {elig_n.min()}, mean {elig_n.mean():.0f}, max {elig_n.max()} (group size about {elig_n.mean()/5:.0f})")
    res["eligible"] = {"min": int(elig_n.min()), "mean": float(elig_n.mean()), "max": int(elig_n.max()), "formations": len(rows_q),
                       "carried": len(carried_q)}
    first_sel = sel_q[rows_q[0]]
    gone15 = [names[cols[j]] for j in np.where(first_sel["elig"])[0] if last_px.iloc[j] < cal[-1] - pd.Timedelta(days=30)]
    res["first_formation_names_later_stopped"] = gone15
    pr(f"Of the {first_sel['k']} eligible at the first formation, {len(gone15)} later stopped trading: {', '.join(gone15[:20])}")

    # --- look-ahead tripwires ---
    pr("\nLook-ahead tripwires:")
    # (1) score panel as the book sees it: formation-date beta, known from the formation close, tradeable from the next session
    sc = pd.DataFrame(np.nan, index=cal, columns=cols)
    ordered = sorted(sel_q)
    for k, i in enumerate(ordered):
        j2 = ordered[k + 1] + 1 if k + 1 < len(ordered) else len(cal)
        s = sel_q[i]
        sc.iloc[i + 1:j2] = np.where(s["elig"], s["beta"], np.nan)
    elig_cols = [c for c in cols if sc[c].notna().sum() >= 60][:400]
    try:
        assert_causal(sc[elig_cols], R[elig_cols], label="trailing beta")
        pr("  PASS  trailing beta (held from the day after formation) vs return[t], return[t+1]")
        res["tripwire_beta"] = "PASS"
    except LookaheadError as e:
        pr(f"  FAIL  {e}")
        res["tripwire_beta"] = f"FAIL {e}"
    for label, planted in (("planted same-bar leak", R[elig_cols]), ("planted next-bar leak", R[elig_cols].shift(-1))):
        try:
            assert_causal(planted, R[elig_cols], label=label)
            pr(f"  BROKEN  negative control '{label}' was NOT caught")
            res[f"control_{label}"] = "NOT CAUGHT"
        except LookaheadError:
            pr(f"  PASS  negative control '{label}' correctly caught")
            res[f"control_{label}"] = "caught"
    # (2) truncation: rebuild the selection from data that stops at a mid-window formation; nothing before it may move
    cut_i = rows_q[len(rows_q) // 2]
    cut = cal[cut_i]
    sel_c, _ = formation_selection(Rn[:cut_i + 1], Mn[:cut_i + 1], An[:cut_i + 1], [i for i in rows_q if i <= cut_i])
    diffs = 0
    for i, s in sel_c.items():
        o = sel_q[i]
        diffs += int((s["elig"] != o["elig"]).sum() + (s["group"] != o["group"]).sum())
    pr(f"  {'PASS' if diffs == 0 else 'FAIL'}  truncation test at {cut.date()}: data after the cut removed, "
       f"{diffs} eligibility/group assignments change across {len(sel_c)} formations")
    res["truncation_test"] = {"cut": str(cut.date()), "assignments_changed": diffs, "pass": diffs == 0}
    # (3) the trade day follows the formation day
    ok_lag = all(td_q[i] > cal[i] for i in sel_q)
    pr(f"  {'PASS' if ok_lag else 'FAIL'}  every trade date is a later session than its formation date (lag 1)")
    res["lag_check"] = ok_lag

    # ---------------- Stage 05: the books ------------------------------------------------------
    pr("\n" + "=" * 100 + "\nSTAGE 05 -- BUILD AND EXECUTE\n" + "=" * 100)
    cal_ix = pd.DatetimeIndex(cal)

    def book(sel, tds, groups, spread=SPREAD_BPS, base=None, record=False):
        mem = members_from(sel, groups, tds, cal_ix, cols)
        return build_basket(pv, base, mem, sorted(tds.values()), 1.0, spread / 1e4 / 2, record=record)

    lv_main, d_main, f_main, W_main = book(sel_q, td_q, [1, 2, 3], record=True)
    lv_hi, d_hi, f_hi = book(sel_q, td_q, [4, 5])
    lv_ew, d_ew, f_ew = book(sel_q, td_q, "all")
    inv_base = pd.DataFrame(np.nan, index=cal_ix, columns=cols)
    for i, td in td_q.items():
        inv_base.loc[td] = np.where(sel_q[i]["elig"] & (sel_q[i]["var"] > 0), 1.0 / np.sqrt(np.maximum(sel_q[i]["var"], 1e-12)), np.nan)
    lv_iv, d_iv, f_iv = book(sel_q, td_q, "all", base=inv_base)
    quint = {f"Q{g}": book(sel_q, td_q, [g])[0] for g in range(1, 6)}
    lv_q23, _, _ = book(sel_q, td_q, [2, 3])
    lv_q12, _, _ = book(sel_q, td_q, [1, 2])
    rows_v, sel_v, carried_v, td_v = run_variant(measure="var")
    lv_var, d_var, _ = book(sel_v, td_v, [1, 2, 3])
    lv_var_hi, _, _ = book(sel_v, td_v, [4, 5])

    books = {"Low-risk book (Q1-Q3 by beta)": lv_main, "High-risk book (Q4-Q5 by beta)": lv_hi,
             "Equal-weight eligible universe": lv_ew, "Inverse-vol eligible universe": lv_iv,
             "Q1 (lowest beta)": quint["Q1"], "Q2": quint["Q2"], "Q3": quint["Q3"], "Q4": quint["Q4"], "Q5 (highest beta)": quint["Q5"],
             "Q2-Q3 book": lv_q23, "Q1-Q2 book": lv_q12,
             "Variance-sorted low-risk (Q1-Q3)": lv_var, "Variance-sorted high-risk (Q4-Q5)": lv_var_hi}
    MAIN, HI, EW = list(books)[0], list(books)[1], list(books)[2]
    live = {k: live_slice(v, first_trade, end) for k, v in books.items()}
    nv, nret = live_slice(nifty_lvl, first_trade, end)
    v_main, ret_main = live[MAIN]
    rows = [stats(v, r, k) for k, (v, r) in live.items()] + [stats(nv, nret, "NIFTY 500")]
    summary = pd.DataFrame(rows)
    yrs = (v_main.index[-1] - v_main.index[0]).days / 365.25
    for k, dg in ((MAIN, d_main), (HI, d_hi), (EW, d_ew)):
        summary.loc[summary["name"] == k, "annual_two_way_turnover"] = float(dg["traded"].dropna().sum() / yrs)
    headline = summary[summary["name"].isin([MAIN, "NIFTY 500"])]
    appendix = summary[~summary["name"].isin([MAIN, "NIFTY 500"])]
    pd.set_option("display.width", 250)
    pr(f"RESULTS, {v_main.index.min().date()} -> {v_main.index.max().date()} ({len(ret_main)} daily returns; costs inside every book; price return)")
    pr(headline.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    pr("\nAPPENDIX (must-beat comparators and variants; not the headline):")
    pr(appendix.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    headline.to_csv(os.path.join(OUT, f"{SLUG}_comparison.csv"), index=False)
    appendix.to_csv(os.path.join(OUT, f"{SLUG}_comparators_appendix.csv"), index=False)
    res["comparison"] = headline.to_dict("records")
    res["comparators_appendix"] = appendix.to_dict("records")
    ann_to = float(d_main["traded"].dropna().sum() / yrs)
    res["annual_two_way_turnover"] = ann_to
    res["costs_note"] = f"{SPREAD_BPS:.0f}bp round trip = {half*1e4:.0f}bp per side on every traded rupee"
    pr(f"\nMain book annual two-way turnover {ann_to:.0%}; forced exits (names that stopped trading while held): {f_main}")

    # --- sanity: names held, largest weight, flags ---
    dm = d_main.copy()
    dm["max_drifted_weight_to_next"] = np.nan
    wmax = W_main.max(axis=1)
    held_n = (W_main > 0).sum(axis=1)
    dm["min_names_until_next"] = np.nan
    td_list = list(dm["date"])
    for k, d0 in enumerate(td_list):
        d1 = td_list[k + 1] if k + 1 < len(td_list) else cal_ix[-1]
        seg = slice(d0, d1)
        dm.loc[dm.index[k], "max_drifted_weight_to_next"] = float(wmax.loc[seg].max())
        dm.loc[dm.index[k], "min_names_until_next"] = int(held_n.loc[seg].min())
    dm.to_csv(os.path.join(OUT, f"{SLUG}_rebalance_diagnostics.csv"), index=False)
    few = dm[dm["names"] < 5]
    big = dm[dm["max_drifted_weight_to_next"] > 0.25]
    pr(f"SANITY: names held at each rebalance min {dm['names'].min()} / mean {dm['names'].mean():.0f} / max {dm['names'].max()}; "
       f"largest single weight at any rebalance {dm['max_weight'].max():.2%}; largest drifted weight on any day {wmax.max():.2%}; "
       f"rebalances with fewer than 5 names: {len(few)}; with a weight above 25%: {len(big)}")
    res["sanity"] = {"names_min": int(dm["names"].min()), "names_mean": float(dm["names"].mean()), "names_max": int(dm["names"].max()),
                     "max_weight_rebalance": float(dm["max_weight"].max()), "max_weight_any_day": float(wmax.max()),
                     "rebalances_lt5": len(few), "rebalances_over25": len(big),
                     "members_without_price_max": int(dm["members_without_price"].max())}

    # --- worst days ---
    Rf = R.reindex(columns=W_main.columns)
    contrib = (W_main.shift(1) * Rf).fillna(0.0)          # weight at the previous close x today's return
    worst = ret_main.nsmallest(5)
    wd = []
    for d, r_ in worst.items():
        c = contrib.loc[d].sort_values()
        wd.append({"date": str(d.date()), "strategy": float(r_), "nifty500": float(nret.get(d, np.nan)),
                   "equal_weight_universe": float(live[EW][1].get(d, np.nan)),
                   "worst_contributors": ", ".join(f"{names[s]} {v:+.2%}" for s, v in c.head(3).items()),
                   "share_of_held_names_down": float((Rf.loc[d][W_main.shift(1).loc[d] > 0] < 0).mean())})
    wd = pd.DataFrame(wd)
    pr("\nFIVE WORST DAYS (strategy vs NIFTY 500; contributions = previous-close weight x that day's return):")
    pr(wd.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    wd.to_csv(os.path.join(OUT, f"{SLUG}_worst_days.csv"), index=False)
    res["worst_days"] = wd.to_dict("records")

    # --- holdings ---
    hrows = []
    sel_by_td = {td_q[i]: sel_q[i] for i in sel_q}
    for _, row in d_main.iterrows():
        td = row["date"]
        s = sel_by_td[td]
        pos = cal_ix.get_loc(td)
        w_ = W_main.iloc[pos]
        for sid in w_.index[w_ > 0]:
            j = cols.get_loc(sid)
            hrows.append({"date": td.date().isoformat(), "symbol": names[sid], "leg": "long", "weight": float(w_[sid]),
                          "price": float(pv.iloc[pos, j]), "beta_252d": float(s["beta"][j]), "beta_group": int(s["group"][j])})
    holdings = pd.DataFrame(hrows)
    holdings.to_csv(os.path.join(OUT, f"{SLUG}_holdings.csv"), index=False)
    pr(f"Holdings: {len(holdings)} rows over {holdings['date'].nunique()} rebalances")

    # --- per-period table and rank IC (gross, per stock) ---
    td_sorted = sorted(td_q.values())
    per = []
    ic_b, ic_v = [], []
    for k in range(len(td_sorted) - 1):
        a0, a1 = td_sorted[k], td_sorted[k + 1]
        rowd = {"from": a0.date().isoformat(), "to": a1.date().isoformat()}
        for lab, lv in [("Q1", quint["Q1"]), ("Q2", quint["Q2"]), ("Q3", quint["Q3"]), ("Q4", quint["Q4"]), ("Q5", quint["Q5"]),
                        ("Low-risk Q1-Q3", lv_main), ("High-risk Q4-Q5", lv_hi), ("Equal-weight universe", lv_ew), ("NIFTY 500", nifty_lvl)]:
            rowd[lab] = float(lv.loc[a1] / lv.loc[a0] - 1)
        per.append(rowd)
        i0 = [i for i in sel_q if td_q[i] == a0][0]
        fwd = (pv.loc[a1] / pv.loc[a0] - 1).to_numpy()
        s = sel_q[i0]
        m_ = s["elig"] & np.isfinite(fwd)
        ic_b.append(float(pd.Series(s["score"][m_]).corr(pd.Series(fwd[m_]), method="spearman")))
        sv = sel_v[[i for i in sel_v if td_v[i] == a0][0]]
        m2 = sv["elig"] & np.isfinite(fwd)
        ic_v.append(float(pd.Series(sv["score"][m2]).corr(pd.Series(fwd[m2]), method="spearman")))
    per = pd.DataFrame(per)
    per["Low minus High"] = per["Low-risk Q1-Q3"] - per["High-risk Q4-Q5"]
    per["Rank IC beta"], per["Rank IC variance"] = ic_b, ic_v
    per.to_csv(os.path.join(OUT, f"{SLUG}_period_returns.csv"), index=False)
    pr("\nPER-QUARTER NET RETURNS (each book rebalanced to its group at every trade date) and Spearman rank IC of the risk score vs next-quarter return:")
    pr(per.round(4).to_string(index=False))
    icb, icv = np.array(ic_b), np.array(ic_v)
    res["rank_ic"] = {"beta_mean": float(icb.mean()), "beta_t": float(icb.mean() / (icb.std(ddof=1) / np.sqrt(len(icb)))),
                      "beta_share_negative": float((icb < 0).mean()),
                      "variance_mean": float(icv.mean()), "variance_t": float(icv.mean() / (icv.std(ddof=1) / np.sqrt(len(icv)))),
                      "n_periods": len(icb)}
    pr(f"Mean rank IC (negative = lower risk earns more): beta {icb.mean():+.3f} (t {res['rank_ic']['beta_t']:+.2f}, "
       f"{(icb < 0).sum()} of {len(icb)} quarters negative); variance {icv.mean():+.3f} (t {res['rank_ic']['variance_t']:+.2f})")
    gap = per["Low minus High"]
    res["quarters"] = {"n": len(per), "low_beats_high": int((gap > 0).sum()), "low_beats_nifty": int((per["Low-risk Q1-Q3"] > per["NIFTY 500"]).sum()),
                       "low_beats_ew": int((per["Low-risk Q1-Q3"] > per["Equal-weight universe"]).sum()),
                       "mean_gap": float(gap.mean()), "best_quarter_gap": float(gap.max()), "best_quarter": per.loc[gap.idxmax(), "to"]}
    cum = {c: float((1 + per[c]).prod() - 1) for c in ["Q1", "Q2", "Q3", "Q4", "Q5"]}
    res["quintile_cumulative"] = cum
    pr(f"Low beats high in {res['quarters']['low_beats_high']} of {len(per)} quarters; beats NIFTY 500 in {res['quarters']['low_beats_nifty']}; "
       f"beats the equal-weight universe in {res['quarters']['low_beats_ew']}; mean quarterly gap {gap.mean():+.2%}")
    # drop the best quarter
    per_ex = per.drop(gap.idxmax())
    res["drop_best_quarter_low_minus_high_mean"] = float((per_ex["Low-risk Q1-Q3"] - per_ex["High-risk Q4-Q5"]).mean())
    pr(f"Mean quarterly gap with the best quarter ({res['quarters']['best_quarter']}) removed: {res['drop_best_quarter_low_minus_high_mean']:+.2%}")
    # monotonic
    qc = np.array([cum[f"Q{g}"] for g in range(1, 6)])
    res["monotonic_spearman_q_vs_return"] = float(pd.Series(qc).corr(pd.Series(np.arange(1, 6)), method="spearman"))
    pr("Cumulative net return by group Q1..Q5: " + ", ".join(f"{x:.1%}" for x in qc) + f"; Spearman (group number vs return) {res['monotonic_spearman_q_vs_return']:+.2f}")

    # --- sector concentration ---
    ind = pd.read_csv(INDUSTRY).set_index("security_id")["screener_broad_sector"]
    lab = ind.reindex(cols).fillna("Unlabelled (no Screener page today)")
    tilt = []
    for i in sel_q:
        s = sel_q[i]
        held = np.isin(s["group"], [1, 2, 3])
        sh_h = pd.Series(1.0, index=cols[held]).groupby(lab[held]).sum() / held.sum()
        sh_u = pd.Series(1.0, index=cols[s["elig"]]).groupby(lab[s["elig"]]).sum() / s["elig"].sum()
        tilt.append(pd.concat([sh_h.rename("held"), sh_u.rename("universe")], axis=1).fillna(0.0).assign(date=cal[i]))
    tilt = pd.concat(tilt)
    tilt = tilt.groupby(level=0)[["held", "universe"]].mean()
    tilt["tilt"] = tilt["held"] - tilt["universe"]
    tilt = tilt.sort_values("tilt", ascending=False)
    tilt.to_csv(os.path.join(OUT, f"{SLUG}_sector_tilt.csv"))
    pr("\nSECTOR TILT of the low-risk book vs the eligible universe (share of names, average over formations; Screener broad sector, today's label):")
    pr(tilt.head(5).round(3).to_string())
    pr(tilt.tail(4).round(3).to_string())
    res["sector_tilt_top"] = tilt.head(5).reset_index().to_dict("records")
    res["sector_tilt_bottom"] = tilt.tail(4).reset_index().to_dict("records")

    # ---------------- Stage 06: research validation ----------------------------------------------
    pr("\n" + "=" * 100 + "\nSTAGE 06 -- RESEARCH VALIDATION (code computes; nothing below is estimated by hand)\n" + "=" * 100)
    rf = rf_series(ret_main.index, CASH_RATE)
    boot = bootstrap_sharpe_ci(ret_main, block_size=BLOCK, n_resamples=a.n_boot, rf_daily=rf, seed=0)
    pr(f"  MAIN Sharpe over 6% cash, 90% block-bootstrap CI (block {BLOCK}): [{boot.ci_low:.2f}, {boot.ci_high:.2f}] point {boot.point_estimate:.2f}, "
       f"{boot.fraction_positive:.0%} of resamples positive")
    res["bootstrap_main"] = {"ci_low": boot.ci_low, "ci_high": boot.ci_high, "point": boot.point_estimate, "frac_positive": boot.fraction_positive}
    pp = {}
    pp["NIFTY 500"] = paired(ret_main, nret, a.n_boot)
    pp[HI] = paired(ret_main, live[HI][1], a.n_boot)
    pp[EW] = paired(ret_main, live[EW][1], a.n_boot)
    pp["Q1 minus Q5"] = paired(live["Q1 (lowest beta)"][1], live["Q5 (highest beta)"][1], a.n_boot)
    pp["Variance-sorted low minus high"] = paired(live["Variance-sorted low-risk (Q1-Q3)"][1], live["Variance-sorted high-risk (Q4-Q5)"][1], a.n_boot)
    for k, b in pp.items():
        lab_ = f"MAIN minus {k}" if k in ("NIFTY 500", HI, EW) else k
        pr(f"  PAIRED {lab_}: Sharpe of the difference [{b['ci_low']:.2f}, {b['ci_high']:.2f}] point {b['point']:.2f}, P(<=0) {b['p_not_positive']:.3f}")
    res["paired"] = pp

    dsr = deflated_sharpe_from_returns(ret_main, n_trials=N_CONFIGS_TRIED, trial_sharpe_std=0.3, rf_daily=rf)
    pr(f"  Deflated Sharpe probability (n_trials={N_CONFIGS_TRIED}, the card's floor; excess of 6% cash): {dsr:.2f}")
    res["deflated_sharpe"] = float(dsr)

    windows = walk_forward_windows(v_main.index, n_folds=4, min_train_years=1.0)
    oos = oos_stability_summary(v_main, ret_main, windows, rf_daily=rf, min_obs=60)
    oos_n = oos_stability_summary(nv, nret, windows, rf_daily=rf, min_obs=60)
    oos_h = oos_stability_summary(*live[HI], windows, rf_daily=rf, min_obs=60)
    oos = oos.assign(nifty_sharpe=oos_n["sharpe"].to_numpy(), nifty_max_dd=oos_n["max_dd"].to_numpy(),
                     high_risk_sharpe=oos_h["sharpe"].to_numpy())
    pr("\n  WALK-FORWARD (anchored windows; Sharpe over 6% cash; the rule has no fitted parameter, so these are sub-periods):")
    pr(oos.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    oos.to_csv(os.path.join(OUT, f"{SLUG}_oos_stability.csv"), index=False)

    # sensitivities: each is a different book; sign vs high-risk and equal-weight universe
    def variant_row(label, lv_low, lv_high, lv_all, tds):
        ft = min(tds.values())
        vl, rl = live_slice(lv_low, ft, end)
        vh, rh = live_slice(lv_high, ft, end)
        va, ra = live_slice(lv_all, ft, end)
        s_ = stats(vl, rl, label)
        return {"variant": label, "cagr": s_["cagr"], "sharpe_excess": s_["sharpe_excess_daily"], "max_dd": s_["max_dd"],
                "cagr_high_risk": stats(vh, rh, "h")["cagr"], "cagr_equal_weight_universe": stats(va, ra, "a")["cagr"],
                "cagr_nifty500": stats(*live_slice(nifty_lvl, ft, end), "n")["cagr"],
                "low_minus_high_cagr": s_["cagr"] - stats(vh, rh, "h")["cagr"], "low_minus_ew_cagr": s_["cagr"] - stats(va, ra, "a")["cagr"]}
    sens = [variant_row("Base: beta, 252d, quarterly", lv_main, lv_hi, lv_ew, td_q),
            variant_row("Variance sort, 252d, quarterly", lv_var, lv_var_hi, lv_ew, td_v)]
    for lab_, kw in (("Beta, 126d window, quarterly", dict(window=126)), ("Beta, 252d, monthly", dict(freq="monthly")),
                     ("Beta, 252d, semi-annual", dict(freq="semiannual"))):
        r_, s_, c_, t_ = run_variant(**kw)
        sens.append(variant_row(lab_, book(s_, t_, [1, 2, 3])[0], book(s_, t_, [4, 5])[0], book(s_, t_, "all")[0], t_))
    for lab_, g in (("Held book Q2-Q3", [2, 3]), ("Held book Q1 only", [1]), ("Held book Q1-Q2", [1, 2])):
        sens.append(variant_row(lab_, book(sel_q, td_q, g)[0], lv_hi, lv_ew, td_q))
    sens = pd.DataFrame(sens)
    pr("\n  SENSITIVITY / VARIANTS (each counted in n_configs_tried = 16; positive 'low minus high' = the anomaly's sign):")
    pr(sens.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    sens.to_csv(os.path.join(OUT, f"{SLUG}_sensitivity.csv"), index=False)
    res["sensitivity"] = sens.to_dict("records")
    res["sign_agree_all"] = bool((sens["low_minus_high_cagr"] > 0).all())

    pr("\n  COST SWEEP (round trip, every traded rupee; main book and equal-weight universe):")
    cs = []
    for c in (0, 30, 60, 90, 150):
        lm = book(sel_q, td_q, [1, 2, 3], spread=c)[0]
        le = book(sel_q, td_q, "all", spread=c)[0]
        sm = stats(*live_slice(lm, first_trade, end), "m")
        se = stats(*live_slice(le, first_trade, end), "e")
        cs.append({"round_trip_bps": c, "cagr": sm["cagr"], "sharpe_excess": sm["sharpe_excess_daily"], "max_dd": sm["max_dd"],
                   "cagr_minus_nifty500": sm["cagr"] - stats(nv, nret, "n")["cagr"], "cagr_equal_weight_universe": se["cagr"]})
    cs = pd.DataFrame(cs)
    pr(cs.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    cs.to_csv(os.path.join(OUT, f"{SLUG}_cost_sweep.csv"), index=False)
    res["cost_sweep"] = cs.to_dict("records")

    pr("\n  CASH-RATE SWEEP (Sharpe numeraire only; the book holds no cash):")
    cr = pd.DataFrame([{"cash_rate": rt, "sharpe_excess": stats(v_main, ret_main, "m", rate=rt)["sharpe_excess_daily"],
                        "sharpe_excess_nifty500": stats(nv, nret, "n", rate=rt)["sharpe_excess_daily"]} for rt in (0.04, 0.05, 0.06, 0.07, 0.08)])
    pr(cr.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    cr.to_csv(os.path.join(OUT, f"{SLUG}_cash_sweep.csv"), index=False)
    res["cash_sweep"] = cr.to_dict("records")

    # placebo: same dates, same group size, names drawn at random from the eligible set
    pr(f"\n  PLACEBO: {a.n_placebo} random 60% selections of the same eligible names at the same dates (equal weight, same costs)")
    rng = np.random.default_rng(0)
    pl = []
    for _ in range(a.n_placebo):
        fake = {}
        for i, s in sel_q.items():
            g = np.zeros(len(s["group"]), dtype=int)
            ec = np.where(s["elig"])[0]
            pick = rng.permutation(ec)
            g[pick[:int(round(0.6 * len(ec)))]] = 1
            fake[i] = {"elig": s["elig"], "group": g}
        lvp = book(fake, td_q, [1])[0]
        vp, rp = live_slice(lvp, first_trade, end)
        sp = stats(vp, rp, "p")
        pl.append({"cagr": sp["cagr"], "sharpe_excess": sp["sharpe_excess_daily"]})
    pl = pd.DataFrame(pl)
    main_s = stats(v_main, ret_main, "m")
    pct = float((pl["cagr"] < main_s["cagr"]).mean())
    pr(f"  random 60% books: CAGR 5th/50th/95th pct {pl['cagr'].quantile(.05):.2%}/{pl['cagr'].median():.2%}/{pl['cagr'].quantile(.95):.2%}; "
       f"the beta-sorted book's {main_s['cagr']:.2%} beats {pct:.0%} of them")
    res["placebo"] = {"n": int(a.n_placebo), "p05": float(pl["cagr"].quantile(.05)), "p50": float(pl["cagr"].median()),
                      "p95": float(pl["cagr"].quantile(.95)), "main_cagr": main_s["cagr"], "share_beaten": pct}
    pl.to_csv(os.path.join(OUT, f"{SLUG}_placebo.csv"), index=False)

    # ---------------- Stage 07: portfolio validation ---------------------------------------------
    pr("\n" + "=" * 100 + "\nSTAGE 07 -- PORTFOLIO VALIDATION\n" + "=" * 100)
    fp = factor_fingerprint(ret_main, pd.DataFrame({"NIFTY 500": nret.reindex(ret_main.index).fillna(0.0)}), rf_daily=rf)
    if "error" in fp:
        pr(f"  factor fingerprint unavailable: {fp['error']}")
    else:
        pr("  FACTOR FINGERPRINT vs NIFTY 500 (the only permitted index series in this run):")
        pr(f"    alpha (ann.) {fp['alpha_ann']:.2%}   alpha t (HAC) {fp['alpha_t_hac']:.2f}   R^2 {fp['r_squared']:.2f}   n {fp['n_obs']}")
        pr(f"    loadings: {fp['loadings']}")
        res["factor_fingerprint"] = {k: fp[k] for k in ("alpha_ann", "alpha_t_hac", "r_squared", "n_obs", "loadings") if k in fp}
    fp2 = factor_fingerprint(ret_main, pd.DataFrame({"NIFTY 500": nret.reindex(ret_main.index).fillna(0.0),
                                                      "Equal-weight universe": live[EW][1].reindex(ret_main.index).fillna(0.0)}), rf_daily=rf)
    if "error" not in fp2:
        pr(f"  (appendix) vs NIFTY 500 + equal-weight universe: alpha {fp2['alpha_ann']:.2%}, t {fp2['alpha_t_hac']:.2f}, loadings {fp2['loadings']}")
        res["factor_fingerprint_with_ew"] = {k: fp2[k] for k in ("alpha_ann", "alpha_t_hac", "r_squared", "n_obs", "loadings") if k in fp2}
    res["corr_to_nifty500"] = float(np.corrcoef(ret_main, nret.reindex(ret_main.index).fillna(0.0))[0, 1])
    res["corr_to_equal_weight_universe"] = float(np.corrcoef(ret_main, live[EW][1].reindex(ret_main.index).fillna(0.0))[0, 1])
    pr(f"  correlation of daily returns with NIFTY 500: {res['corr_to_nifty500']:.2f}; with equal-weight universe {res['corr_to_equal_weight_universe']:.2f}")
    up = nret > 0
    res["up_capture"] = float(ret_main[up].mean() / nret[up].mean())
    res["down_capture"] = float(ret_main[~up].mean() / nret[~up].mean())
    pr(f"  up-day capture {res['up_capture']:.2f}, down-day capture {res['down_capture']:.2f} (vs NIFTY 500)")
    # realised beta of the book to NIFTY 500
    res["realised_beta_main"] = float(np.cov(ret_main, nret.reindex(ret_main.index).fillna(0.0))[0, 1] / nret.var())
    pr(f"  realised beta of the low-risk book to NIFTY 500: {res['realised_beta_main']:.2f}; high-risk book: "
       f"{float(np.cov(live[HI][1], nret.reindex(live[HI][1].index).fillna(0.0))[0, 1] / nret.var()):.2f}")

    # ---------------- charts, hand-off csvs ----------------------------------------------------
    os.makedirs(a.handoff, exist_ok=True)
    dr = pd.DataFrame({"strategy": ret_main, "benchmark": nret.reindex(ret_main.index).fillna(0.0), "sleeve": live[HI][1].reindex(ret_main.index)})
    dr.index.name = "date"
    dr.to_csv(os.path.join(a.handoff, "daily_returns.csv"))
    holdings.to_csv(os.path.join(a.handoff, "holdings.csv"), index=False)
    cmp_cols = {"High-risk book (Q4-Q5 by beta)": HI, "Equal-weight eligible universe": EW, "Inverse-vol eligible universe": "Inverse-vol eligible universe",
                "Q1 (lowest beta)": "Q1 (lowest beta)", "Q2": "Q2", "Q3": "Q3", "Q4": "Q4", "Q5 (highest beta)": "Q5 (highest beta)",
                "Q2-Q3 book": "Q2-Q3 book", "Variance-sorted low-risk (Q1-Q3)": "Variance-sorted low-risk (Q1-Q3)"}
    comp = pd.DataFrame({k: live[v][1] for k, v in cmp_cols.items()})
    comp.index.name = "date"
    comp.to_csv(os.path.join(a.handoff, "comparators.csv"))
    if not a.no_charts:
        try:
            from universal_backtester.clean_charts import save_clean_charts
            charts = save_clean_charts(
                v_main, nv, outdir=os.path.join(OUT, "charts"), tag=SLUG,
                strategy_name="Low-risk book (lowest 3 of 5 beta groups)", benchmark_name="NIFTY 500",
                weights=pd.DataFrame({"Invested": W_main.loc[v_main.index].sum(axis=1)}),
                sleeve=live[HI][0], sleeve_name="High-risk book (top 2 of 5 beta groups)",
                footnote="Price return (no dividends) for every series; 30bp round trip charged; universe = top 500 NSE stocks by traded value, a proxy for NIFTY 500.")
            res["charts"] = [os.path.relpath(c, REPO).replace("\\", "/") for c in charts]
            pr("  charts:", *res["charts"], sep="\n    ")
        except Exception as e:  # charts are a convenience; never fail the run on them
            pr(f"  charts skipped: {e!r}")

    # ---------------- Gate B inputs, judged by the repo's own gate_b() ---------------------------
    from ros.cards.schema import load_card
    from ros.governance.gates import gate_b
    research = {"deflated_sharpe": {"deflated_sharpe_prob": float(dsr),
                                    "interpretation": f"n_trials={N_CONFIGS_TRIED} (the card's floor), trial Sharpe std 0.3, excess of 6% cash"},
                "oos_min_sharpe": float(oos["sharpe"].min()) if not oos.empty else None,
                "bootstrap_p_not_positive": float(pp["NIFTY 500"]["p_not_positive"])}
    portfolio = {"alpha_t_hac": (float(fp["alpha_t_hac"]) if "error" not in fp else None),
                 "annual_turnover": ann_to,
                 "mandate": {"passes": True, "violations": []}}
    gb = gate_b(load_card(CARD), research, portfolio)
    pr("\n" + "=" * 100)
    pr("GATE B CRITERIA, as the repo's own gate_b() computes them from this run (decision stays PENDING)")
    pr("=" * 100)
    pr(gb.render())
    res["gate_b"] = gb.to_dict()
    res["gate_b_inputs"] = {"research": research, "portfolio": portfolio}
    res["oos_windows"] = oos.to_dict("records")
    res["window"] = {"first_trade": str(first_trade.date()), "end": str(end.date()), "n_daily_returns": len(ret_main), "years": yrs}
    json.dump(res, open(os.path.join(OUT, f"{SLUG}_results.json"), "w", encoding="utf-8"), indent=1, default=str)
    pr(f"\nResults written to {OUT} ({SLUG}_*). Gate B is a human decision and is NOT assigned by this script.")


if __name__ == "__main__":
    main()
