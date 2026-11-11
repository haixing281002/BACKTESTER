# Quant AI Researcher
"""Stocks on the Move (Andreas Clenow, 2015) on NIFTY 500 members: the book's own rules, translated to India.

Executes cards/oceanofpdf_com_stocks_on_the_move_andreas_clenow.yaml (Step 05) and computes the Step 06/07
validation numbers. Nothing here is estimated in prose: every figure in the hand-off files comes from this script.

PARAMETERS COME FROM THE CARD (changed 2026-10-30 after the Gate A -> Gate B audit). The window
(backtest_plan.sample_start / sample_end), the cost (costs.spread_bps), every signal parameter (signal.params,
including the signal weekday), the cash rate (the CASH_PROXY_CONSTANT_<n>PCT asset), the trial count
(n_configs_tried + this run's sensitivities) and the mandate (portfolio.mandate_allow_cash) are read from the card
at import time and recorded in manifest.json; Lightyear fails the run if they disagree with the approved card.
The numbers quoted below are the card's values at the time of writing, not literals the script uses.

WHAT THE MECHANISM IS (card: strategy.formation_rule, signal.params)
  * Signal at the card's signal weekday close (Tuesday; the previous trading day if it is a holiday); every trade
    fills at the next trading day's close, normally Wednesday. lag_days = 1.
  * Universe on a signal date: NIFTY 500 members at the latest quarterly snapshot on or before it (holdings
    workbook), keyed by ISIN, with 100 trading days of own adjusted-close history.
  * Score = (exp(slope of OLS on log adjusted close over the last 90 trading days) ** 250 - 1) * R-squared of
    the same fit. Rank every scored member BEFORE any filter; the hold band is the top 20% (rounded down).
  * Disqualified (for holding and for buying): adjusted close below its 100-day simple moving average, or any
    one-day close-to-close move above 15% (either way, adjusted closes) in the last 90 trading days.
  * Sells first: a holding outside the top 20%, disqualified, no longer a member, or delisted. Then every
    second signal date positions are reset to target when the difference exceeds 5%. Then, only if the NIFTY 500
    price index close is above its 200-day simple moving average, buy down the ranking (skipping held and
    disqualified names) at target value = NAV x 0.001 / (ATR20 / price) until the next buy would cost more
    than the cash available. Cash is a drift only and earns the card's flat rate, with an appendix sweep from config/fund.yaml.
  * Costs: the card's costs.spread_bps, and nothing else. The APPENDIX sweeps the costs in config/costs.yaml and reports
    the breakeven; every table priced differently from the headline is labelled "Appendix".
  * Whole shares are honoured on the UNADJUSTED close of the fill day; the position is then carried in adjusted
    units (value / adjusted close), so a split never reads as a trade. Share counts quoted to a human are
    unadjusted.

DATA (ros/data/sources.py: three files, nothing else; the run fetches nothing)
  ace.load_long(["close","high","low","unadj_close"])  Ace Equity adjusted OHLC + raw close, dates x ISIN
  nifty500.load_membership() / membership_panel()      quarterly NIFTY 500 snapshots, point in time
  load_banner_workbook(NSE_INDEX_WORKBOOK)             NIFTY 500 price index (gate + benchmark), factor sleeves
  Returns are PRICE returns: the Ace file carries no dividends. Both sides of every comparison are price return.
  The card's window ends 2026-09-18, the last NIFTY 500 close in the workbook (house limit 2026-09-29).

RUN
  python scripts/oceanofpdf_com_stocks_on_the_move_andreas_clenow_india_backtest.py [--run-dir outputs/lightyear/<id>]
  (--run-dir defaults to the run Lightyear names in $LIGHTYEAR_RUN; it is required otherwise)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ros import config
from ros.cards.schema import load_card
from ros.data import ace, corporate_actions, nifty500
from ros.data.lineage import sha256_file, write_run_manifest
from ros.data.loaders import synthetic_cash_series
from ros.data.sources import ACE_PRICES_CSV, NIFTY500_HOLDINGS_XLSX, NSE_INDEX_WORKBOOK
from ros.engine import missing_prices as mp
from ros.governance.gates import gate_b
from ros.metrics.core import ann_vol, cagr, max_drawdown, sharpe
from ros.validation import research, trials
from ros.validation.portfolio import benchmark_relative, factor_fingerprint
from universal_backtester.checkpoint import checkpoint
from universal_backtester.clean_charts import save_clean_charts
from universal_backtester.data import load_banner_workbook

SLUG = "oceanofpdf_com_stocks_on_the_move_andreas_clenow"
REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# $LIGHTYEAR_CARD points the script at a COPY of the card (mutation tests, what-if runs); the default is the repo card.
CARD = os.path.abspath(os.environ.get("LIGHTYEAR_CARD") or os.path.join(REPO_DIR, "cards", f"{SLUG}.yaml"))
CARD_OBJ = load_card(CARD)                       # THE source of truth: every parameter below is read from it, never retyped
_WEEKDAY = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4}
SENSITIVITIES = ("Thursday signal, Friday fill", "20% gap limit", "120-day regression", "no 200-day index filter")


def _params_from_card(card) -> tuple[dict, dict]:
    """Signal parameters, cost and cash rate from the approved card. Returns (P as the engine uses it, the card's
    signal.params as written) so manifest.json can carry both and Lightyear can compare them with the card."""
    sp = dict(card.signal.params)
    cash_rate, _cash_source = config.cash_rate_for(card)      # the card's universe.cash_asset; 0% when it names none
    wd = sp.get("signal_weekday", "Tuesday")
    p = {"regression_days": int(sp["regression_days"]), "annualise_power": int(sp["annualise_power"]),
         "stock_trend_days": int(sp["stock_trend_days"]), "gap_limit": float(sp["gap_limit"]), "gap_days": int(sp["gap_days"]),
         "atr_days": int(sp["atr_days"]), "risk_factor": float(sp["risk_factor"]),
         "hold_band_quantile": float(sp["hold_band_quantile"]), "index_filter_days": int(sp["index_filter_days"]),
         "resize_every_n_signals": int(sp["resize_every_n_signals"]), "resize_tolerance": float(sp["resize_tolerance"]),
         "min_history_days": int(sp["min_history_days"]),
         "signal_weekday": _WEEKDAY[str(wd).lower()] if isinstance(wd, str) else int(wd),
         "cash_rate": cash_rate, "cost_bp": float(card.costs.spread_bps), "use_index_filter": True}
    return p, sp


P, CARD_PARAMS = _params_from_card(CARD_OBJ)
START, END = pd.Timestamp(CARD_OBJ.backtest_plan.sample_start), pd.Timestamp(CARD_OBJ.backtest_plan.sample_end)
# Universe and start rule (card fields, added 2026-11-02): which membership file the run reads, and optionally a first
# signal one session BEFORE the window on a named NSE list, so the book is invested from the window's first day.
MEMBERSHIP_SOURCE = CARD_OBJ.universe.membership_source or "holdings_workbook"
FIRST_SIGNAL = pd.Timestamp(CARD_PARAMS["first_signal_date"]) if CARD_PARAMS.get("first_signal_date") else None
FIRST_SIGNAL_UNIVERSE = CARD_PARAMS.get("first_signal_universe") or None
LOAD_START = START - pd.DateOffset(years=1)       # 200 index closes and 100 stock closes of warm-up sit before START
MEMBERSHIP_FROM = START - pd.offsets.QuarterEnd(1)  # the last quarter-end snapshot before START is the first one used
START_CAPITAL = float(CARD_PARAMS.get("start_capital_inr", 100_000_000))   # Rs 10 crore on the card
# Every version actually tried on this paper (ros/validation/trials.py: the book's, Lightyear's, and studies outside
# Lightyear in data/reference/trial_ledger.csv), reported separately from this run's sensitivities.
N_SENSITIVITIES = len(SENSITIVITIES)
# TRIALS, N_VERSIONS and N_TRIALS are set in main(), once the run folder is known: the run being written is not counted.
MANDATE_ALLOWS_CASH = CARD_OBJ.portfolio.mandate_allow_cash is True
COST_LABEL = "zero cost" if P["cost_bp"] == 0 else f"{P['cost_bp']:g}bp round trip"
COST_SWEEP_BP = sorted({*config.cost_sweep_bp(), P["cost_bp"]})       # appendix only: the headline is at the card's cost
CASH_SWEEP = sorted({*config.cash_rate_sweep(), P["cash_rate"]})      # appendix only: the headline is at the card's rate
SENS_FROM_2015 = "2015-01-01"   # survivorship sensitivity window (Wave 2, item 4)
FFILL_LIMIT = 5    # signals carry a stale close at most 5 sessions; holdings follow ros/engine/missing_prices.py
BAND_PROXY = 0.095  # a close-to-close move above this on the fill day stands in for a price-band hit


# ------------------------------------------------------------------------------------------------- utilities
def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def rolling_ols(y: np.ndarray, n: int, block: int = 32) -> tuple[np.ndarray, np.ndarray]:
    """Rolling OLS of y on 0..n-1 over axis 0: slope per day and R-squared, NaN unless all n points are present."""
    T, N = y.shape
    x = np.arange(n, dtype=float)
    x -= x.mean()
    sxx = float((x ** 2).sum())
    slope = np.full((T, N), np.nan)
    r2 = np.full((T, N), np.nan)
    for c0 in range(0, N, block):
        blk = y[:, c0:c0 + block]
        win = sliding_window_view(blk, n, axis=0)               # (T-n+1, nb, n)
        valid = ~np.isnan(win).any(axis=2)
        w = np.where(np.isnan(win), 0.0, win)
        ym = w.mean(axis=2)
        yc = w - ym[..., None]
        sxy = (yc * x).sum(axis=2)
        syy = (yc ** 2).sum(axis=2)
        b = sxy / sxx
        with np.errstate(divide="ignore", invalid="ignore"):
            r = np.where(syy > 0, sxy ** 2 / (sxx * syy), np.nan)
        b[~valid] = np.nan
        r[~valid] = np.nan
        slope[n - 1:, c0:c0 + block] = b
        r2[n - 1:, c0:c0 + block] = r
    return slope, r2


def nav_metrics(nav: pd.Series, rf_daily: pd.Series, name: str) -> dict:
    r = nav.pct_change().dropna()
    return {"name": name, "cagr": cagr(nav), "vol": ann_vol(r), "sharpe": sharpe(r, rf_daily), "max_dd": max_drawdown(nav),
            "total_return": float(nav.iloc[-1] / nav.iloc[0] - 1), "start": str(nav.index[0].date()),
            "end": str(nav.index[-1].date()), "n_days": len(nav)}


class _Res:
    """The minimal shape ros.validation expects: value, returns, turnover, name."""

    def __init__(self, nav: pd.Series, turnover: pd.Series | None, name: str):
        self.value, self.name = nav, name
        self.returns = nav.pct_change().fillna(0.0)
        self.turnover = turnover if turnover is not None else pd.Series(0.0, index=nav.index)


# ------------------------------------------------------------------------------------------------- data
def load_data() -> dict:
    """Stage 04: point-in-time panels. Everything keyed by ISIN; dates are the Ace file's own calendar."""
    log(f"loading membership spells (membership_source = {MEMBERSHIP_SOURCE})")
    spells = nifty500.load_membership(source=MEMBERSHIP_SOURCE)
    ever = spells[(spells["start_date"] <= END) & (spells["end_date"].isna() | (spells["end_date"] > MEMBERSHIP_FROM))]
    isins = sorted(ever["isin"].unique())
    fsu = None
    if FIRST_SIGNAL_UNIVERSE:
        fsu = nifty500.first_signal_universe(FIRST_SIGNAL_UNIVERSE)
        isins = sorted(set(isins) | set(fsu["isin"]))
        log(f"first signal {FIRST_SIGNAL.date()} uses the {FIRST_SIGNAL_UNIVERSE} list: {len(fsu)} names, "
            f"{int(fsu['in_ace_master'].sum())} in the Ace master")
    sm = ace.security_master().set_index("isin")
    sm = sm[~sm.index.duplicated()]
    names = {i: (sm["nse_symbol"].get(i) or i, sm["company_name"].get(i) or "") for i in isins}

    log(f"loading Ace prices for {len(isins)} past-or-present members, {LOAD_START.date()} to {END.date()}")
    long = ace.load_long(["close", "high", "low", "unadj_close"], start=LOAD_START, end=END)
    long = long[long["isin"].isin(isins)]
    cal = pd.DatetimeIndex(ace.trading_calendar())
    cal = cal[(cal >= LOAD_START) & (cal <= END)]
    panels = {}
    for f in ("close", "high", "low", "unadj_close"):
        w = long.pivot(index="date", columns="isin", values=f).reindex(index=cal, columns=isins)
        panels[f] = w
    del long

    log("membership panel (point in time)")
    mdates = cal[cal >= min(MEMBERSHIP_FROM, FIRST_SIGNAL or MEMBERSHIP_FROM)]
    members = nifty500.membership_panel(mdates, columns=isins, m=spells).reindex(index=cal, columns=isins).fillna(False)
    members = members.astype(bool)
    if fsu is not None:
        assert FIRST_SIGNAL in members.index, f"first signal {FIRST_SIGNAL.date()} is not an NSE session"
        members.loc[FIRST_SIGNAL, :] = False
        members.loc[FIRST_SIGNAL, [i for i in fsu["isin"] if i in members.columns]] = True

    log("NIFTY 500 index and factor sleeves (NSE workbook)")
    bm, prov_bm = load_banner_workbook(NSE_INDEX_WORKBOOK, sheet="Broad Market")
    fi, _prov_fi = load_banner_workbook(NSE_INDEX_WORKBOOK, sheet="Factor Indices")
    n500 = bm["NIFTY 500 Close"].dropna()
    sma200 = n500.rolling(P["index_filter_days"], min_periods=P["index_filter_days"]).mean()
    idx_missing = int((~cal[cal >= START].isin(n500.index)).sum())
    index = pd.DataFrame({"close": n500, "sma200": sma200}).reindex(cal).ffill()
    sleeves = {c[:-6]: fi[c] for c in fi.columns if c.endswith("Close")}
    sleeves["NIFTY 500"] = n500
    sleeves = pd.DataFrame(sleeves).reindex(cal).ffill()

    snaps = nifty500.load_snapshots()
    snaps = snaps[snaps["mapped"]]
    seg = np.where(snaps["in_nifty100"], "large", np.where(snaps["in_midcap150"], "mid",
                   np.where(snaps["in_smallcap250"], "small", "unflagged")))
    segments = snaps.assign(segment=seg)[["snapshot_date", "isin", "segment"]]

    stale = nifty500.staleness(END)
    # demergers Ace does not adjust for: the adjusted panels above already carry them (ace.load_long); the ex-dates are
    # also exempt from the gap rule (operator's ruling 2026-11-11)
    dem = corporate_actions.load_table()
    dem = dem[dem["parent_isin"].isin(isins)]
    # the missing-price rule (ros/engine/missing_prices.py): only a sourced filing date makes a delisting confirmed
    dl = mp.load_delistings()
    dl = dl[dl["isin"].isin(isins)]
    return dict(cal=cal, isins=isins, names=names, members=members, index=index, sleeves=sleeves, segments=segments,
                stale=stale, idx_missing_days=idx_missing, prov_index=prov_bm["sha256"], demergers=dem, delistings=dl,
                **panels)


def build_signals(d: dict, regression_days: int, gap_limit: float) -> dict:
    """Everything the rule reads at a signal close, as date x ISIN arrays, from trailing data only."""
    close = d["close"].ffill(limit=FFILL_LIMIT)
    high = d["high"].ffill(limit=FFILL_LIMIT)
    low = d["low"].ffill(limit=FFILL_LIMIT)
    logc = np.log(close.to_numpy(dtype=float))
    slope, r2 = rolling_ols(logc, regression_days)
    ann_slope = np.exp(slope) ** P["annualise_power"] - 1.0
    score = ann_slope * r2
    sma = close.rolling(P["stock_trend_days"], min_periods=P["stock_trend_days"]).mean()
    ret = close.pct_change(fill_method=None)
    absret = ret.abs()
    for e in d.get("demergers", pd.DataFrame(columns=["parent_isin", "ex_date"])).itertuples():
        if e.parent_isin in absret.columns and e.ex_date in absret.index:
            absret.at[e.ex_date, e.parent_isin] = 0.0          # a demerger ex-date is not a gap
    biggest = absret.rolling(P["gap_days"], min_periods=1).max()
    gap = biggest > gap_limit
    prev = close.shift(1)
    # true range = max(high - low, |high - previous close|, |previous close - low|); NaN if any input is missing
    tr = np.maximum(np.maximum((high - low).to_numpy(), (high - prev).abs().to_numpy()), (prev - low).abs().to_numpy())
    atr = pd.DataFrame(tr, index=close.index, columns=close.columns).rolling(P["atr_days"], min_periods=P["atr_days"]).mean()
    atr_pct = atr / close
    return {"close": close, "score": pd.DataFrame(score, index=close.index, columns=close.columns),
                "ann_slope": pd.DataFrame(ann_slope, index=close.index, columns=close.columns),
                "r2": pd.DataFrame(r2, index=close.index, columns=close.columns), "sma": sma, "gap": gap, "biggest": biggest,
                "atr_pct": atr_pct, "ret": ret, "traded": d["close"].notna(), "unadj": d["unadj_close"].ffill(limit=FFILL_LIMIT),
                "state": mp.states(d["close"], d.get("delistings"))}


def signal_schedule(cal: pd.DatetimeIndex, weekday: int) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """(signal date, fill date) pairs: the given weekday's close (previous trading day if a holiday), filled at the
    next trading day's close. Both inside START..END."""
    out = []
    pos = {d: i for i, d in enumerate(cal)}
    weeks = sorted({(d.isocalendar()[0], d.isocalendar()[1]) for d in cal if START <= d <= END})
    for y, w in weeks:
        target = pd.Timestamp.fromisocalendar(y, w, weekday + 1)
        cands = cal[(cal <= target) & (cal > target - pd.Timedelta(days=6))]
        if len(cands) == 0:
            continue
        s = cands[-1]
        if s < START and s != FIRST_SIGNAL:
            continue
        i = pos[s]
        if i + 1 >= len(cal) or cal[i + 1] > END:
            continue
        out.append((s, cal[i + 1]))
    if FIRST_SIGNAL is not None and weekday == P["signal_weekday"]:
        # The start rule names the card's signal weekday. A weekday sensitivity (Thursday signal) keeps the same ISO week
        # and its own weekday, so its first signal falls inside the window and it starts in cash for those sessions.
        assert out and out[0][0] == FIRST_SIGNAL, f"the first signal must be {FIRST_SIGNAL.date()}, got {out[0][0].date() if out else None}"
        assert out[0][1] == cal[cal >= START][0], "the first fill must be the window's first session"
    return out


# ------------------------------------------------------------------------------------------------- the book
def simulate(d: dict, sig: dict, cfg: dict, write_logs: bool = False) -> dict:
    """Run the book's rules day by day. Returns the NAV, daily weights and the logs."""
    cal, isins, names = d["cal"], d["isins"], d["names"]
    N = len(isins)
    pos_of = {i: k for k, i in enumerate(cal)}
    close = sig["close"].to_numpy(dtype=float)
    traded = sig["traded"].to_numpy()
    state = sig["state"].to_numpy()
    unadj = sig["unadj"].to_numpy(dtype=float)
    score = sig["score"].to_numpy(dtype=float)
    sma = sig["sma"].to_numpy(dtype=float)
    gap = sig["gap"].to_numpy()
    atr_pct = sig["atr_pct"].to_numpy(dtype=float)
    members = d["members"].to_numpy()
    idx_close = d["index"]["close"].to_numpy(dtype=float)
    idx_sma = d["index"]["sma200"].to_numpy(dtype=float)
    ret_raw = sig["ret"].to_numpy(dtype=float)
    unadj_ret = d["unadj_close"].pct_change(fill_method=None).to_numpy(dtype=float)
    ann_slope = sig["ann_slope"].to_numpy(dtype=float)
    r2 = sig["r2"].to_numpy(dtype=float)
    biggest = sig["biggest"].to_numpy(dtype=float)

    sched = signal_schedule(cal, cfg["signal_weekday"])
    fills = {f: s for s, f in sched}
    day_rate = (1.0 + cfg["cash_rate"]) ** (1.0 / 252.0) - 1.0
    half_cost = cfg["cost_bp"] / 2.0 / 1e4

    start_i = pos_of[cal[cal >= START][0]]
    T = len(cal) - start_i
    nav = np.zeros(T)
    cash_w = np.zeros(T)
    weights = np.zeros((T, N))
    units = np.zeros(N)
    entry_date = {}
    entry_px = {}
    cash = START_CAPITAL
    last_px = np.full(N, np.nan)
    pnl_by_name = np.zeros(N)
    turnover_daily = pd.Series(0.0, index=cal[start_i:])
    trades, holdings, selection, rebal, worst_sells = [], [], [], [], []
    n_sig = 0
    n_band_buys = n_band_sells = 0
    pending_sells, pending_buys = {}, {}     # orders whose name had no price on the fill day: j -> (why or target, signal)
    NO_PRICE = (mp.HOLD, mp.SUSPENDED)

    for ti in range(start_i, len(cal)):
        t = cal[ti]
        k = ti - start_i
        px = close[ti]
        last_px = np.where(np.isfinite(px), px, last_px)
        held = units > 0
        cash *= (1.0 + day_rate)
        nav_before = cash + float(np.nansum(units[held] * last_px[held]))

        # ---- orders rolled from an earlier fill day: they fill on the first day the name trades again
        for j in list(pending_sells):
            if units[j] <= 0:
                pending_sells.pop(j)
            elif state[ti][j] in (mp.TRADED, mp.DELISTED):
                why, s0 = pending_sells.pop(j)
                p = px[j] if state[ti][j] == mp.TRADED and np.isfinite(px[j]) else last_px[j]
                val = units[j] * p
                cash += val * (1 - half_cost)
                worst_sells.append({"isin": isins[j], "symbol": names[isins[j]][0], "reason": "rolled",
                                    "entry_date": entry_date.get(j), "exit_date": t,
                                    "return": p / entry_px[j] - 1 if j in entry_px else np.nan})
                if write_logs:
                    trades.append({"date": t, "symbol": names[isins[j]][0], "action": "SELL", "weight_before": val / nav_before,
                                   "weight_after": 0.0, "isin": isins[j], "signal_date": s0, "execution_date": t, "price_date": t,
                                   "price": unadj[ti][j], "price_basis": "Ace unadjusted close", "value_rs": val, "adjusted_close": p,
                                   "shares": round(val / unadj[ti][j]) if np.isfinite(unadj[ti][j]) and unadj[ti][j] > 0 else np.nan,
                                   "why": f"Sold: {why} (rolled: no price on the fill day)"})
                units[j] = 0.0
                entry_date.pop(j, None)
                entry_px.pop(j, None)
        for j in list(pending_buys):
            if state[ti][j] != mp.TRADED or not np.isfinite(px[j]) or not (np.isfinite(unadj[ti][j]) and unadj[ti][j] > 0):
                continue
            target, s0, rk = pending_buys.pop(j)
            sh = math.floor(target / unadj[ti][j])
            val = sh * unadj[ti][j]
            if sh <= 0 or not members[ti][j] or val * (1 + half_cost) > cash or units[j] > 0:
                continue
            cash -= val * (1 + half_cost)
            units[j] = val / px[j]
            entry_date[j], entry_px[j] = t, px[j]
            if write_logs:
                trades.append({"date": t, "symbol": names[isins[j]][0], "action": "BUY", "weight_before": 0.0,
                               "weight_after": val / nav_before, "isin": isins[j], "signal_date": s0, "execution_date": t,
                               "price_date": t, "price": unadj[ti][j], "price_basis": "Ace unadjusted close", "shares": sh,
                               "value_rs": val, "adjusted_close": px[j],
                               "why": f"Rank {rk} at the signal; rolled: no price on the fill day, bought the next day it traded"})
        held = units > 0
        nav_before = cash + float(np.nansum(units[held] * last_px[held]))

        if t in fills:
            pending_buys.clear()                 # a new signal's decisions replace buy orders still waiting
            s = fills[t]
            si = pos_of[s]
            n_sig += 1
            nav_s = nav[k - 1] if k > 0 else START_CAPITAL
            # ---- ranking at the signal close, BEFORE any filter
            scoreable = members[si] & np.isfinite(score[si]) & np.isfinite(sma[si]) & traded[si]
            cand = np.where(scoreable)[0]
            order = cand[np.lexsort((cand, -score[si][cand]))]   # highest score first; ties broken by ISIN (isins are sorted)
            rank = np.full(N, np.nan)
            rank[order] = np.arange(1, len(order) + 1)
            n_ranked = len(order)
            top_n = math.floor(P["hold_band_quantile"] * n_ranked)
            below_sma = np.isfinite(sma[si]) & (close[si] < sma[si])
            disq = below_sma | gap[si]
            gate_open = bool(idx_close[si] > idx_sma[si]) if cfg["use_index_filter"] else True
            traded_value = 0.0
            held_before = set(np.where(units > 0)[0])
            w_before = {j: units[j] * last_px[j] / nav_before for j in held_before}

            # ---- step 1: sells
            sells = []
            for j in sorted(held_before):
                why = None
                if state[si][j] == mp.DELISTED:
                    why = "delisted (sourced filing): exit at the last available close"
                elif state[si][j] in NO_PRICE:
                    if not members[si][j]:          # it must go, but has no price: the sale waits for a day it trades
                        pending_sells[j] = ("left the NIFTY 500 list at the latest quarterly snapshot", s)
                    continue                        # no price: held at its last close, not scored, not sold for it
                elif not members[si][j]:
                    why = "left the NIFTY 500 list at the latest quarterly snapshot"
                elif not np.isfinite(rank[j]):
                    why = "could not be scored at the signal date"
                elif rank[j] > top_n:
                    why = f"rank {int(rank[j])} is outside the top 20% (top {top_n} of {n_ranked})"
                elif below_sma[j]:
                    why = f"close {close[si][j]:.2f} is below its 100-day average {sma[si][j]:.2f}"
                elif gap[si][j]:
                    why = f"a one-day move of {biggest[si][j]:.1%} in the last 90 days exceeds the 15% limit"
                if why:
                    sells.append((j, why))
            rolled = [(j, why) for j, why in sells if state[ti][j] in NO_PRICE]
            for j, why in rolled:
                pending_sells[j] = (why, s)        # no price on the fill day: the order rolls to the next day it trades
            sells = [(j, why) for j, why in sells if state[ti][j] not in NO_PRICE]
            for j, why in sells:
                p = px[j] if np.isfinite(px[j]) and state[ti][j] == mp.TRADED else last_px[j]
                val = units[j] * p
                cash += val * (1 - half_cost)
                traded_value += val
                sh = round(val / unadj[ti][j]) if np.isfinite(unadj[ti][j]) and unadj[ti][j] > 0 else np.nan
                reason_tag = ("membership" if "left the NIFTY 500" in why else "delisted" if "delisted" in why
                              else "rank" if "rank" in why else "sma" if "100-day" in why else "gap")
                ret_since_entry = p / entry_px[j] - 1 if j in entry_px else np.nan
                worst_sells.append({"isin": isins[j], "symbol": names[isins[j]][0], "reason": reason_tag,
                                    "entry_date": entry_date.get(j), "exit_date": t, "return": ret_since_entry})
                if np.isfinite(unadj_ret[ti][j]) and unadj_ret[ti][j] < -BAND_PROXY:
                    n_band_sells += 1
                if write_logs:
                    trades.append({"date": t, "symbol": names[isins[j]][0], "action": "SELL", "weight_before": w_before[j],
                                       "weight_after": 0.0, "isin": isins[j], "signal_date": s, "execution_date": t, "price_date": t,
                                       "price": unadj[ti][j], "price_basis": "Ace unadjusted close", "shares": sh, "value_rs": val,
                                       "adjusted_close": p, "why": "Sold: " + why})
                units[j] = 0.0
                entry_date.pop(j, None)
                entry_px.pop(j, None)

            # ---- step 2: resize every second signal
            n_resized = 0
            if n_sig % P["resize_every_n_signals"] == 0:
                for j in np.where(units > 0)[0]:
                    if not (np.isfinite(atr_pct[si][j]) and atr_pct[si][j] > 0 and traded[ti][j] and np.isfinite(px[j])):
                        continue
                    target = nav_s * P["risk_factor"] / atr_pct[si][j]
                    cur = units[j] * px[j]
                    if cur <= 0 or abs(target - cur) / cur <= P["resize_tolerance"]:
                        continue
                    diff = target - cur
                    if diff > 0:
                        diff = min(diff, max(cash, 0.0) / (1 + half_cost))
                        if diff <= 0:
                            continue
                    sh = round(abs(diff) / unadj[ti][j]) if np.isfinite(unadj[ti][j]) and unadj[ti][j] > 0 else 0
                    if sh == 0:
                        continue
                    diff = math.copysign(sh * unadj[ti][j], diff)
                    cash -= diff + abs(diff) * half_cost
                    traded_value += abs(diff)
                    wb = units[j] * px[j] / nav_before
                    units[j] += diff / px[j]
                    n_resized += 1
                    if write_logs:
                        trades.append({"date": t, "symbol": names[isins[j]][0], "action": "ADD" if diff > 0 else "TRIM",
                                           "weight_before": wb, "weight_after": units[j] * px[j] / nav_before, "isin": isins[j],
                                           "signal_date": s, "execution_date": t, "price_date": t, "price": unadj[ti][j],
                                           "price_basis": "Ace unadjusted close", "shares": sh if diff > 0 else -sh,
                                           "value_rs": abs(diff), "adjusted_close": px[j],
                                           "why": f"Resize to target NAV x 0.001 / ATR%: target Rs {target:,.0f}, was Rs {cur:,.0f} "
                                               f"({(cur / target - 1):+.1%}, beyond the 5% band)"})

            # ---- step 3: buys from the top of the ranking while the gate is open
            buys, skipped, not_needed = [], [], []
            pick_no = {j: None for j in range(N)}
            rank_of_last_pick = None
            stopped = False
            for j in order[:top_n]:
                if units[j] > 0:
                    continue
                if disq[j]:
                    skipped.append((j, "below 100-day average" if below_sma[j] else f"{biggest[si][j]:.1%} one-day move in 90 days"))
                    continue
                if not gate_open:
                    skipped.append((j, "no new buys: NIFTY 500 is below its 200-day average"))
                    continue
                if not (np.isfinite(atr_pct[si][j]) and atr_pct[si][j] > 0):
                    skipped.append((j, "no 20-day ATR"))
                    continue
                if not (traded[ti][j] and np.isfinite(px[j]) and np.isfinite(unadj[ti][j]) and unadj[ti][j] > 0):
                    if not stopped:
                        pending_buys[j] = (nav_s * P["risk_factor"] / atr_pct[si][j], s, int(rank[j]))
                    skipped.append((j, "no price on the fill day: the order rolls to the next day it trades"))
                    continue
                if stopped:
                    not_needed.append(j)
                    continue
                target = nav_s * P["risk_factor"] / atr_pct[si][j]
                sh = math.floor(target / unadj[ti][j])
                val = sh * unadj[ti][j]
                if sh <= 0:
                    skipped.append((j, "target below one share"))
                    continue
                if val * (1 + half_cost) > cash:
                    stopped = True
                    not_needed.append(j)
                    continue
                cash -= val * (1 + half_cost)
                traded_value += val
                units[j] = val / px[j]
                entry_date[j], entry_px[j] = t, px[j]
                buys.append(j)
                rank_of_last_pick = int(rank[j])
                if np.isfinite(unadj_ret[ti][j]) and unadj_ret[ti][j] > BAND_PROXY:
                    n_band_buys += 1
                if write_logs:
                    trades.append({"date": t, "symbol": names[isins[j]][0], "action": "BUY", "weight_before": 0.0,
                                       "weight_after": val / nav_before, "isin": isins[j], "signal_date": s, "execution_date": t,
                                       "price_date": t, "price": unadj[ti][j], "price_basis": "Ace unadjusted close", "shares": sh,
                                       "value_rs": val, "adjusted_close": px[j],
                                       "why": f"Rank {int(rank[j])} of {n_ranked} (score {score[si][j]:.3f}); above its 100-day average, "
                                           f"no 15% move in 90 days; sized at NAV x 0.001 / ATR% ({atr_pct[si][j]:.2%}) = {val / nav_s:.1%}"})
            turnover_daily.iloc[k] = traded_value / nav_before if nav_before > 0 else 0.0

            # ---- logs for the base run
            held_now = np.where(units > 0)[0]
            nav_after = cash + float(np.nansum(units[held_now] * last_px[held_now]))
            if write_logs:
                for pn, j in enumerate(sorted(held_now, key=lambda j: (rank[j] if np.isfinite(rank[j]) else 1e9)), start=1):
                    pick_no[j] = pn
                    wgt = units[j] * last_px[j] / nav_after
                    holdings.append({"date": s, "symbol": names[isins[j]][0], "leg": "long", "weight": wgt, "isin": isins[j],
                                         "execution_date": t, "shares": round(units[j] * last_px[j] / unadj[ti][j]) if np.isfinite(unadj[ti][j]) else np.nan,
                                         "price": unadj[ti][j], "rank": rank[j], "signal_score": score[si][j], "r_squared": r2[si][j],
                                         "atr_pct": atr_pct[si][j], "entry_date": entry_date.get(j), "company": names[isins[j]][1]})
                sold_set = {j for j, _ in sells}
                rows = set(order[:top_n].tolist()) | held_before | set(held_now.tolist())
                for j in rows:
                    if j in sold_set:
                        dec, why = "SOLD", next(w for jj, w in sells if jj == j)
                    elif j in buys:
                        dec, why = "BOUGHT", f"rank {int(rank[j])}, passes both filters, bought at NAV x 0.001 / ATR%"
                    elif units[j] > 0 and state[si][j] in NO_PRICE:
                        dec, why = "HELD, NO PRICE", ("must be sold, but has no price: the sale waits for the next day it trades"
                                                      if j in pending_sells else
                                                      "no price at the signal: kept at its last close, not ranked")
                    elif units[j] > 0:
                        dec, why = "KEPT", f"rank {int(rank[j])} stays inside the top {top_n}; passes both filters"
                    elif j in not_needed:
                        dec, why = "NOT NEEDED", "eligible, but the cash was spent before the ranking reached it"
                    else:
                        why = next((w for jj, w in skipped if jj == j), "in the top band but not bought")
                        dec = "SKIPPED"
                    selection.append({"signal_date": s, "execution_date": t, "symbol": names[isins[j]][0], "isin": isins[j], "decision": dec,
                                          "why": why, "rank": rank[j], "pick_no": pick_no.get(j), "score": score[si][j],
                                          "annualised_slope": ann_slope[si][j], "r_squared": r2[si][j],
                                          "pct_vs_100d_avg": (close[si][j] / sma[si][j] - 1) if np.isfinite(sma[si][j]) else np.nan,
                                          "biggest_move_90d": biggest[si][j], "close_raw": unadj[si][j], "atr_pct": atr_pct[si][j],
                                          "weight_after": (units[j] * last_px[j] / nav_after) if units[j] > 0 else 0.0,
                                          "in_nifty500_list": bool(members[si][j]), "gate_open": gate_open,
                                          "rank_of_last_pick": rank_of_last_pick, "n_ranked": n_ranked, "top_n": top_n})
            wts_now = units[held_now] * last_px[held_now] / nav_after if nav_after > 0 else np.array([])
            top_band = order[:top_n]
            rebal.append({"signal_date": s, "fill_date": t, "n_members": int(members[si].sum()), "n_ranked": n_ranked, "top_n": top_n,
                              "n_top_disq_gap": int(gap[si][top_band].sum()), "n_top_disq_sma": int(below_sma[top_band].sum()),
                              "n_top_eligible": int((~disq[top_band]).sum()), "gate_open": gate_open,
                              "index_close": idx_close[si], "index_sma200": idx_sma[si], "n_sold": len(sells),
                              "n_sold_membership": sum(1 for _, w in sells if "left the NIFTY 500" in w),
                              "n_sold_delisted": sum(1 for _, w in sells if "delisted" in w),
                              "n_orders_rolled": len(rolled) + len(pending_buys),
                              "n_resized": n_resized, "n_bought": len(buys), "n_held": len(held_now),
                              "cash_share": cash / nav_after if nav_after > 0 else 1.0,
                              "max_weight": float(wts_now.max()) if len(wts_now) else 0.0,
                              "max_weight_symbol": names[isins[held_now[int(np.argmax(wts_now))]]][0] if len(wts_now) else "",
                              "top5_weight": float(np.sort(wts_now)[-5:].sum()) if len(wts_now) else 0.0,
                              "rank_of_last_pick": rank_of_last_pick, "traded_value_frac": traded_value / nav_before})
            held = units > 0

        nav[k] = cash + float(np.nansum(units[held] * last_px[held]))
        cash_w[k] = cash / nav[k]
        weights[k] = np.where(held, units * np.where(np.isfinite(last_px), last_px, 0.0) / nav[k], 0.0)
        if k > 0:
            dpx = np.where(np.isfinite(ret_raw[ti]), ret_raw[ti], 0.0)
            prev_vals = weights[k - 1] * nav[k - 1]
            pnl_by_name += prev_vals * dpx

    idx = cal[start_i:]
    return {"nav": pd.Series(nav, index=idx, name="nav"), "cash_weight": pd.Series(cash_w, index=idx),
                "weights": pd.DataFrame(weights, index=idx, columns=isins), "turnover": turnover_daily,
                "trades": pd.DataFrame(trades), "holdings": pd.DataFrame(holdings), "selection": pd.DataFrame(selection),
                "rebalances": pd.DataFrame(rebal), "sells": pd.DataFrame(worst_sells), "pnl_by_name": pd.Series(pnl_by_name, index=isins),
                "n_band_buys": n_band_buys, "n_band_sells": n_band_sells, "schedule": sched,
                "missing_price_events": mp.flagged_events(sig["state"].loc[idx],
                                                          pd.DataFrame(weights, index=idx, columns=isins) > 0)}


# ------------------------------------------------------------------------------------------------- comparators
def basket(d: dict, sig: dict, scheme: str) -> pd.Series:
    """Monthly rebalanced basket of every priced NIFTY 500 member: equal weight or inverse 20-day volatility.
    Signal at the last trading day of the month, fills the next day; a name that stops trading is held flat."""
    cal = d["cal"]
    window = cal[cal >= START]
    close = sig["close"]
    ret = sig["ret"].reindex(window).fillna(0.0).to_numpy(dtype=float)
    vol20 = sig["ret"].rolling(20, min_periods=15).std()
    members = d["members"]
    traded = sig["traded"]
    # signal on the last trading day of each month, fill on the next trading day; the first basket is formed on the
    # first day of the window from the previous close (2013-12-31 snapshot)
    month_last = pd.Series(window, index=window).groupby(window.to_period("M")).last().tolist()
    pos = {dte: i for i, dte in enumerate(window)}
    nav = np.ones(len(window))
    fills = [window[0]] + [cal[cal.get_loc(s) + 1] for s in month_last
                           if cal.get_loc(s) + 1 < len(cal) and cal[cal.get_loc(s) + 1] <= END]
    fills = sorted({f for f in fills if f in pos})
    level = 1.0
    for a, b in zip(fills, fills[1:] + [None]):
        s = cal[cal.get_loc(a) - 1]
        elig = (members.loc[s] & traded.loc[s] & close.loc[s].notna()).to_numpy()
        if scheme == "inverse_vol":
            v = vol20.loc[s].to_numpy(dtype=float)
            w = np.where(elig & np.isfinite(v) & (v > 0), 1.0 / np.where(v > 0, v, 1.0), 0.0)
        else:
            w = elig.astype(float)
        w = w / w.sum()
        i0 = pos[a]
        i1 = pos[b] if b is not None else len(window)
        seg = ret[i0 + 1:i1 + 1] if b is not None else ret[i0 + 1:]
        cum = np.cumprod(1.0 + seg, axis=0)
        vals = (cum * w).sum(axis=1) * level
        nav[i0] = level
        if len(vals):
            nav[i0 + 1:i0 + 1 + len(vals)] = vals
            level = vals[-1]
    return pd.Series(nav, index=window, name=scheme)


# ------------------------------------------------------------------------------------------------- checks
def lookahead_checks(d: dict, sig: dict, sched, rng) -> list[dict]:
    """(a) recompute the ranking on random signal dates with every later price deleted: must be identical;
    (b) planted one-day leak: the same test on a score built from TOMORROW's close must catch it;
    (c) scramble test (ros/validation/lookahead.py): every price after a mid-sample signal date perturbed, the whole
    book re-run: weights and NAV up to that date must be bit-identical; (d) hand-check slope/R2."""
    from scipy import stats

    from ros.validation import lookahead as la
    out = []
    picks = rng.choice(len(sched), size=5, replace=False)
    panels = ("close", "high", "low", "unadj_close")

    def truncated(dd, s):
        t = {k: v.loc[:s] for k, v in dd.items() if k in panels}
        t.update({"isins": dd["isins"], "cal": dd["cal"][dd["cal"] <= s]})
        return t

    def leaky_score(dd):          # the planted leak lives INSIDE the signal: every price read one day early
        return build_signals({**dd, **{k: dd[k].shift(-1) for k in panels}}, P["regression_days"], P["gap_limit"])["score"]

    leaky_full = leaky_score(d)
    same, caught = 0, 0
    for p in picks:
        s, _ = sched[p]
        full = sig["score"].loc[s].to_numpy(dtype=float)
        part = build_signals(truncated(d, s), P["regression_days"], P["gap_limit"])["score"].loc[s].to_numpy(dtype=float)
        same += int(np.allclose(full, part, equal_nan=True))
        lfull = leaky_full.loc[s].to_numpy(dtype=float)
        lpart = leaky_score(truncated(d, s)).loc[s].to_numpy(dtype=float)
        caught += int(not np.allclose(lfull, lpart, equal_nan=True))
    out.append({"check": "look-ahead tripwire: ranking recomputed with every later price deleted is identical",
                "passed": same == 5, "detail": f"{same}/5 random signal dates identical"})
    out.append({"check": "planted leak control: the same tripwire catches a score built from tomorrow's close",
                "passed": caught == 5, "detail": f"caught on {caught}/5 dates (a tripwire that cannot see a leak is no tripwire)"})
    # (c) scramble: one noise matrix for all four panels, so each day's high/low/close stay consistent
    cut = sched[len(sched) // 2][0]
    noise = la.scramble_after(pd.DataFrame(1.0, index=d["cal"], columns=d["isins"]), cut, rng)
    sd = {**d, **{k: d[k] * noise for k in panels}}
    base = simulate(d, sig, P)
    scr = simulate(sd, build_signals(sd, P["regression_days"], P["gap_limit"]), P)
    w_ok = base["weights"].loc[:cut].equals(scr["weights"].loc[:cut])
    n_ok = base["nav"].loc[:cut].equals(scr["nav"].loc[:cut])
    moved = not base["nav"].equals(scr["nav"])
    out.append({"check": "scramble test: every price after a mid-sample signal date perturbed; weights and NAV up to it unchanged",
                "passed": bool(w_ok and n_ok and moved),
                "detail": f"up to {cut.date()}: weights {'identical' if w_ok else 'CHANGED'}, NAV {'identical' if n_ok else 'CHANGED'}; "
                          f"after it the NAV {'moved' if moved else 'did not move'}"})
    # hand check of slope and R2 against scipy on two names at two dates
    ok = 0
    tested = 0
    for p in picks[:2]:
        s, _ = sched[p]
        row = sig["score"].loc[s].dropna().sort_values(ascending=False)
        for isin in row.index[:2]:
            y = np.log(sig["close"][isin].loc[:s].tail(P["regression_days"]).to_numpy(dtype=float))
            lr = stats.linregress(np.arange(len(y)), y)
            exp_score = (math.exp(lr.slope) ** P["annualise_power"] - 1) * lr.rvalue ** 2
            tested += 1
            ok += int(abs(exp_score - row[isin]) < 1e-9)
    out.append({"check": "hand check: top scores match scipy.stats.linregress slope and R-squared",
                "passed": ok == tested, "detail": f"{ok}/{tested} match to 1e-9"})
    return out


# ------------------------------------------------------------------------------------------------- main
# ------------------------------------------------------------------------------------------------- fixed output template
# The Validation rows and the table sheets are the SAME in every run of this card (added 2026-10-30): the model may append
# rows and tables in results.json, never rename or drop these. tests/test_frozen_outputs.py fails on any change here.
FIXED_TABLES = [
    {"title": "Performance", "csv": "performance.csv", "note": "Headline statistics over the card's window, price returns, Sharpe over the card's cash rate."},
    {"title": "Appendix cost sweep", "csv": "cost_sweep.csv", "note": "APPENDIX: the same run at each cost in config/costs.yaml; the headline is at the card's cost."},
    {"title": "Cash-rate sweep", "csv": "cash_rate_sweep.csv", "note": "APPENDIX: idle cash at each rate in config/fund.yaml and at the card's own."},
    {"title": "Sensitivities", "csv": "sensitivities.csv", "note": "Thursday signal, 20% gap limit, 120-day regression, no index filter."},
    {"title": "Calendar-year returns", "csv": "calendar_year_returns.csv", "note": "First and last years are part years."},
    {"title": "Sub-period stability", "csv": "sub_period_stability.csv", "note": "Four consecutive windows after a 3-year start, judged on excess over NIFTY 500. The rules fit no parameters, so this is not out-of-sample evidence."},
    {"title": "Sub-period CAGR", "csv": "subperiod_cagr.csv", "note": "Four equal blocks of the sample."},
    {"title": "Rebalance log", "csv": "rebalance_log.csv", "note": "Per signal: names ranked, top band, filter removals, gate state, buys, sells, cash share, largest weight."},
    {"title": "Exits by reason", "csv": "exits_by_reason.csv", "note": "Why positions were sold and what they returned while held."},
    {"title": "Worst days", "csv": "worst_days.csv", "note": "Five worst strategy days with the index's return and the names that fell most."},
    {"title": "Contributors", "csv": "contributors.csv", "note": "Profit and loss by name over the whole run, in rupees."},
    {"title": "Cap mix by year", "csv": "cap_mix_by_year.csv", "note": "Average NAV share in NIFTY 100, Midcap 150 and Smallcap 250 names per rebalance; the rest is cash."},
    {"title": "Gap events", "csv": "gap_events.csv", "note": "Every member-day with a one-day move over the gap limit and whether Ace's adjustment factor changed that day."},
    {"title": "Checks", "csv": "checks.csv", "note": "Look-ahead tripwires and accounting identities; every row must pass."},
    {"title": "Universe coverage", "csv": "universe_coverage.csv", "note": "Per year: members on the run's own panel, how many had an Ace close, and the names that never did (in the universe, never tradable)."},
]


def _perf(raw, prefix):
    for r in raw["performance"]:
        if r["name"].startswith(prefix):
            return r
    return {}


def _sens(raw, prefix):
    for r in raw["sensitivities"]:
        if r["variant"].startswith(prefix):
            return r
    return {}


def _sweep(raw, bp):
    for r in raw["cost_sweep"]:
        if r["round_trip_cost_bp"] == bp:
            return r
    return {}


def _cash(raw, rate):
    for r in raw["cash_rate_sweep"]:
        if abs(r["cash_rate"] - rate) < 1e-12:
            return r
    return {}


# (label, group, format, function(raw) -> value, source). Append new rows at the END only.
FIXED_VALIDATION_SPEC = [
    {"label": "CAGR, strategy", "group": "returns_risk", "format": "pct", "fn": lambda r: _perf(r, "Stocks on the Move")["cagr"], "source": "out/performance.csv"},
    {"label": "CAGR, NIFTY 500 price index", "group": "returns_risk", "format": "pct", "fn": lambda r: _perf(r, "NIFTY 500 (price")["cagr"], "source": "out/performance.csv"},
    {"label": "CAGR, equal-weight members (monthly)", "group": "returns_risk", "format": "pct", "fn": lambda r: _perf(r, "Equal-weight")["cagr"], "source": "out/performance.csv"},
    {"label": "CAGR, NIFTY500 Momentum 50 (backfilled)", "group": "returns_risk", "format": "pct", "fn": lambda r: _perf(r, "NIFTY500 Momentum 50")["cagr"], "source": "out/performance.csv"},
    {"label": "CAGR, same rules without the index filter", "group": "returns_risk", "format": "pct", "fn": lambda r: _perf(r, "Same rules, no 200-day")["cagr"], "source": "out/performance.csv"},
    {"label": "Volatility, strategy", "group": "returns_risk", "format": "pct", "fn": lambda r: _perf(r, "Stocks on the Move")["vol"], "source": "out/performance.csv"},
    {"label": "Volatility, NIFTY 500", "group": "returns_risk", "format": "pct", "fn": lambda r: _perf(r, "NIFTY 500 (price")["vol"], "source": "out/performance.csv"},
    {"label": "Sharpe, strategy", "group": "returns_risk", "format": "num", "fn": lambda r: _perf(r, "Stocks on the Move")["sharpe"], "source": "ros.metrics.core.sharpe()"},
    {"label": "Sharpe, NIFTY 500", "group": "returns_risk", "format": "num", "fn": lambda r: _perf(r, "NIFTY 500 (price")["sharpe"], "source": "ros.metrics.core.sharpe()"},
    {"label": "Max drawdown, strategy", "group": "returns_risk", "format": "pct", "fn": lambda r: _perf(r, "Stocks on the Move")["max_dd"], "source": "out/performance.csv"},
    {"label": "Max drawdown, NIFTY 500", "group": "returns_risk", "format": "pct", "fn": lambda r: _perf(r, "NIFTY 500 (price")["max_dd"], "source": "out/performance.csv"},
    {"label": "Drawdown in the latest index correction, strategy", "group": "returns_risk", "format": "pct", "fn": lambda r: r["latest_index_correction"]["strategy_dd"],
     "source": lambda r: f"daily_returns.csv, {r['latest_index_correction']['peak']} to {r['latest_index_correction']['trough']}"},
    {"label": "Drawdown in the latest index correction, NIFTY 500", "group": "returns_risk", "format": "pct", "fn": lambda r: r["latest_index_correction"]["nifty500_dd"],
     "source": lambda r: f"daily_returns.csv, {r['latest_index_correction']['peak']} to {r['latest_index_correction']['trough']}"},
    {"label": "Beta to NIFTY 500", "group": "returns_risk", "format": "num", "fn": lambda r: r["benchmark_relative"]["beta"], "source": "benchmark_relative()"},
    {"label": "Information ratio vs NIFTY 500", "group": "returns_risk", "format": "num", "fn": lambda r: r["benchmark_relative"]["information_ratio"], "source": "benchmark_relative()"},
    {"label": "Deflated Sharpe, repo default (unit variance)", "group": "returns_risk", "format": "num", "fn": lambda r: r["deflated_sharpe"]["deflated_sharpe_prob"],
     "source": lambda r: f"research.deflated_sharpe(), {r['n_trials']} trials"},
    {"label": "Deflated Sharpe, variance of the variants' Sharpes", "group": "returns_risk", "format": "num", "fn": lambda r: r["deflated_sharpe_variants_variance"]["deflated_sharpe_prob"],
     "source": "research.deflated_sharpe(benchmark_sharpe=expected_max_sharpe(n, var))"},
    {"label": "Two-way turnover a year (x capital)", "group": "costs_execution", "format": "num", "fn": lambda r: r["turnover_two_way_annual"], "source": "simulate()"},
    {"label": "Breakeven round-trip cost vs NIFTY 500 (bp; beyond the sweep if blank)", "group": "costs_execution", "format": "num", "fn": lambda r: r["breakeven_bp"] if np.isfinite(r["breakeven_bp"]) else None, "source": "out/cost_sweep.csv"},
    {"label": "Names held per rebalance, mean", "group": "costs_execution", "format": "num", "fn": lambda r: r["holdings_check"]["mean_names"], "source": "out/rebalance_log.csv"},
    {"label": "Rebalances with fewer than 5 names", "group": "diagnostics", "format": "int", "fn": lambda r: r["holdings_check"]["rebalances_under_5_names"], "source": "out/rebalance_log.csv"},
    {"label": "Largest single weight at any rebalance", "group": "costs_execution", "format": "pct", "fn": lambda r: r["holdings_check"]["max_weight"], "source": "out/rebalance_log.csv"},
    {"label": "Different stocks held over the run", "group": "costs_execution", "format": "int", "fn": lambda r: r["holdings_check"]["names_ever_held"], "source": "simulate()"},
    {"label": "Top-2 stocks' share of gross gains", "group": "costs_execution", "format": "pct", "fn": lambda r: r["holdings_check"]["top2_share_of_gross_gains"], "source": "out/contributors.csv"},
    {"label": "Mean cash share of NAV", "group": "costs_execution", "format": "pct", "fn": lambda r: r["cash"]["mean_share"], "source": "simulate()"},
    {"label": "Share of signals with buying shut by the index filter", "group": "diagnostics", "format": "pct", "fn": lambda r: r["cash"]["gate_closed_share_of_signals"], "source": "out/rebalance_log.csv"},
    {"label": "Median holding period (days)", "group": "costs_execution", "format": "num", "fn": lambda r: r["exits"]["median_holding_days"], "source": "out/exits.csv"},
    {"label": "Top-band names removed by the gap rule, mean per signal", "group": "diagnostics", "format": "num", "fn": lambda r: r["filters"]["mean_top_disq_gap"], "source": "out/rebalance_log.csv"},
    {"label": "Buys on days the stock closed up more than 9.5% (band proxy)", "group": "diagnostics", "format": "int", "fn": lambda r: r["band_days"]["buys_on_up_9_5pct_days"], "source": "simulate()"},
    {"label": "Average NAV share in Smallcap 250 names", "group": "costs_execution", "format": "pct",
     "fn": lambda r: float(np.mean([row.get("small", 0.0) for row in r["cap_mix_by_year"]])) if r["cap_mix_by_year"] else None, "source": "out/cap_mix_by_year.csv"},
    {"label": "Bootstrap Sharpe 95% low", "group": "robustness", "format": "num", "fn": lambda r: r["bootstrap"]["intervals"]["strategy"]["sharpe"][0], "source": "stationary_bootstrap()"},
    {"label": "Bootstrap Sharpe 95% high", "group": "robustness", "format": "num", "fn": lambda r: r["bootstrap"]["intervals"]["strategy"]["sharpe"][1], "source": "stationary_bootstrap()"},
    {"label": "Paired P(no Sharpe edge) vs NIFTY 500", "group": "robustness", "format": "num", "fn": lambda r: r["bootstrap"]["paired_sharpe_diff_vs_strategy"]["NIFTY 500"]["p_not_positive"], "source": "stationary_bootstrap()"},
    {"label": "Paired P(no Sharpe edge) vs equal-weight members", "group": "robustness", "format": "num", "fn": lambda r: r["bootstrap"]["paired_sharpe_diff_vs_strategy"]["Equal weight"]["p_not_positive"], "source": "stationary_bootstrap()"},
    {"label": "Paired P(no Sharpe edge) vs Momentum 50", "group": "robustness", "format": "num", "fn": lambda r: r["bootstrap"]["paired_sharpe_diff_vs_strategy"]["Momentum 50"]["p_not_positive"], "source": "stationary_bootstrap()"},
    {"label": "Paired P(no Sharpe edge) vs no-filter variant", "group": "robustness", "format": "num", "fn": lambda r: r["bootstrap"]["paired_sharpe_diff_vs_strategy"]["No filter"]["p_not_positive"], "source": "stationary_bootstrap()"},
    {"label": "Worst sub-period excess CAGR over NIFTY 500", "group": "robustness", "format": "pct", "fn": lambda r: min(w["excess_cagr"] for w in r["sub_period_stability"]), "source": "out/sub_period_stability.csv"},
    {"label": "Factor alpha a year", "group": "robustness", "format": "pct", "fn": lambda r: r["factor_fingerprint"].get("alpha_ann"), "source": "factor_fingerprint()"},
    {"label": "Factor alpha HAC t-stat", "group": "robustness", "format": "num", "fn": lambda r: r["factor_fingerprint"].get("alpha_t_hac"), "source": "factor_fingerprint()"},
    {"label": "Factor alpha a year, over the Sharpe hurdle", "group": "robustness", "format": "pct", "fn": lambda r: r["factor_fingerprint_hurdle"].get("alpha_ann"), "source": "factor_fingerprint(), config/fund.yaml sharpe_hurdle"},
    {"label": "Factor alpha HAC t-stat, over the Sharpe hurdle", "group": "robustness", "format": "num", "fn": lambda r: r["factor_fingerprint_hurdle"].get("alpha_t_hac"), "source": "factor_fingerprint(), config/fund.yaml sharpe_hurdle"},
    {"label": "Loading on NIFTY500 Momentum 50", "group": "robustness", "format": "num", "fn": lambda r: r["factor_fingerprint"].get("loadings", {}).get("NIFTY500 MOMENTUM 50"), "source": "factor_fingerprint()"},
    {"label": "Loading on NIFTY500 Value 50", "group": "robustness", "format": "num", "fn": lambda r: r["factor_fingerprint"].get("loadings", {}).get("NIFTY500 VALUE 50"), "source": "factor_fingerprint()"},
    {"label": "Factor R-squared", "group": "robustness", "format": "num", "fn": lambda r: r["factor_fingerprint"].get("r_squared"), "source": "factor_fingerprint()"},
    {"label": "Alpha HAC t without the Momentum 50 sleeve", "group": "robustness", "format": "num", "fn": lambda r: r["factor_fingerprint_without_momentum"].get("alpha_t_hac"), "source": "factor_fingerprint()"},
    {"label": "Alpha HAC t, no-filter variant", "group": "robustness", "format": "num", "fn": lambda r: r["factor_fingerprint_no_filter_variant"].get("alpha_t_hac"), "source": "factor_fingerprint()"},
    {"label": "CAGR, Thursday signal / Friday fill", "group": "robustness", "format": "pct", "fn": lambda r: _sens(r, "Thursday")["cagr"], "source": "out/sensitivities.csv"},
    {"label": "CAGR, 20% gap limit", "group": "robustness", "format": "pct", "fn": lambda r: _sens(r, "20% gap")["cagr"], "source": "out/sensitivities.csv"},
    {"label": "CAGR, 120-day regression", "group": "robustness", "format": "pct", "fn": lambda r: _sens(r, "120-day")["cagr"], "source": "out/sensitivities.csv"},
    {"label": "CAGR with cash at 0%", "group": "robustness", "format": "pct", "fn": lambda r: _cash(r, 0.0)["cagr"], "source": "out/cash_rate_sweep.csv"},
    {"label": "Look-ahead and accounting checks passed", "group": "other", "format": "text", "fn": lambda r: f"{sum(1 for c in r['checks'] if c['passed'])} of {len(r['checks'])}", "source": "out/checks.csv"},
    {"label": "Signals (weekly)", "group": "other", "format": "int", "fn": lambda r: r["n_signals"], "source": "simulate()"},
    {"label": "Member-days with a move over the gap limit that coincide with an Ace adjustment change", "group": "other", "format": "text",
     "fn": lambda r: f"{r['gap_events']['n_with_adjustment_factor_change']} of {r['gap_events']['n_member_days_over_15pct']}", "source": "out/gap_events.csv"},
    # appended 2026-11-02 (universe v2 and the start rule)
    {"label": "Universe source (card: universe.membership_source)", "group": "other", "format": "text", "fn": lambda r: r["universe"]["source"], "source": "card"},
    {"label": "First signal and first fill", "group": "other", "format": "text", "fn": lambda r: f"{r['sched_first']} -> {r['first_fill']}", "source": "simulate()"},
    {"label": "Members at the first signal", "group": "other", "format": "int", "fn": lambda r: r["universe"]["first_signal_members"], "source": "out/universe_coverage.csv"},
    {"label": "Members with an Ace close at the first signal", "group": "other", "format": "int", "fn": lambda r: r["universe"]["first_signal_priced"], "source": "out/universe_coverage.csv"},
    {"label": "Members never priced over the run (in universe, never tradable)", "group": "other", "format": "int", "fn": lambda r: len(r["universe"]["never_priced"]), "source": "out/universe_coverage.csv"},
    {"label": "CAGR from 2015 (survivorship sensitivity)", "group": "robustness", "format": "pct", "fn": lambda r: _sens(r, "From 2015")["cagr"], "source": "out/sensitivities.csv"},
    {"label": "Edge over NIFTY 500 from 2015 (survivorship sensitivity)", "group": "robustness", "format": "pct", "fn": lambda r: _sens(r, "From 2015")["minus_nifty500_cagr"], "source": "out/sensitivities.csv"},
]


def universe_coverage(d: dict, sig: dict, sched, out: str) -> dict:
    """What the run's own membership panel held, year by year, and how much of it Ace priced (close within the carry
    limit). Unpriced members are in the universe and cannot be traded; they are named, never dropped."""
    members = d["members"]
    priced = members & sig["close"].notna()
    rows = []
    window = members.index[members.index >= START]
    for y, idx in window.to_series().groupby(window.year):
        m, p = members.loc[idx].sum(axis=1), priced.loc[idx].sum(axis=1)
        ever_member = members.loc[idx].any(axis=0)
        ever_priced = priced.loc[idx].any(axis=0)
        never = sorted(d["names"][i][0] for i in members.columns[ever_member & ~ever_priced])
        rows.append({"year": int(y), "sessions": len(idx), "members_min": int(m.min()), "members_max": int(m.max()),
                     "members_mean": round(float(m.mean()), 1), "priced_min": int(p.min()), "priced_max": int(p.max()),
                     "priced_mean": round(float(p.mean()), 1), "unpriced_mean": round(float((m - p).mean()), 1),
                     "never_priced_in_year": len(never), "never_priced_names": ", ".join(never)})
    pd.DataFrame(rows).to_csv(os.path.join(out, "universe_coverage.csv"), index=False)
    s0 = sched[0][0]
    ever_m = members.loc[window].any(axis=0) | members.loc[s0]
    ever_p = priced.loc[window].any(axis=0) | priced.loc[s0]
    never_all = sorted(d["names"][i][0] for i in members.columns[ever_m & ~ever_p])
    return {"source": MEMBERSHIP_SOURCE, "by_year": rows, "first_signal_date": str(s0.date()),
            "first_signal_members": int(members.loc[s0].sum()), "first_signal_priced": int(priced.loc[s0].sum()),
            "first_signal_unpriced_names": sorted(d["names"][i][0] for i in members.columns[members.loc[s0] & ~priced.loc[s0]]),
            "never_priced": never_all}


def write_fixed_notes(raw: dict, out: str) -> str:
    """out/notes_fixed.json: sentences computed here that Lightyear places first in the Notes, whatever the model writes."""
    u = raw["universe"]
    by = {r["year"]: r for r in u["by_year"]}
    cov = "; ".join(f"{y}: {by[y]['members_mean']:.0f} members, {by[y]['priced_mean']:.0f} priced" for y in sorted(by))
    unp = "; ".join(f"{y}: {1 - by[y]['priced_mean'] / by[y]['members_mean']:.1%}" for y in sorted(by)
                    if by[y]["members_mean"] and by[y]["priced_mean"] < by[y]["members_mean"])
    s15 = _sens(raw, "From 2015")
    notes = [
        (f"SURVIVORSHIP BIAS, UPWARD: {len(u['never_priced'])} NIFTY 500 members over the run have no Ace price at all, so the "
         f"book can never hold them into their fall. Share of member-days with no price, by year: {unp or 'none'}. "
         f"Names: {', '.join(u['never_priced']) or 'none'}. Measured from 2015 (leaving out the worst years) the book "
         f"returns {s15['cagr']:.1%} a year, {s15['minus_nifty500_cagr']:+.1%} against NIFTY 500 over the same years."
         if s15 else "Survivorship: see the unpriced members below."),
        f"Universe: membership_source = {u['source']} ({nifty500.MEMBERSHIP_SOURCES.get(u['source'], '')}).",
        f"Universe coverage by year, mean per session on the run's own panel: {cov}.",
        (f"Unpriced members (in the universe, never tradable, so the survivorship bias they carry remains): "
         f"{len(u['never_priced'])} names over the run: {', '.join(u['never_priced']) or 'none'}. The only fix is price "
         f"history for these names (the 'Adjusted Prices' folder is empty on this machine)."),
        (f"Start rule: first signal {u['first_signal_date']} on the {FIRST_SIGNAL_UNIVERSE} list ({u['first_signal_members']} "
         f"names, {u['first_signal_priced']} with an Ace close), first fill {raw['first_fill']}, so the book is invested from "
         f"the window's first session; the benchmark starts the same day."
         if FIRST_SIGNAL is not None else
         f"Start: first signal {u['first_signal_date']} (the first signal weekday on or after the sample start), first fill "
         f"{raw['first_fill']}; the book is in cash until then."),
    ]
    mpx = raw.get("missing_prices") or {}
    sus = "; ".join(f"{r['symbol']} {r['first']} to {r['last']} ({r['sessions']} sessions)" for r in mpx.get("suspensions", []))
    dls = "; ".join(f"{r['symbol']} from {r['first']}" for r in mpx.get("delistings", []))
    notes.append("Missing prices (ros/engine/missing_prices.py): a held name with no price is kept at its last close, "
                 "not traded, and its orders roll to the next day it trades. Suspensions held through (over 20 sessions "
                 f"without a price, no delisting on record): {sus or 'none'}. Delistings exited at the last close: {dls or 'none'}. "
                 "See out/missing_prices.csv.")
    p = os.path.join(out, "notes_fixed.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(notes, fh, indent=1)
    return p


def gate_a_revisions(run_dir: str) -> list[dict]:
    """The Gate A revisions Lightyear recorded for this run (state.json), so the manifest carries them too."""
    p = os.path.join(run_dir, "state.json")
    try:
        with open(p, encoding="utf-8") as fh:
            st = json.load(fh)
        return [{"at": r.get("at"), "notes": r.get("notes")} for r in (st.get("revisions") or [])]
    except (OSError, ValueError):
        return []


def write_fixed_outputs(raw: dict, out: str, run_dir: str) -> list[str]:
    """out/validation_rows.json and out/tables.json: the fixed Validation rows and sheet list Lightyear puts first."""
    rows = []
    for spec in FIXED_VALIDATION_SPEC:
        try:
            v = spec["fn"](raw)
        except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError):
            v = None
        src = spec["source"](raw) if callable(spec["source"]) else spec["source"]
        rows.append({"label": spec["label"], "value": (None if v is None or (isinstance(v, float) and math.isnan(v)) else v),
                     "format": spec["format"], "source": src, "group": spec["group"]})
    rel_out = os.path.relpath(out, REPO_DIR).replace("\\", "/")
    tables = [{"title": t["title"], "csv": f"{rel_out}/{t['csv']}", "note": t["note"]} for t in FIXED_TABLES
              if os.path.exists(os.path.join(out, t["csv"]))]
    p1, p2 = os.path.join(out, "validation_rows.json"), os.path.join(out, "tables.json")
    with open(p1, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=1, default=str)
    with open(p2, "w", encoding="utf-8") as fh:
        json.dump(tables, fh, indent=1)
    return [p1, p2]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run-dir", default=(os.path.join(REPO_DIR, "outputs", "lightyear", os.environ["LIGHTYEAR_RUN"])
                                          if os.environ.get("LIGHTYEAR_RUN") else None),
                    help="the Lightyear run folder to write into; defaults to $LIGHTYEAR_RUN's folder, required otherwise")
    ap.add_argument("--auto-approve", action="store_true", default=True)
    ap.add_argument("--n-boot", type=int, default=2000)
    args = ap.parse_args()
    if not args.run_dir:
        raise SystemExit("--run-dir is required (or set LIGHTYEAR_RUN): this script never writes into another run's folder")
    run_dir = args.run_dir
    global TRIALS, N_VERSIONS, N_TRIALS
    TRIALS = trials.count(SLUG, int(CARD_OBJ.n_configs_tried), exclude_run=run_dir)
    N_VERSIONS = TRIALS["versions"]
    N_TRIALS = N_VERSIONS + N_SENSITIVITIES      # every version tried, plus this run's sensitivities
    out = os.path.join(run_dir, "out")
    charts_dir = os.path.join(out, "charts")
    os.makedirs(charts_dir, exist_ok=True)
    produced: list[str] = []
    t0 = time.time()
    card = CARD_OBJ
    assert float(card.costs.spread_bps) == P["cost_bp"], "the headline cost must be the card's"
    assert str(START.date()) == card.backtest_plan.sample_start and str(END.date()) == card.backtest_plan.sample_end, "window must be the card's"
    assert P["gap_limit"] == float(card.signal.params["gap_limit"]), "gap limit must be the card's"
    assert P["signal_weekday"] == _WEEKDAY[str(card.signal.params["signal_weekday"]).lower()], "signal weekday must be the card's"
    assert N_TRIALS >= int(card.n_configs_tried), "trial count can only add to the card's"
    assert MEMBERSHIP_SOURCE in nifty500.MEMBERSHIP_SOURCES, f"unknown universe.membership_source {MEMBERSHIP_SOURCE!r}"
    assert (FIRST_SIGNAL is None) == (FIRST_SIGNAL_UNIVERSE is None), "first_signal_date and first_signal_universe go together"
    log(f"universe: {MEMBERSHIP_SOURCE}; start rule: " + (f"first signal {FIRST_SIGNAL.date()} on {FIRST_SIGNAL_UNIVERSE}, "
        f"first fill {START.date()}" if FIRST_SIGNAL is not None else "first signal is the first signal weekday on or after the start"))
    log(f"card {os.path.relpath(CARD, REPO_DIR)}: window {START.date()} to {END.date()}, {COST_LABEL}, gap {P['gap_limit']:.0%}, "
        f"signal weekday {P['signal_weekday']}, cash {P['cash_rate']:.0%}, trials {N_TRIALS}, mandate allows cash {MANDATE_ALLOWS_CASH}")

    # ---------------------------------------------------------------- Stage 04: point-in-time data
    d = load_data()
    cal = d["cal"]
    window = cal[cal >= START]
    rf_daily = synthetic_cash_series(window, P["cash_rate"])
    log(f"panel: {len(d['isins'])} ISINs x {len(cal)} days; window {window[0].date()} to {window[-1].date()} "
        f"({len(window)} days); index days filled forward in window: {d['idx_missing_days']}")
    log(f"membership staleness: {d['stale']['message']}")
    sig = build_signals(d, P["regression_days"], P["gap_limit"])
    sched = signal_schedule(cal, P["signal_weekday"])
    log(f"{len(sched)} signals, first {sched[0][0].date()} -> {sched[0][1].date()}, last {sched[-1][0].date()} -> {sched[-1][1].date()}")
    pit = {"isins": len(d["isins"]), "days": len(cal), "window": [str(window[0].date()), str(window[-1].date())],
           "n_signals": len(sched), "first_signal": str(sched[0][0].date()), "first_fill": str(sched[0][1].date()),
           "last_signal": str(sched[-1][0].date()), "last_fill": str(sched[-1][1].date()),
           "index_days_forward_filled_in_window": d["idx_missing_days"], "membership_staleness": d["stale"],
           "ace_source_sha256": ace.provenance()["source_sha256"], "nifty500_last_snapshot": nifty500.provenance()["last_snapshot"],
           "index_workbook_sha256": d["prov_index"], "price_basis": "Ace back-adjusted OHLC; PRICE returns, no dividends",
           "membership_source": MEMBERSHIP_SOURCE, "membership_provenance": nifty500.provenance(source=MEMBERSHIP_SOURCE),
           "first_signal_rule": ({"first_signal_date": str(FIRST_SIGNAL.date()), "first_signal_universe": FIRST_SIGNAL_UNIVERSE}
                                 if FIRST_SIGNAL is not None else None)}
    uni = universe_coverage(d, sig, sched, out)
    produced.append(os.path.join(out, "universe_coverage.csv"))
    with open(os.path.join(out, "pit_snapshot.json"), "w", encoding="utf-8") as fh:
        json.dump(pit, fh, indent=1, default=str)
    produced.append(os.path.join(out, "pit_snapshot.json"))
    if not checkpoint("Stage 04 -- point-in-time data built", produced, auto_approve=args.auto_approve):
        return 1

    # ---------------------------------------------------------------- Stage 05: the book's rules
    print("LIGHTYEAR-STAGE: 05", flush=True)
    log(f"base run: the book's rules, {COST_LABEL}, cash at {P['cash_rate']:.0%}")
    base = simulate(d, sig, P, write_logs=True)
    nav = base["nav"]
    bench = d["index"]["close"].reindex(window)
    bench = bench / bench.iloc[0] * START_CAPITAL
    mom50 = d["sleeves"]["NIFTY500 MOMENTUM 50"].reindex(window)
    mom50 = mom50 / mom50.iloc[0] * START_CAPITAL
    log("comparators: equal weight and inverse volatility baskets of all members, no-filter variant")
    ew = basket(d, sig, "equal") * START_CAPITAL
    iv = basket(d, sig, "inverse_vol") * START_CAPITAL
    nofilter = simulate(d, sig, {**P, "use_index_filter": False})

    log("sensitivities: Thursday signal, 20% gap, 120-day regression")
    thu = simulate(d, sig, {**P, "signal_weekday": 3})
    sig20 = build_signals(d, P["regression_days"], 0.20)
    gap20 = simulate(d, sig20, P)
    sig120 = build_signals(d, 120, P["gap_limit"])
    reg120 = simulate(d, sig120, P)
    log("cost sweep and cash-rate sweep")
    sweep = {bp: (base if bp == P["cost_bp"] else simulate(d, sig, {**P, "cost_bp": float(bp)})) for bp in COST_SWEEP_BP}
    cash_runs = {r: (base if r == P["cash_rate"] else simulate(d, sig, {**P, "cash_rate": r})) for r in CASH_SWEEP}

    # ---------------------------------------------------------------- performance tables
    def ret(s):
        return s.pct_change().dropna()

    perf_rows = [nav_metrics(nav, rf_daily, f"Stocks on the Move book ({COST_LABEL}, cash {P['cash_rate']:.0%})"),
                 nav_metrics(bench, rf_daily, "NIFTY 500 (price index)"),
                 nav_metrics(ew, rf_daily, "Equal-weight NIFTY 500 members (monthly)"),
                 nav_metrics(iv, rf_daily, "Inverse-volatility NIFTY 500 members (monthly)"),
                 nav_metrics(mom50, rf_daily, "NIFTY500 Momentum 50 (price, backfilled)"),
                 nav_metrics(nofilter["nav"], rf_daily, "Same rules, no 200-day index filter"),
                 nav_metrics(thu["nav"], rf_daily, "Thursday signal, Friday fill"),
                 nav_metrics(gap20["nav"], rf_daily, "20% gap limit instead of 15%"),
                 nav_metrics(reg120["nav"], rf_daily, "120-day regression instead of 90")]
    perf = pd.DataFrame(perf_rows)
    perf.to_csv(os.path.join(out, "performance.csv"), index=False)
    produced.append(os.path.join(out, "performance.csv"))
    print(perf.to_string())

    bench_cagr = cagr(bench)
    sweep_rows = []
    for bp, r in sweep.items():
        m = nav_metrics(r["nav"], rf_daily, f"{bp}bp")
        sweep_rows.append({"round_trip_cost_bp": bp, "cagr": m["cagr"], "sharpe": m["sharpe"], "max_dd": m["max_dd"],
                           "minus_nifty500_cagr": m["cagr"] - bench_cagr})
    sweep_df = pd.DataFrame(sweep_rows)
    edge = sweep_df["minus_nifty500_cagr"].to_numpy()
    bps = sweep_df["round_trip_cost_bp"].to_numpy(dtype=float)
    if (edge > 0).all():
        breakeven = float("inf")
    elif edge[0] <= 0:
        breakeven = 0.0
    else:
        i = int(np.argmax(edge <= 0))
        breakeven = float(bps[i - 1] + (bps[i] - bps[i - 1]) * edge[i - 1] / (edge[i - 1] - edge[i]))
    sweep_df.to_csv(os.path.join(out, "cost_sweep.csv"), index=False)
    produced.append(os.path.join(out, "cost_sweep.csv"))

    cash_df = pd.DataFrame([{"cash_rate": r, **{k: v for k, v in nav_metrics(x["nav"], rf_daily, "").items() if k in ("cagr", "vol", "sharpe", "max_dd")}}
                            for r, x in cash_runs.items()])
    cash_df.to_csv(os.path.join(out, "cash_rate_sweep.csv"), index=False)
    produced.append(os.path.join(out, "cash_rate_sweep.csv"))

    sens = pd.DataFrame([{"variant": nm, **{k: v for k, v in nav_metrics(x, rf_daily, nm).items() if k in ("cagr", "vol", "sharpe", "max_dd")},
                          "minus_nifty500_cagr": cagr(x) - bench_cagr}
                         for nm, x in [("Base: Tuesday signal, 15% gap, 90-day regression, index filter", nav),
                                       ("Thursday signal, Friday fill", thu["nav"]), ("20% gap limit", gap20["nav"]),
                                       ("120-day regression", reg120["nav"]), ("No 200-day index filter", nofilter["nav"])]])
    # survivorship sensitivity: the same run measured from 2015, leaving out 2013-14, the years with the most members
    # Ace never priced (they cannot be held into their fall, so the bias is upward)
    s15, b15 = nav.loc[SENS_FROM_2015:], bench.loc[SENS_FROM_2015:]
    m15 = nav_metrics(s15, rf_daily.loc[SENS_FROM_2015:], "From 2015")
    sens = pd.concat([sens, pd.DataFrame([{"variant": "From 2015 (survivorship: 2013-14 hold the most unpriced members)",
                                           **{k: m15[k] for k in ("cagr", "vol", "sharpe", "max_dd")},
                                           "minus_nifty500_cagr": cagr(s15) - cagr(b15)}])], ignore_index=True)
    sens.to_csv(os.path.join(out, "sensitivities.csv"), index=False)
    produced.append(os.path.join(out, "sensitivities.csv"))

    # calendar years
    def cy(s):
        v = s.groupby(s.index.year).last()
        first = s.groupby(s.index.year).first()
        return v / v.shift(1).fillna(first) - 1
    cal_years = pd.DataFrame({"strategy": cy(nav), "nifty500": cy(bench), "equal_weight": cy(ew), "momentum50": cy(mom50),
                              "no_filter": cy(nofilter["nav"])})
    cal_years["strategy_minus_nifty500"] = cal_years["strategy"] - cal_years["nifty500"]
    cal_years.index.name = "year"
    cal_years.to_csv(os.path.join(out, "calendar_year_returns.csv"))
    produced.append(os.path.join(out, "calendar_year_returns.csv"))

    rb = base["rebalances"]
    rb.to_csv(os.path.join(out, "rebalance_log.csv"), index=False)
    produced.append(os.path.join(out, "rebalance_log.csv"))

    # ---------------------------------------------------------------- Stage 06: research validation
    print("LIGHTYEAR-STAGE: 06", flush=True)
    log("bootstrap, deflated Sharpe, walk-forward")
    rets = {"strategy": ret(nav), "NIFTY 500": ret(bench), "Equal weight": ret(ew), "Momentum 50": ret(mom50),
            "No filter": ret(nofilter["nav"])}
    boot = research.stationary_bootstrap(rets, rf_daily, n_boot=args.n_boot, baseline="strategy")
    dsr = research.deflated_sharpe(ret(nav), N_TRIALS, rf_daily)
    # the same test with the trials' OWN Sharpe dispersion instead of unit variance (both are reported, fixed rows)
    var_sharpe = float(sens["sharpe"].var(ddof=1)) if len(sens) > 1 else 1.0
    dsr_var = research.deflated_sharpe(ret(nav), N_TRIALS, rf_daily, benchmark_sharpe=research.expected_max_sharpe(N_TRIALS, var_sharpe))
    # the latest index correction deeper than 10%: peak to trough of the NIFTY 500, and both series' falls over it
    bench_dd = bench / bench.cummax() - 1
    deep = bench_dd[bench_dd < -0.10]
    if len(deep):
        last_deep = deep.index[-1]                                   # the latest day the index sat more than 10% below its high
        pre = bench_dd.loc[:last_deep]
        peak = pre[pre >= -1e-12].index[-1] if (pre >= -1e-12).any() else pre.index[0]
        post = bench_dd.loc[last_deep:]
        recovered = post[post >= -1e-12]
        end_ep = recovered.index[0] if len(recovered) else post.index[-1]
        trough = bench_dd.loc[peak:end_ep].idxmin()                  # the deepest point of that whole spell
        win_s = nav.loc[peak:trough]
        latest_corr = {"peak": str(peak.date()), "trough": str(trough.date()),
                       "strategy_dd": float((win_s / win_s.cummax() - 1).min()), "nifty500_dd": float(bench_dd.loc[trough])}
    else:
        latest_corr = {"peak": None, "trough": None, "strategy_dd": None, "nifty500_dd": None}
    splits = research.walk_forward_split(nav.index, n_folds=4, min_train_years=3)
    oos = research.oos_summary(_Res(nav, base["turnover"], "strategy"), splits, rf_daily, bench=_Res(bench, None, "NIFTY 500"))
    oos.to_csv(os.path.join(out, "sub_period_stability.csv"), index=False)
    produced.append(os.path.join(out, "sub_period_stability.csv"))
    print(oos.to_string())
    sub = research.subperiod_table([_Res(nav, None, "strategy"), _Res(bench, None, "NIFTY 500"), _Res(ew, None, "Equal weight"),
                                    _Res(nofilter["nav"], None, "No filter")], rf_daily, n_periods=4, metric="cagr")
    sub.to_csv(os.path.join(out, "subperiod_cagr.csv"))
    produced.append(os.path.join(out, "subperiod_cagr.csv"))

    checks = lookahead_checks(d, sig, sched, np.random.default_rng(11))
    w_ = base["weights"]
    gross = w_.sum(axis=1)
    checks.append({"check": "no negative weight and gross never above 100.5% of NAV", "passed": bool((w_.min().min() >= -1e-9) and (gross.max() <= 1.005)),
                   "detail": f"min weight {w_.min().min():.4f}, max gross {gross.max():.4f}"})
    checks.append({"check": "cash share plus stock weights equal 1 every day", "passed": bool(np.allclose(gross + base["cash_weight"], 1.0, atol=1e-6)),
                   "detail": f"max |gross + cash - 1| = {float((gross + base['cash_weight'] - 1).abs().max()):.2e}"})
    h_chk = base["holdings"]
    mem_ok = [bool(d["members"].at[pd.Timestamp(r.date), r.isin]) for r in h_chk.itertuples()] if len(h_chk) else []
    checks.append({"check": "every holding was a NIFTY 500 member at its signal date", "passed": bool(mem_ok) and all(mem_ok),
                   "detail": f"{len(mem_ok) - sum(mem_ok)} of {len(mem_ok)} holding rows were not members on their signal date"})
    checks.append({"check": "panel ends at the benchmark's last date; nothing after 2026-09-18 is read", "passed": bool(cal[-1] == END), "detail": str(cal[-1].date())})
    pd.DataFrame(checks).to_csv(os.path.join(out, "checks.csv"), index=False)
    produced.append(os.path.join(out, "checks.csv"))
    for c in checks:
        print(f"[{'PASS' if c['passed'] else 'FAIL'}] {c['check']} -- {c['detail']}")
    if not all(c["passed"] for c in checks):
        print("A CHECK FAILED: nothing downstream is trustworthy until it is fixed.")

    # ---------------------------------------------------------------- Stage 07: portfolio validation
    print("LIGHTYEAR-STAGE: 07", flush=True)
    log("factor fingerprint, benchmark-relative statistics, mandate, turnover")
    sleeves = d["sleeves"].reindex(window)
    fac = sleeves[["NIFTY 500", "NIFTY500 MOMENTUM 50", "NIFTY500 VALUE 50", "NIFTY500 QUALITY 50", "NIFTY500 LOW VOLATILITY 50"]]
    fac_ret = fac.pct_change(fill_method=None).dropna()
    ff = factor_fingerprint(ret(nav), fac_ret, rf_daily)
    # the same regression with returns above the Sharpe hurdle instead of the card's cash rate: reported beside it
    ff_hurdle = factor_fingerprint(ret(nav), fac_ret, pd.Series(config.hurdle_daily(), index=rf_daily.index))
    ff_nomom = factor_fingerprint(ret(nav), fac_ret.drop(columns=["NIFTY500 MOMENTUM 50"]), rf_daily)
    ff_nf = factor_fingerprint(ret(nofilter["nav"]), fac_ret, rf_daily)
    br = benchmark_relative(ret(nav), ret(bench), rf_daily)
    turnover_ann = float(base["turnover"].sum() / ((nav.index[-1] - nav.index[0]).days / 365.25))
    cash_mean, cash_max = float(base["cash_weight"].mean()), float(base["cash_weight"].max())
    pct_days_cash_over_half = float((base["cash_weight"] > 0.5).mean())
    cash_fact = f"holds cash as a drift on every day (mean {cash_mean:.1%}, max {cash_max:.1%})"
    mandate = {"max_cash": cash_max, "mean_cash": cash_mean, "max_single_weight": float(w_.max().max()),
               "pct_days_holding_cash": float((base["cash_weight"] > 1e-6).mean()),
               "mandate_allow_cash": MANDATE_ALLOWS_CASH}
    if MANDATE_ALLOWS_CASH:        # card portfolio.mandate_allow_cash: true (operator's ruling 2026-10-30)
        mandate.update(violations=[], passes=True,
                       note=f"{cash_fact}; the card's mandate_allow_cash is true, so the cash is allowed for this test")
    else:
        mandate.update(violations=[f"{cash_fact}; the mandate is fully invested"], passes=False)
    # what cash earned
    cash_contrib = float((base["cash_weight"].shift(1) * rf_daily).sum()) if True else 0.0

    # names, concentration, worst days, contributors
    held_min, held_max, held_mean = int(rb["n_held"].min()), int(rb["n_held"].max()), float(rb["n_held"].mean())
    max_w = float(rb["max_weight"].max())
    few = rb[rb["n_held"] < 5]
    r_s = ret(nav)
    r_b = ret(bench)
    worst = r_s.nsmallest(5)
    worst_rows = []
    for dte, rr in worst.items():
        wprev = w_.shift(1).loc[dte]
        held_j = wprev[wprev > 0].index
        day_ret = sig["ret"].loc[dte, held_j]
        contrib = (wprev[held_j] * day_ret).sort_values()
        worst_rows.append({"date": str(dte.date()), "strategy": float(rr), "nifty500": float(r_b.get(dte, np.nan)),
                           "n_held": len(held_j), "cash_share": float(base["cash_weight"].shift(1).loc[dte]),
                           "share_of_holdings_down": float((day_ret < 0).mean()) if len(held_j) else np.nan,
                           "worst_names": "; ".join(f"{d['names'][i][0]} {day_ret[i]:+.1%}" for i in contrib.index[:3])})
    worst_df = pd.DataFrame(worst_rows)
    worst_df.to_csv(os.path.join(out, "worst_days.csv"), index=False)
    produced.append(os.path.join(out, "worst_days.csv"))
    pnl = base["pnl_by_name"].sort_values(ascending=False)
    total_gain = float(pnl[pnl > 0].sum())
    contrib_df = pd.DataFrame({"isin": pnl.index, "symbol": [d["names"][i][0] for i in pnl.index],
                               "company": [d["names"][i][1] for i in pnl.index], "pnl_rs": pnl.values,
                               "share_of_gross_gains": pnl.values / total_gain if total_gain else np.nan})
    contrib_df = contrib_df[contrib_df["pnl_rs"] != 0]
    contrib_df.to_csv(os.path.join(out, "contributors.csv"), index=False)
    produced.append(os.path.join(out, "contributors.csv"))
    names_ever = int((w_ > 0).any().sum())
    top2_share = float(pnl.iloc[:2].sum() / total_gain) if total_gain else np.nan

    # cap mix by year (snapshot flags at the signal date)
    segs = d["segments"]
    h = base["holdings"].copy()
    snap_dates = np.array(sorted(segs["snapshot_date"].unique()))
    seg_map = {sd: g.set_index("isin")["segment"] for sd, g in segs.groupby("snapshot_date")}
    def seg_of(row):
        sd = snap_dates[snap_dates <= np.datetime64(pd.Timestamp(row["date"]))]
        if len(sd) == 0:
            return "unflagged"
        return seg_map[sd[-1]].get(row["isin"], "unflagged")
    if len(h):
        h["segment"] = h.apply(seg_of, axis=1)
        h["year"] = pd.to_datetime(h["date"]).dt.year
        # average weight in each cap segment per rebalance, by calendar year (the rest of 1.0 is cash)
        mix = h.groupby(["year", "segment"])["weight"].sum().unstack(fill_value=0.0)
        mix = mix.div(h.groupby("year")["date"].nunique(), axis=0)
    else:                      # a book that never held a name (an absurd card) still produces every table
        mix = pd.DataFrame(columns=["large", "mid", "small", "unflagged"])
        mix.index.name = "year"
    mix.to_csv(os.path.join(out, "cap_mix_by_year.csv"))
    produced.append(os.path.join(out, "cap_mix_by_year.csv"))

    # gap events among members: are the 15% moves real shocks or unadjusted corporate actions?
    adj_factor = (d["close"] / d["unadj_close"])
    fchg = (adj_factor / adj_factor.shift(1) - 1).abs() > 0.01
    big = (sig["ret"].abs() > P["gap_limit"]) & d["members"]
    big = big.loc[window]
    ev = big.stack()
    ev = ev[ev]
    unadj_ret_df = d["unadj_close"].pct_change(fill_method=None)
    gap_rows = []
    known = {(e.parent_isin, e.ex_date) for e in d["demergers"].itertuples()}
    listings = ace.security_master()[["company_name", "first_date"]].dropna()
    for (dte, isin) in ev.index:
        adj_move, fc = float(sig["ret"].at[dte, isin]), bool(fchg.at[dte, isin])
        gap_rows.append({"date": str(dte.date()), "isin": isin, "symbol": d["names"][isin][0], "adjusted_move": adj_move,
                         "unadjusted_move": float(unadj_ret_df.at[dte, isin]),
                         "adjustment_factor_changed": fc, "known_demerger": (isin, dte) in known,
                         "probable_unadjusted_corporate_action": corporate_actions.probable_unadjusted_action(
                             adj_move, fc, corporate_actions.new_listing_near(d["names"][isin][1], dte, listings),
                             (isin, dte) in known)})
    gap_df = pd.DataFrame(gap_rows)
    gap_df.to_csv(os.path.join(out, "gap_events.csv"), index=False)
    # the missing-price rule: every suspension (> 20 sessions without a price) and delisting the book sat through
    mpe = base["missing_price_events"].copy()
    mpe["symbol"] = [d["names"][i][0] for i in mpe["isin"]]
    mpe.to_csv(os.path.join(out, "missing_prices.csv"), index=False)
    produced.append(os.path.join(out, "missing_prices.csv"))
    produced.append(os.path.join(out, "gap_events.csv"))
    sells = base["sells"]
    sells.to_csv(os.path.join(out, "exits.csv"), index=False)
    produced.append(os.path.join(out, "exits.csv"))
    exit_summary = sells.groupby("reason")["return"].agg(["count", "mean", "median"]).reset_index() if len(sells) else pd.DataFrame()
    hold_days = (pd.to_datetime(sells["exit_date"]) - pd.to_datetime(sells["entry_date"])).dt.days if len(sells) else pd.Series(dtype=float)

    # ---------------------------------------------------------------- Gate B criteria (computed, PENDING)
    paired = boot.get("paired_sharpe_diff_vs_strategy", {})
    oos_min = float(oos["sharpe"].min()) if len(oos) else None
    research_d = {"deflated_sharpe": dsr, "oos_min_sharpe": oos_min,
                  "bootstrap_p_not_positive": paired.get("NIFTY 500", {}).get("p_not_positive")}
    portfolio_d = {"alpha_t_hac": ff.get("alpha_t_hac"), "alpha_t_hac_error": ff.get("error"), "annual_turnover": turnover_ann,
                   "mandate": mandate}
    gb = gate_b(card, research_d, portfolio_d)
    assert gb.decision == "PENDING"
    print(gb.render())

    # ---------------------------------------------------------------- charts
    footnote = (f"Price returns (no dividends in the Ace file); {COST_LABEL} (the card's costs.spread_bps); cash at a flat "
                f"{P['cash_rate']:.0%}. Benchmark: NIFTY 500 price index. Quant AI Researcher")
    charts = save_clean_charts(nav, bench, charts_dir, SLUG, strategy_name="Stocks on the Move book", benchmark_name="NIFTY 500 (price)",
                               weights=w_, sleeve=mom50, sleeve_name="NIFTY500 Momentum 50 (price, backfilled)", footnote=footnote)
    produced += charts

    # ---------------------------------------------------------------- hand-off files
    d["names"]
    dr = pd.DataFrame({"date": r_s.index, "strategy": r_s.values, "benchmark": r_b.reindex(r_s.index).values,
                       "sleeve": ret(mom50).reindex(r_s.index).values})
    dr.to_csv(os.path.join(run_dir, "daily_returns.csv"), index=False)
    hold = base["holdings"].copy()
    hold["date"] = pd.to_datetime(hold["date"]).dt.date
    hold["execution_date"] = pd.to_datetime(hold["execution_date"]).dt.date
    hold["entry_date"] = pd.to_datetime(hold["entry_date"]).dt.date
    hold.to_csv(os.path.join(run_dir, "holdings.csv"), index=False)
    tr = base["trades"].copy()
    for c in ("date", "signal_date", "execution_date", "price_date"):
        tr[c] = pd.to_datetime(tr[c]).dt.date
    tr.to_csv(os.path.join(run_dir, "trades.csv"), index=False)
    sel = base["selection"].copy()
    for c in ("signal_date", "execution_date"):
        sel[c] = pd.to_datetime(sel[c]).dt.date
    sel = sel.sort_values(["signal_date", "rank"])
    sel.to_csv(os.path.join(run_dir, "selection.csv"), index=False)
    comp = pd.DataFrame({"date": r_s.index,
                         "Equal-weight NIFTY 500 members (monthly)": ret(ew).reindex(r_s.index).values,
                         "Inverse-volatility NIFTY 500 members (monthly)": ret(iv).reindex(r_s.index).values,
                         "NIFTY500 Momentum 50 index (price, backfilled)": ret(mom50).reindex(r_s.index).values,
                         "Same rules, no 200-day index filter": ret(nofilter["nav"]).reindex(r_s.index).values})
    comp.to_csv(os.path.join(run_dir, "comparators.csv"), index=False)
    for f in ("daily_returns.csv", "holdings.csv", "trades.csv", "selection.csv", "comparators.csv"):
        produced.append(os.path.join(run_dir, f))

    raw = {
        "missing_prices": {"suspensions": mpe[mpe["kind"] == "suspended"][["symbol", "first", "last", "sessions"]].astype(str).to_dict("records"),
                           "delistings": mpe[mpe["kind"] == "delisted"][["symbol", "first"]].astype(str).to_dict("records")},
        "performance": perf_rows, "cost_sweep": sweep_rows, "breakeven_bp": breakeven, "cash_rate_sweep": cash_df.to_dict("records"),
        "sensitivities": sens.to_dict("records"), "calendar_years": cal_years.reset_index().to_dict("records"),
        "sub_period_stability": oos.to_dict("records"), "subperiod_cagr": sub.reset_index().to_dict("records"),
        "bootstrap": boot, "deflated_sharpe": dsr, "n_trials": N_TRIALS, "trials": {**TRIALS, "sensitivities": N_SENSITIVITIES},
        "factor_fingerprint": ff, "factor_fingerprint_hurdle": ff_hurdle,
        "factor_fingerprint_without_momentum": ff_nomom, "factor_fingerprint_no_filter_variant": ff_nf,
        "benchmark_relative": br, "turnover_two_way_annual": turnover_ann, "mandate": mandate,
        "cash": {"mean_share": cash_mean, "max_share": cash_max, "pct_days_over_half_cash": pct_days_cash_over_half,
                 "gate_closed_share_of_signals": float((~rb["gate_open"]).mean()),
                 "cash_return_contribution_simple_sum": cash_contrib},
        "holdings_check": {"min_names": held_min, "max_names": held_max, "mean_names": held_mean, "max_weight": max_w,
                           "max_weight_symbol": rb.loc[rb["max_weight"].idxmax(), "max_weight_symbol"],
                           "max_weight_date": str(rb.loc[rb["max_weight"].idxmax(), "signal_date"].date()),
                           "rebalances_under_5_names": len(few), "dates_under_5_names": [str(x.date()) for x in few["signal_date"]][:20],
                           "n_signals": len(rb), "names_ever_held": names_ever, "top2_share_of_gross_gains": top2_share,
                           "mean_top5_weight": float(rb["top5_weight"].mean())},
        "filters": {"mean_top_band": float(rb["top_n"].mean()), "mean_top_disq_gap": float(rb["n_top_disq_gap"].mean()),
                    "mean_top_disq_sma": float(rb["n_top_disq_sma"].mean()), "mean_top_eligible": float(rb["n_top_eligible"].mean()),
                    "signals_with_under_20_eligible": int((rb["n_top_eligible"] < 20).sum()),
                    "share_top_band_removed_by_gap": float((rb["n_top_disq_gap"] / rb["top_n"]).mean())},
        "exits": {"by_reason": exit_summary.to_dict("records"), "n_exits": len(sells),
                  "mean_holding_days": float(hold_days.mean()) if len(hold_days) else None,
                  "median_holding_days": float(hold_days.median()) if len(hold_days) else None,
                  "membership_sells": int(rb["n_sold_membership"].sum()), "delisting_exits": int(rb["n_sold_delisted"].sum()), "orders_rolled": int(rb["n_orders_rolled"].sum())},
        "band_days": {"buys_on_up_9_5pct_days": base["n_band_buys"], "sells_on_down_9_5pct_days": base["n_band_sells"],
                      "n_buys": int((tr["action"] == "BUY").sum()), "n_sells": int((tr["action"] == "SELL").sum())},
        "gap_events": {"n_member_days_over_15pct": len(gap_df), "n_with_adjustment_factor_change": int(gap_df["adjustment_factor_changed"].sum()) if len(gap_df) else 0,
                       "n_names": int(gap_df["isin"].nunique()) if len(gap_df) else 0},
        "cap_mix_by_year": mix.reset_index().to_dict("records"),
        "worst_days": worst_rows, "contributors_top5": contrib_df.head(5).to_dict("records"), "contributors_bottom5": contrib_df.tail(5).to_dict("records"),
        "checks": checks, "gate_b": gb.to_dict(), "pit": pit, "charts": [c.replace("\\", "/") for c in charts],
        "deflated_sharpe_variants_variance": dsr_var, "latest_index_correction": latest_corr,
        "params": P, "sched_first": str(sched[0][0].date()), "sched_last": str(sched[-1][0].date()), "n_signals": len(sched),
        "first_fill": str(sched[0][1].date()), "universe": uni,
        "runtime_s": time.time() - t0,
    }
    with open(os.path.join(out, "results_raw.json"), "w", encoding="utf-8") as fh:
        json.dump(raw, fh, indent=1, default=str)
    produced.append(os.path.join(out, "results_raw.json"))
    exit_summary.to_csv(os.path.join(out, "exits_by_reason.csv"), index=False)
    produced.append(os.path.join(out, "exits_by_reason.csv"))
    produced += write_fixed_outputs(raw, out, run_dir)       # after every table CSV exists
    produced.append(write_fixed_notes(raw, out))

    mp = write_run_manifest(run_dir, __file__, {"ace_prices": ACE_PRICES_CSV, "nifty500_holdings": NIFTY500_HOLDINGS_XLSX,
                                               "nse_index_workbook": NSE_INDEX_WORKBOOK, "card": CARD,
                                               **nifty500.membership_inputs(MEMBERSHIP_SOURCE, FIRST_SIGNAL_UNIVERSE),
                                               "demergers_sourced": corporate_actions.SOURCED,
                                               "demergers_table": corporate_actions.table_path()},
                            params={**CARD_PARAMS, **P, "n_trials": N_TRIALS, "n_versions": N_VERSIONS,
                                    "n_sensitivities": N_SENSITIVITIES, "cost_sweep_bp": COST_SWEEP_BP, "cash_sweep": CASH_SWEEP,
                                    "start": str(START.date()), "end": str(END.date()), "start_capital": START_CAPITAL,
                                    "mandate_allow_cash": MANDATE_ALLOWS_CASH, "sensitivities": list(SENSITIVITIES),
                                    "card_sha256_at_import": sha256_file(CARD), "membership_source": MEMBERSHIP_SOURCE,
                                    "first_signal_date": CARD_PARAMS.get("first_signal_date"),
                                    "first_signal_universe": CARD_PARAMS.get("first_signal_universe"),
                                    "gate_a_revisions": gate_a_revisions(run_dir)},
                            outputs=["daily_returns.csv", "holdings.csv", "trades.csv", "selection.csv", "comparators.csv"])
    produced.append(mp)
    checkpoint("Stages 05-07 complete -- hand-off files written; Gate B criteria computed, decision PENDING", produced, auto_approve=True)
    log(f"done in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
