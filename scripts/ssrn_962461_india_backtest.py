"""Step 05 to 07 for cards/ssrn_962461.yaml (Faber, 'A Quantitative Approach to Tactical Asset
Allocation', 2013 update), run AS DRAFTED and approved at Gate A.

Sources: NSE bhavcopy (data/raw/master/bhavcopy_screener_master.csv), Screener.in (current shares
and free float in the same master; industry labels in screener_industry_snapshot.csv, fetched by
scripts/ssrn_962461_fetch_industry.py), and the NIFTY 500 index workbook. Cash is a flat 6% a year.

What it runs:
  MAIN       five sleeves at 20% each -- NIFTY 500 and four free-float-weighted industry baskets of the
             top 500 NSE stocks by trailing traded value (export earners, rate sensitive, commodity
             producers, real estate). At each month-end close a sleeve above the average of its last ten
             month-end levels is 'on' for the next month, below is 'off' and its 20% sits in cash at 6%.
             Traded at the NEXT trading day's close. 30bp round trip on every switch, every monthly reset
             to 20%, and every trade inside a basket (quarterly reconstitution, names that stop trading).
  comparators  Buy & Hold the five sleeves (paper's own comparator), a static mix at the timing book's
             average exposure, NIFTY 500 timed alone, NIFTY 500 itself (the benchmark).
  variants   the mandate (fully invested) version, equal-weight baskets, an ex-basket domestic sleeve.
  sweeps     SMA length 6/8/10/12 and 10-excluding-current, cash 4/6/8%, cost 30/60/90bp + break-even,
             trade day (paper's same close, next day, +5, +10).

The sleeve baskets are built in build_basket() (plain, testable code). The per-sleeve switch is the
SleeveSwitch allocator below (the card's template_gap: 0.20 x 1[level > SMA10], no renormalisation).
The engine (universal_backtester, long-only here) does all accounting, the causal shift and costs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER = os.path.join(REPO, "data", "raw", "master", "bhavcopy_screener_master.csv")
INDUSTRY = os.path.join(REPO, "data", "raw", "master", "screener_industry_snapshot.csv")
INDEX_PATH = os.path.join(REPO, "data", "raw", "NSE_Broad_Factor_Indices_Historical_Data.xlsx")
CARD = os.path.join(REPO, "cards", "ssrn_962461.yaml")
OUT = os.path.join(REPO, "outputs")
SLUG = "ssrn_962461"

TOP_N = 500
LOOKBACK_SESSIONS, MIN_SESSIONS = 63, 40      # the master's own top-N rule (nse_bhavcopy_ingest)
OCT_2021_END = pd.Timestamp("2021-10-29")      # card: pre-flag membership known at this close
FIRST_LEVEL_MONTH = pd.Timestamp("2021-11-01")  # card: basket month-ends count from November 2021
LIVE_START = pd.Timestamp("2022-09-01")        # card: first trade
SMA_MONTHS, SLEEVE_W, NAME_CAP = 10, 0.20, 0.20
SPREAD_BPS, CASH_RATE = 30.0, 0.06
TRADE_OFFSET = 1                               # card lag_days 1: trade at the NEXT trading day's close
N_CONFIGS_TRIED = 20                           # the card's own count (a floor)
BLOCK = 63                                     # bootstrap block: a quarter; positions run several months

SLEEVES = ["NIFTY 500", "Export earners", "Rate sensitive", "Commodity producers", "Real estate"]


# ---------------------------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------------------------
def load_panel(path: str = MASTER):
    """Wide panels from the master: adjusted close, daily traded value (Rs cr), the master's
    top-1000 flag, plus the last symbol per security."""
    m = pd.read_csv(path, usecols=["date", "security_id", "symbol", "adj_close", "in_universe", "adv"],
                    parse_dates=["date"])
    px = m.pivot(index="date", columns="security_id", values="adj_close").sort_index()
    adv = m.pivot(index="date", columns="security_id", values="adv").reindex(px.index)
    flag = m.pivot(index="date", columns="security_id", values="in_universe").reindex(px.index).fillna(0).astype(bool)
    names = m.sort_values("date").groupby("security_id")["symbol"].last().to_dict()
    return px, adv, flag, names


def load_ff_mcap(path: str = MASTER):
    """Free-float market cap (Rs cr): adjusted close x TODAY's Screener shares x the current free-float
    fraction. Neither shares nor free float is point in time (MANIFEST caveats). Also returns the
    free-float fraction per security, NaN where Screener had none."""
    m = pd.read_csv(path, usecols=["date", "security_id", "market_cap", "free_float_frac"], parse_dates=["date"])
    mc = m.pivot(index="date", columns="security_id", values="market_cap").sort_index()
    ff = m.groupby("security_id")["free_float_frac"].last()
    return mc, ff


def top500_membership(adv: pd.DataFrame, flag: pd.DataFrame, top_n: int = TOP_N) -> pd.DataFrame:
    """The card's eligible universe, daily boolean, no look-ahead.

    From the first quarter the master's top-1000 flag is set: among flagged names on the quarter's
    first day, the top `top_n` by mean traded value over the 63 sessions strictly before the quarter
    (at least 40 with data) -- the master's own rule at N=500 -- held for the quarter.
    Before that: the top `top_n` by mean traded value over October 2021 alone, known at the
    2021-10-29 close and held fixed (card, selection.rule)."""
    idx = adv.index
    mem = pd.DataFrame(False, index=idx, columns=adv.columns)
    first_flag = flag.any(axis=1).idxmax()
    octw = adv.loc[:OCT_2021_END]
    n_oct = octw.notna().sum()
    oct_top = octw.mean()[n_oct >= int(0.75 * len(octw))].dropna().sort_values(ascending=False).head(top_n).index
    mem.loc[idx < first_flag, oct_top] = True
    for qs in pd.date_range(first_flag.to_period("Q").start_time, idx[-1], freq="QS"):
        days = idx[(idx >= qs) & (idx <= qs + pd.offsets.QuarterEnd(0))]
        if not len(days):
            continue
        trailing = adv.loc[:qs - pd.Timedelta(days=1)].tail(LOOKBACK_SESSIONS)
        ok = (trailing.notna().sum() >= MIN_SESSIONS) & flag.loc[days[0]]
        top = trailing.mean()[ok].dropna().sort_values(ascending=False).head(top_n).index
        mem.loc[days, top] = True
    return mem


def sleeve_of(row) -> str | None:
    """The card's industry-to-sleeve rule (selection.rule), applied to Screener's four-level label.
    IT services or pharmaceuticals -> export earners; banks or housing finance -> rate sensitive;
    steel, non-ferrous metals, mining, or crude oil and gas production -> commodity producers;
    real-estate developers -> real estate. Anything else: no basket."""
    def g(k):
        v = row.get(k)
        return v if isinstance(v, str) else ""
    sec, bi, ind = g("screener_sector"), g("screener_broad_industry"), g("screener_industry")
    if bi in ("IT - Software", "IT - Services") or ind == "Pharmaceuticals":
        return "Export earners"
    if bi == "Banks" or ind == "Housing Finance Company":
        return "Rate sensitive"
    # steel, non-ferrous, mining: the Metals & Mining sector, producers only (traders excluded);
    # crude oil and gas production: upstream and integrated producers; coal is mining
    if (sec == "Metals & Mining" and bi != "Metals & Minerals Trading") \
            or ind in ("Oil Exploration & Production", "Integrated Oil & Gas", "Coal"):
        return "Commodity producers"
    if bi == "Realty":
        return "Real estate"
    return None


def load_nifty500():
    from universal_backtester.data import load_banner_workbook
    d, _ = load_banner_workbook(INDEX_PATH, sheet="Broad Market")
    return d["NIFTY 500 Close"].dropna()


# ---------------------------------------------------------------------------------------------
# Baskets and signal
# ---------------------------------------------------------------------------------------------
def cap_weights(w: np.ndarray, cap: float) -> np.ndarray:
    """Exact per-name cap: names above `cap` are set to it and the excess goes pro rata to names still
    BELOW it, until none is above (at most one pass per name). With fewer than 1/cap names the cap
    cannot bind and the basket is equal weight -- the least concentrated book those names allow.
    (universal_backtester.allocators._cap_and_redistribute keeps feeding names already at the cap, so
    it converges only geometrically and its answer depends on how many zero-weight columns it is given;
    the truncation test caught that.)"""
    w = w.copy()
    k = int((w > 0).sum())
    if k == 0:
        return w
    cap = max(cap, 1.0 / k)
    for _ in range(k + 1):
        over = w > cap + 1e-12
        if not over.any():
            break
        excess = float((w[over] - cap).sum())
        w[over] = cap
        under = (w > 0) & (w < cap - 1e-12)
        if not under.any():
            break
        w[under] += excess * w[under] / w[under].sum()
    return w


def build_basket(pv: pd.DataFrame, weight_base, members: pd.DataFrame, recon_dates, cap: float, half: float):
    """A daily basket level, net of its own trading costs.

    At each reconstitution close: target weights over that day's members with a price, proportional to
    `weight_base` (free-float cap) or equal if None, capped at `cap` per name; trading the drifted book
    to the target costs `half` x traded. Between reconstitutions the book drifts with prices. A held
    name whose price disappears (delisted, suspended more than 5 days) is sold at its last price at
    cost and the proceeds reinvested pro rata, also at cost -- never quietly zeroed."""
    dates = pv.index
    cols = members.columns[members.any()]
    P = pv[cols].to_numpy(dtype=float)
    M = members[cols].to_numpy(dtype=bool)
    B = weight_base[cols].reindex(dates).to_numpy(dtype=float) if weight_base is not None else None
    rset = set(pd.DatetimeIndex(recon_dates))
    L, units, lastp, bcash = 1.0, np.zeros(len(cols)), np.full(len(cols), np.nan), 0.0
    level, diag, forced = [], [], 0
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
                w = cap_weights(w, cap)
                drift = np.where(units > 0, units * np.nan_to_num(p) / L, 0.0) if L > 0 and i > 0 else np.zeros(len(cols))
                traded = float(np.abs(w - drift).sum())
                L *= 1 - half * traded
                units = np.where(w > 0, L * w / np.where(ok, p, 1.0), 0.0)
                bcash = L * max(0.0, 1.0 - float(w.sum()))   # every name at the cap: the rest waits uninvested
                diag.append({"date": d.date().isoformat(), "names": int(ok.sum()), "members_without_weight": int((M[i] & ~ok).sum()),
                             "max_weight": float(w.max()), "traded": traded if i > 0 else float("nan")})
        lastp = np.where(np.isnan(p), lastp, p)
        level.append(L)
    return pd.Series(level, index=dates), pd.DataFrame(diag), forced


def month_ends(calendar: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Last trading day of each calendar month, from the full bhavcopy calendar."""
    s = pd.Series(calendar, index=calendar)
    return pd.DatetimeIndex(s.groupby(calendar.to_period("M")).max().to_numpy())


def sma_states(levels: pd.DataFrame, mends: pd.DatetimeIndex, months: int, include_current: bool = True,
               first_month: pd.Timestamp = FIRST_LEVEL_MONTH) -> pd.DataFrame:
    """1 = on, 0 = off at each month-end close, per sleeve. On if level > the average of the last
    `months` month-end levels (this one included, or the `months` before it if not); a tie keeps the
    previous state; fewer than `months` month-ends of history = off (not traded). Only month-ends from
    `first_month` count (the baskets start there)."""
    me = [d for d in mends if d >= first_month and d in levels.index]
    lv = levels.loc[me]
    sma = lv.rolling(months, min_periods=months).mean() if include_current else \
        lv.shift(1).rolling(months, min_periods=months).mean()
    out = pd.DataFrame(0.0, index=lv.index, columns=lv.columns)
    for c in lv.columns:
        prev = 0.0
        for d in lv.index:
            s, x = sma.at[d, c], lv.at[d, c]
            if np.isnan(s) or np.isnan(x):
                st = 0.0
            elif x > s:
                st = 1.0
            elif x < s:
                st = 0.0
            else:
                st = prev
            out.at[d, c], prev = st, st
    return out


def daily_from_monthly(states: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """The month-end state, carried through the following days (known from that close onward)."""
    return states.reindex(index).ffill()


# ---------------------------------------------------------------------------------------------
# Allocator: the card's per-sleeve switch (template_gap)
# ---------------------------------------------------------------------------------------------
from universal_backtester.allocators import Allocator  # noqa: E402


class SleeveSwitch(Allocator):
    """weight_i = sleeve_weight x 1[state_i == 1]; off sleeves' weight in cash, never renormalised.
    `mode="mandate"` instead moves an off sleeve's weight into sleeve 0 (the NIFTY 500): the fully
    invested variant. `mode="fixed"` ignores the state and holds `fixed` (buy & hold, static mix).
    Trades only on `trade_dates`."""
    template_name = "sleeve_switch_sma"

    def __init__(self, assets, trade_dates, sleeve_weight=SLEEVE_W, mode="cash", fixed=None):
        super().__init__(assets, sleeve_weight=sleeve_weight, mode=mode)
        self.trade_dates = set(pd.DatetimeIndex(trade_dates))
        self.w, self.mode = sleeve_weight, mode
        self.fixed = None if fixed is None else np.asarray(fixed, dtype=float)

    def ready(self, ctx):
        return ctx.date in self.trade_dates and (self.mode == "fixed" or ctx.alpha is not None)

    def target_weights(self, ctx):
        if self.mode == "fixed":
            return self.fixed.copy()
        on = np.nan_to_num(np.asarray(ctx.alpha, dtype=float), nan=0.0) == 1.0
        w = np.where(on, self.w, 0.0)
        if self.mode == "mandate":
            w[0] += self.w * float((~on).sum())
        return w


def trade_dates_for(mends: pd.DatetimeIndex, cal: pd.DatetimeIndex, offset: int, start: pd.Timestamp, end: pd.Timestamp):
    """Trading day `offset` sessions after each month-end (0 = the month-end close itself)."""
    pos = cal.get_indexer(mends)
    out = [cal[p + offset] for p in pos if p >= 0 and p + offset < len(cal)]
    return pd.DatetimeIndex([d for d in out if start <= d <= end])


# ---------------------------------------------------------------------------------------------
# Running a book, statistics
# ---------------------------------------------------------------------------------------------
def rf_series(index, rate):
    return pd.Series((1 + rate) ** (1 / 252) - 1, index=index)


def run_book(levels, assets, states_daily, tdates, spread=SPREAD_BPS, rate=CASH_RATE, mode="cash", fixed=None,
             offset=TRADE_OFFSET, name="book"):
    from universal_backtester.engine import Backtester
    bt = Backtester(prices=levels[assets], assets=assets, rf_daily=rf_series(levels.index, rate),
                    spread_bps=spread, lag_days=0, allow_cash=True)
    alpha = None
    if states_daily is not None:
        alpha = states_daily[assets]
        if offset == 0:              # paper's same-close trade: the state of THIS close (diagnostic only)
            alpha = alpha.shift(-1)
    alloc = SleeveSwitch(assets, tdates, mode=mode, fixed=fixed)
    return bt.run(allocator=alloc, rebalance="daily", alpha=alpha, name=name)


def live_slice(value, start, end):
    v = value.loc[(value.index >= start) & (value.index <= end)]
    v = v / v.iloc[0]
    r = v.pct_change(fill_method=None).fillna(0.0)
    return v, r


def stats(v, r, label, rate=CASH_RATE):
    from universal_backtester.metrics import ann_vol, cagr, max_drawdown, sharpe
    c, vol = cagr(v), ann_vol(r)
    return {"name": label, "cagr": c, "vol": vol, "sharpe_vs_6pct": (c - CASH_RATE) / vol if vol > 0 else float("nan"),
            "sharpe_excess_daily": sharpe(v, r, rf_series(r.index, rate)), "max_dd": max_drawdown(v),
            "n_obs": len(v), "start": str(v.index.min().date()), "end": str(v.index.max().date())}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-charts", action="store_true")
    ap.add_argument("--n-boot", type=int, default=2000)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    from universal_backtester.engine import LookaheadError, assert_causal
    from universal_backtester.validation import (bootstrap_sharpe_ci, deflated_sharpe_from_returns,
                                                 oos_stability_summary, sensitivity_verdict, walk_forward_windows)
    from ros.validation.portfolio import factor_fingerprint
    res = {}
    half = SPREAD_BPS / 1e4 / 2

    print("Card: ssrn_962461  (AS DRAFTED and approved at Gate A; nothing changed except where stated)")
    # ---------------- Stage 04: point-in-time inputs ------------------------------------------
    print("\n" + "=" * 100 + "\nSTAGE 04 -- POINT-IN-TIME INPUTS\n" + "=" * 100)
    px, adv, flag, names = load_panel()
    mc, ff = load_ff_mcap()
    mc = mc.reindex(index=px.index, columns=px.columns)
    ffm = mc * ff.reindex(px.columns).fillna(1.0)
    mem = top500_membership(adv, flag)
    first_flag = flag.any(axis=1).idxmax()
    print(f"Master: {px.shape[1]} securities, {px.index.min().date()} -> {px.index.max().date()}; "
          f"top-1000 flag first set {first_flag.date()} (card said ~2022-03-29; the October-2021 set covers "
          f"{OCT_2021_END.date()} to {(first_flag - pd.Timedelta(days=1)).date()} only)")
    ind = pd.read_csv(INDUSTRY)
    ind["sleeve"] = ind.apply(sleeve_of, axis=1)
    sl = ind.set_index("security_id")["sleeve"]
    ever = mem.columns[mem.any()]
    labelled = ind.set_index("security_id")["screener_industry"].reindex(ever).notna()
    print(f"Top-500 universe: {len(ever)} securities ever members; Screener industry label found for "
          f"{int(labelled.sum())}, missing for {int((~labelled).sum())} (no page today: delisted / merged / renamed)")
    tv_share = (adv.where(mem)[ever[~labelled.to_numpy()]].sum(axis=1) / adv.where(mem).sum(axis=1))
    print(f"  traded-value share of the top 500 held by unlabelled names: mean {tv_share.mean():.1%}, max {tv_share.max():.1%}")
    src = ind.get("label_source", pd.Series(index=ind.index, dtype=object)).fillna("fetched")
    src = src[ind["security_id"].isin(ever) & ind["screener_industry"].notna()]
    n_fetched, n_peer = int((src == "fetched").sum()), int(src.str.startswith("peer_table").sum())
    print(f"  of the labelled: {n_fetched} fetched from the company page, {n_peer} borrowed from a matching cached "
          f"peer table (scripts/ssrn_962461_peer_labels.py; leave-one-out agreement printed there)")
    unl = adv.where(mem)[ever[~labelled.to_numpy()]].mean().sort_values(ascending=False).head(15)
    print("  largest unlabelled names by mean traded value: " + ", ".join(names[s] for s in unl.index))
    res["industry_coverage"] = {"ever_members": int(len(ever)), "labelled": int(labelled.sum()),
                                "labelled_fetched": n_fetched, "labelled_peer_table": n_peer,
                                "unlabelled": int((~labelled).sum()), "unlabelled_tv_share_mean": float(tv_share.mean()),
                                "largest_unlabelled": [names[s] for s in unl.index]}
    mapping = (ind[ind["security_id"].isin(ever) & ind["sleeve"].notna()]
               .groupby(["sleeve", "screener_broad_industry", "screener_industry"]).size().rename("names").reset_index())
    mapping.to_csv(os.path.join(OUT, f"{SLUG}_sleeve_mapping.csv"), index=False)
    print("Industry -> sleeve mapping actually applied (names ever in the top 500):")
    print(mapping.to_string(index=False))

    nifty = load_nifty500()
    end = min(nifty.index.max(), px.index.max())
    cal_full = px.index
    mends = month_ends(cal_full)
    cal = cal_full[(cal_full >= OCT_2021_END) & (cal_full <= end)]
    print(f"Live window: {LIVE_START.date()} -> {end.date()} (NIFTY 500 workbook ends {nifty.index.max().date()}, "
          f"bhavcopy {px.index.max().date()}; the window ends at the last date both hold)")
    pv = px.ffill(limit=5).loc[cal]
    recon = [OCT_2021_END] + [d for d in trade_dates_for(mends, cal_full, 1, first_flag, end)
                              if d.month in (1, 4, 7, 10) and d >= first_flag]
    recon = pd.DatetimeIndex(sorted(set(recon)))
    nifty_lvl = nifty.reindex(cal).ffill()
    missing_n = int(nifty.reindex(cal).isna().sum())
    print(f"NIFTY 500 days missing on the bhavcopy calendar (carried forward): {missing_n}")

    def baskets(weight_base, members_mask, tagname):
        lv, dg = {}, []
        for s in SLEEVES[1:]:
            m = mem.loc[cal] & members_mask(s)
            lev, d, forced = build_basket(pv, weight_base, m, recon, NAME_CAP, half)
            lv[s] = lev
            d.insert(0, "sleeve", s)
            d["forced_exits_total"] = forced
            d["variant"] = tagname
            dg.append(d)
        return lv, pd.concat(dg, ignore_index=True)

    in_sleeve = lambda s: pd.Series(sl.reindex(px.columns).eq(s).to_numpy(), index=px.columns)  # noqa: E731
    lv_ff, diag_ff = baskets(ffm.loc[cal], in_sleeve, "free-float cap, 20% cap")
    lv_ew, diag_ew = baskets(None, in_sleeve, "equal weight")
    in_any = sl.reindex(px.columns).notna()
    exb, diag_exb, _ = build_basket(pv, ffm.loc[cal], mem.loc[cal] & ~in_any.to_numpy(), recon, NAME_CAP, half)
    diag_exb.insert(0, "sleeve", "Top 500 ex-basket (domestic)")
    diag_exb["variant"] = "free-float cap, 20% cap"
    bdiag = pd.concat([diag_ff, diag_ew, diag_exb], ignore_index=True)
    bdiag.to_csv(os.path.join(OUT, f"{SLUG}_basket_diagnostics.csv"), index=False)
    print("\nBasket reconstitutions (free-float, 20% cap): names held per sleeve, min / mean / max; max name weight")
    for s, g in diag_ff.groupby("sleeve"):
        print(f"  {s:20s} names {g['names'].min()}/{g['names'].mean():.0f}/{g['names'].max()}  "
              f"max weight {g['max_weight'].max():.0%}  members with no Screener mcap {g['members_without_weight'].max()}  "
              f"forced exits {g['forced_exits_total'].iloc[0]}  mean reconstitution trade {g['traded'].mean():.0%}")
    res["basket_names"] = {s: {"min": int(g["names"].min()), "mean": float(g["names"].mean()), "max": int(g["names"].max())}
                           for s, g in diag_ff.groupby("sleeve")}

    levels = pd.DataFrame({"NIFTY 500": nifty_lvl, **lv_ff})
    levels_ew = pd.DataFrame({"NIFTY 500": nifty_lvl, **lv_ew})
    levels_exb = levels.copy()
    levels_exb["NIFTY 500"] = exb       # the domestic sleeve replaced by the top 500 ex-basket
    levels.to_csv(os.path.join(OUT, f"{SLUG}_sleeve_levels.csv"))

    states = sma_states(levels, mends, SMA_MONTHS)
    sd = daily_from_monthly(states, cal)
    states.to_csv(os.path.join(OUT, f"{SLUG}_monthly_states.csv"))
    first_sig = states.index[(states.index >= pd.Timestamp("2022-08-01"))][0]
    tdates = trade_dates_for(mends, cal_full, TRADE_OFFSET, LIVE_START, end)
    print(f"\nFirst signal month-end {first_sig.date()}, first trade {tdates[0].date()}; {len(tdates)} monthly trade dates")

    # PIT tripwires
    print("\nLook-ahead tripwires:")
    rets_lv = levels.pct_change(fill_method=None)
    sh = sd.shift(1)  # what the engine sees (lag_days=0 + its own 1-day shift)
    try:
        assert_causal(sh, rets_lv, label="sleeve state")
        print("  PASS  sleeve state vs sleeve return[t], return[t+1]")
        res["tripwire_state"] = "PASS"
    except LookaheadError as e:
        print(f"  FAIL  {e}")
        res["tripwire_state"] = f"FAIL {e}"
    for label, planted in (("planted same-bar leak", rets_lv), ("planted next-bar leak", rets_lv.shift(-1))):
        try:
            assert_causal(planted, rets_lv, label=label)
            print(f"  BROKEN  negative control '{label}' was NOT caught")
            res[f"control_{label}"] = "NOT CAUGHT"
        except LookaheadError:
            print(f"  PASS  negative control '{label}' correctly caught")
            res[f"control_{label}"] = "caught"
    # truncation test: rebuild everything from data cut at a mid-window date; nothing before it may move
    cut = pd.Timestamp("2024-06-28")
    calc = cal[cal <= cut]
    mem_c = top500_membership(adv.loc[:cut], flag.loc[:cut])
    lv_c = {}
    for s in SLEEVES[1:]:
        lv_c[s], _, _ = build_basket(px.loc[:cut].ffill(limit=5).loc[calc], ffm.loc[calc],
                                     mem_c.loc[calc] & in_sleeve(s), [r for r in recon if r <= cut], NAME_CAP, half)
    lvc = pd.DataFrame({"NIFTY 500": nifty.loc[:cut].reindex(calc).ffill(), **lv_c})
    st_c = sma_states(lvc, mends[mends <= cut], SMA_MONTHS)
    lvl_diff = float((lvc - levels.loc[calc]).abs().max().max())
    st_diff = int((st_c != states.loc[st_c.index]).sum().sum())
    ok_trunc = lvl_diff < 1e-10 and st_diff == 0
    print(f"  {'PASS' if ok_trunc else 'FAIL'}  truncation test at {cut.date()}: max basket-level difference {lvl_diff:.2e}, "
          f"monthly states that change {st_diff}")
    res["truncation_test"] = {"cut": str(cut.date()), "max_level_diff": lvl_diff, "state_changes": st_diff, "pass": ok_trunc}

    # ---------------- Stage 05: the books --------------------------------------------------------
    print("\n" + "=" * 100 + "\nSTAGE 05 -- BUILD AND EXECUTE\n" + "=" * 100)
    A = SLEEVES
    r_main = run_book(levels, A, sd, tdates, name="MAIN 10-month switch, five sleeves")
    r_bh = run_book(levels, A, None, tdates, mode="fixed", fixed=[SLEEVE_W] * 5, name="Buy & Hold five sleeves")
    v_main, ret_main = live_slice(r_main.value, tdates[0], end)
    expo = float(r_main.weights.loc[v_main.index].sum(axis=1).mean())
    r_static = run_book(levels, A, None, tdates, mode="fixed", fixed=[SLEEVE_W * expo] * 5,
                        name=f"Static mix at {expo:.0%} exposure")
    # NIFTY 500 timed alone holds 100% when on
    from universal_backtester.engine import Backtester
    bt1 = Backtester(prices=levels[["NIFTY 500"]], assets=["NIFTY 500"], rf_daily=rf_series(cal, CASH_RATE),
                     spread_bps=SPREAD_BPS, lag_days=0, allow_cash=True)
    r_nt = bt1.run(allocator=SleeveSwitch(["NIFTY 500"], tdates, sleeve_weight=1.0), rebalance="daily",
                   alpha=sd[["NIFTY 500"]], name="NIFTY 500 timed alone")
    r_mand = run_book(levels, A, sd, tdates, mode="mandate", name="Mandate variant (off -> NIFTY 500)")
    r_ewb = run_book(levels_ew, A, daily_from_monthly(sma_states(levels_ew, mends, SMA_MONTHS), cal), tdates,
                     name="Equal-weight baskets")
    r_ewb_bh = run_book(levels_ew, A, None, tdates, mode="fixed", fixed=[SLEEVE_W] * 5, name="B&H, equal-weight baskets")
    r_exb = run_book(levels_exb, A, daily_from_monthly(sma_states(levels_exb, mends, SMA_MONTHS), cal), tdates,
                     name="Ex-basket domestic sleeve")
    r_exb_bh = run_book(levels_exb, A, None, tdates, mode="fixed", fixed=[SLEEVE_W] * 5, name="B&H, ex-basket domestic")

    books = {"MAIN 10-month switch, five sleeves": r_main, "Buy & Hold five sleeves": r_bh,
             f"Static mix at {expo:.0%} exposure": r_static, "NIFTY 500 timed alone": r_nt,
             "Mandate variant (off -> NIFTY 500)": r_mand, "Equal-weight baskets (switch)": r_ewb,
             "Equal-weight baskets (B&H)": r_ewb_bh, "Ex-basket domestic (switch)": r_exb,
             "Ex-basket domestic (B&H)": r_exb_bh}
    live = {k: live_slice(b.value, tdates[0], end) for k, b in books.items()}
    nv, nret = live_slice(nifty_lvl, tdates[0], end)
    rows = [stats(v, r, k) for k, (v, r) in live.items()] + [stats(nv, nret, "NIFTY 500")]
    for k, b in books.items():
        w = b.weights.loc[live[k][0].index]
        rr = next(x for x in rows if x["name"] == k)
        rr["avg_invested"] = float(w.sum(axis=1).mean())
        rr["ann_two_way_turnover_sleeve_level"] = float(b.turnover.loc[w.index].mean() * 252 * 2)
        rr["costs_paid_pct_nav"] = float(b.costs.loc[w.index].sum())
    summary = pd.DataFrame(rows)
    MAIN, BH, STATIC = "MAIN 10-month switch, five sleeves", "Buy & Hold five sleeves", f"Static mix at {expo:.0%} exposure"
    headline = summary[summary["name"].isin([MAIN, "NIFTY 500"])]
    appendix = summary[~summary["name"].isin([MAIN, "NIFTY 500"])]
    pd.set_option("display.width", 250)
    print(f"RESULTS, {v_main.index.min().date()} -> {v_main.index.max().date()} (costs inside every book; cash at 6%)")
    print(headline.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    print("\nAPPENDIX (must-beat comparators and variants; not the headline):")
    print(appendix.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    headline.to_csv(os.path.join(OUT, f"{SLUG}_comparison.csv"), index=False)
    appendix.to_csv(os.path.join(OUT, f"{SLUG}_comparators_appendix.csv"), index=False)
    res["comparison"] = headline.to_dict("records")
    res["comparators_appendix"] = appendix.to_dict("records")
    res["avg_exposure"] = expo

    # switches and holdings
    wm = r_main.weights.loc[v_main.index]
    st_live = states.loc[(states.index >= first_sig) & (states.index < end)]
    switches = int((st_live.diff().abs() > 0).sum().sum())
    print(f"\nMAIN: average invested {expo:.1%}; sleeve switches over the window: {switches} "
          f"({len(st_live)} monthly signals x 5 sleeves); months all five off: {int((st_live.sum(axis=1) == 0).sum())}, "
          f"all five on: {int((st_live.sum(axis=1) == 5).sum())}")
    res["switches"] = switches
    res["n_monthly_signals"] = int(len(st_live))
    res["months_all_off"] = int((st_live.sum(axis=1) == 0).sum())
    res["months_all_on"] = int((st_live.sum(axis=1) == 5).sum())
    mw = wm.loc[wm.index.isin(tdates)].copy()
    mw["cash"] = 1 - mw.sum(axis=1)
    mw.to_csv(os.path.join(OUT, f"{SLUG}_holdings_monthly.csv"))

    # basket internal trading, weighted by what the book held
    btrade = 0.0
    for s in SLEEVES[1:]:
        g = diag_ff[(diag_ff["sleeve"] == s)]
        for _, row in g.iterrows():
            d = pd.Timestamp(row["date"])
            if d in wm.index and np.isfinite(row["traded"]):
                btrade += float(wm.at[d, s]) * float(row["traded"])
    yrs = (v_main.index[-1] - v_main.index[0]).days / 365.25
    ann_to = float(r_main.turnover.loc[v_main.index].mean() * 252 * 2) + btrade / yrs
    print(f"  annual two-way turnover incl. trades inside baskets: {ann_to:.0%}")
    res["annual_turnover_incl_baskets"] = ann_to

    # sleeve correlations
    cr = levels.loc[v_main.index].pct_change(fill_method=None).corr()
    cr_x = levels_exb.loc[v_main.index].pct_change(fill_method=None).corr()
    cr_x.index = cr_x.columns = ["Top 500 ex-basket"] + SLEEVES[1:]
    cr.to_csv(os.path.join(OUT, f"{SLUG}_sleeve_correlation.csv"))
    cr_x.to_csv(os.path.join(OUT, f"{SLUG}_sleeve_correlation_exbasket.csv"))
    off = cr.where(~np.eye(5, dtype=bool)).stack()
    print(f"\nSleeve correlation (daily, live window): pairwise min {off.min():.2f}, mean {off.mean():.2f}, max {off.max():.2f}")
    print(cr.round(2).to_string())
    offx = cr_x.where(~np.eye(5, dtype=bool)).stack()
    print(f"  ex-basket domestic version: pairwise min {offx.min():.2f}, mean {offx.mean():.2f}, max {offx.max():.2f}")
    res["sleeve_corr"] = {"min": float(off.min()), "mean": float(off.mean()), "max": float(off.max()),
                          "exbasket_mean": float(offx.mean())}

    # ---------------- Stage 06: research validation ----------------------------------------------
    print("\n" + "=" * 100 + "\nSTAGE 06 -- RESEARCH VALIDATION (code computes; nothing below is estimated by hand)\n" + "=" * 100)
    rf = rf_series(v_main.index, CASH_RATE)
    boot = bootstrap_sharpe_ci(ret_main, block_size=BLOCK, n_resamples=a.n_boot, rf_daily=rf, seed=0)
    print(f"  MAIN Sharpe over 6% cash, 90% block-bootstrap CI (block {BLOCK} days): [{boot.ci_low:.2f}, {boot.ci_high:.2f}] "
          f"point {boot.point_estimate:.2f}, {boot.fraction_positive:.0%} of resamples positive")
    res["bootstrap_main"] = {"ci_low": boot.ci_low, "ci_high": boot.ci_high, "point": boot.point_estimate,
                             "frac_positive": boot.fraction_positive}
    paired = {}
    for lab in (BH, STATIC, "NIFTY 500 timed alone"):
        d = (ret_main - live[lab][1]).fillna(0.0)
        b = bootstrap_sharpe_ci(d, block_size=BLOCK, n_resamples=a.n_boot, seed=0)
        paired[lab] = {"ci_low": b.ci_low, "ci_high": b.ci_high, "point": b.point_estimate, "p_not_positive": 1 - b.fraction_positive}
        print(f"  PAIRED MAIN minus {lab}: Sharpe of the difference [{b.ci_low:.2f}, {b.ci_high:.2f}] point {b.point_estimate:.2f}, "
              f"P(<=0) {1 - b.fraction_positive:.3f}")
    bn = bootstrap_sharpe_ci((ret_main - nret.reindex(ret_main.index).fillna(0.0)), block_size=BLOCK, n_resamples=a.n_boot, seed=0)
    paired["NIFTY 500"] = {"ci_low": bn.ci_low, "ci_high": bn.ci_high, "point": bn.point_estimate, "p_not_positive": 1 - bn.fraction_positive}
    print(f"  PAIRED MAIN minus NIFTY 500: [{bn.ci_low:.2f}, {bn.ci_high:.2f}] point {bn.point_estimate:.2f}, P(<=0) {1 - bn.fraction_positive:.3f}")
    res["paired"] = paired
    # drawdown difference bootstrap: is the drawdown reduction vs Buy & Hold more than resampling noise?
    rng = np.random.default_rng(0)
    rb = live[BH][1].to_numpy()
    rm = ret_main.to_numpy()
    n = len(rm)
    dd_diff = []
    for _ in range(a.n_boot):
        starts = rng.integers(0, n - BLOCK + 1, size=int(np.ceil(n / BLOCK)))
        ix = np.concatenate([np.arange(s, s + BLOCK) for s in starts])[:n]
        vm, vb = np.cumprod(1 + rm[ix]), np.cumprod(1 + rb[ix])
        dd_diff.append(float((1 - vb / np.maximum.accumulate(vb)).max() - (1 - vm / np.maximum.accumulate(vm)).max()))
    dd_diff = np.array(dd_diff)
    res["dd_reduction_vs_bh_bootstrap"] = {"ci_low": float(np.percentile(dd_diff, 5)), "ci_high": float(np.percentile(dd_diff, 95)),
                                           "p_not_positive": float((dd_diff <= 0).mean())}
    print(f"  Max-drawdown reduction vs Buy & Hold (B&H DD minus MAIN DD), paired block bootstrap 90% CI: "
          f"[{np.percentile(dd_diff, 5):.1%}, {np.percentile(dd_diff, 95):.1%}], P(<=0) {(dd_diff <= 0).mean():.3f}")

    dsr = deflated_sharpe_from_returns(ret_main, n_trials=N_CONFIGS_TRIED, trial_sharpe_std=0.3, rf_daily=rf)
    print(f"  Deflated Sharpe probability (n_trials={N_CONFIGS_TRIED}, the card's floor; excess of 6% cash): {dsr:.2f}")
    res["deflated_sharpe"] = float(dsr)

    windows = walk_forward_windows(v_main.index, n_folds=4, min_train_years=1.0)
    oos = oos_stability_summary(v_main, ret_main, windows, rf_daily=rf, min_obs=60)
    oos_bh = oos_stability_summary(live[BH][0], live[BH][1], windows, rf_daily=rf, min_obs=60)
    oos_n = oos_stability_summary(nv, nret, windows, rf_daily=rf, min_obs=60)
    oos = oos.assign(bh_sharpe=oos_bh["sharpe"].to_numpy(), bh_max_dd=oos_bh["max_dd"].to_numpy(),
                     nifty_sharpe=oos_n["sharpe"].to_numpy(), nifty_max_dd=oos_n["max_dd"].to_numpy())
    print("\n  WALK-FORWARD (anchored windows; Sharpe over 6% cash; the rule has no fitted parameter, so these are sub-periods):")
    print(oos.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    oos.to_csv(os.path.join(OUT, f"{SLUG}_oos_stability.csv"), index=False)

    def bundle(levels_, st_, tds, spread=SPREAD_BPS, rate=CASH_RATE, offset=TRADE_OFFSET):
        m = run_book(levels_, A, st_, tds, spread=spread, rate=rate, offset=offset)
        b = run_book(levels_, A, None, tds, spread=spread, rate=rate, mode="fixed", fixed=[SLEEVE_W] * 5)
        vm, rm_ = live_slice(m.value, tdates[0], end)
        vb, rb_ = live_slice(b.value, tdates[0], end)
        e = float(m.weights.loc[vm.index].sum(axis=1).mean())
        s = run_book(levels_, A, None, tds, spread=spread, rate=rate, mode="fixed", fixed=[SLEEVE_W * e] * 5)
        vs, rs = live_slice(s.value, tdates[0], end)
        sm, sb, ss = stats(vm, rm_, "m", rate), stats(vb, rb_, "b", rate), stats(vs, rs, "s", rate)
        return {"cagr": sm["cagr"], "vol": sm["vol"], "sharpe_excess": sm["sharpe_excess_daily"], "max_dd": sm["max_dd"],
                "avg_invested": e, "bh_cagr": sb["cagr"], "bh_sharpe_excess": sb["sharpe_excess_daily"], "bh_max_dd": sb["max_dd"],
                "static_sharpe_excess": ss["sharpe_excess_daily"], "static_max_dd": ss["max_dd"],
                "cagr_minus_bh": sm["cagr"] - sb["cagr"], "sharpe_minus_bh": sm["sharpe_excess_daily"] - sb["sharpe_excess_daily"],
                "sharpe_minus_static": sm["sharpe_excess_daily"] - ss["sharpe_excess_daily"],
                "dd_ratio_to_bh": sm["max_dd"] / sb["max_dd"]}

    print("\n  SMA LENGTH SENSITIVITY (base case 10 months, the paper's rule; each counted in n_configs_tried):")
    rows = []
    for mo, inc in ((6, True), (8, True), (10, True), (12, True), (10, False)):
        st = daily_from_monthly(sma_states(levels, mends, mo, include_current=inc), cal)
        rows.append({"sma_months": mo, "includes_current": inc, **bundle(levels, st, tdates)})
    sma_sw = pd.DataFrame(rows)
    print(sma_sw.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    sw_for_verdict = sma_sw[sma_sw["includes_current"]].rename(columns={"sharpe_excess": "sharpe"})
    verdict = sensitivity_verdict(sw_for_verdict, 10, "sma_months")
    print("  " + verdict)
    sma_sw.to_csv(os.path.join(OUT, f"{SLUG}_sensitivity_sma.csv"), index=False)
    res["sma_sensitivity"] = sma_sw.to_dict("records")
    res["sma_verdict"] = verdict

    print("\n  CASH-RATE SWEEP (the declared 6% proxy, swept 4-8%):")
    cash_sw = pd.DataFrame([{"cash_rate": rt, **bundle(levels, sd, tdates, rate=rt)} for rt in (0.04, 0.05, 0.06, 0.07, 0.08)])
    print(cash_sw.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    cash_sw.to_csv(os.path.join(OUT, f"{SLUG}_cash_sweep.csv"), index=False)
    res["cash_sweep"] = cash_sw.to_dict("records")

    print("\n  COST SWEEP (sleeve-level round trip; trades inside baskets stay at 30bp):")
    cost_sw = pd.DataFrame([{"round_trip_bps": c, **bundle(levels, sd, tdates, spread=c)} for c in (0, 30, 60, 90, 150)])
    print(cost_sw.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    cost_sw.to_csv(os.path.join(OUT, f"{SLUG}_cost_sweep.csv"), index=False)
    res["cost_sweep"] = cost_sw.to_dict("records")
    f = lambda c: bundle(levels, sd, tdates, spread=c)["sharpe_minus_bh"]  # noqa: E731
    lo_c, hi_c = 0.0, 2000.0
    if f(lo_c) <= 0:
        be = "none: below Buy & Hold even at zero cost"
    elif f(hi_c) > 0:
        be = "> 2000bp"
    else:
        for _ in range(25):
            mid = (lo_c + hi_c) / 2
            lo_c, hi_c = (mid, hi_c) if f(mid) > 0 else (lo_c, mid)
        be = f"{(lo_c + hi_c) / 2:.0f}bp"
    print(f"  Break-even round-trip cost (switch's excess Sharpe = Buy & Hold's): {be}")
    res["break_even_cost"] = be

    print("\n  TRADE-DAY SENSITIVITY (0 = paper's same close, a diagnostic only; 1 = card; 5, 10 = later):")
    rows = []
    for off_ in (0, 1, 5, 10):
        td = trade_dates_for(mends, cal_full, off_, first_sig, end)
        rows.append({"trade_offset_days": off_, **bundle(levels, sd, td, offset=off_)})
    lag_sw = pd.DataFrame(rows)
    print(lag_sw.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    lag_sw.to_csv(os.path.join(OUT, f"{SLUG}_trade_day_sensitivity.csv"), index=False)
    res["trade_day_sensitivity"] = lag_sw.to_dict("records")

    # ---------------- Stage 07: portfolio validation ---------------------------------------------
    print("\n" + "=" * 100 + "\nSTAGE 07 -- PORTFOLIO VALIDATION\n" + "=" * 100)
    fr = pd.DataFrame({"NIFTY 500": nret.reindex(ret_main.index).fillna(0.0), "Buy & Hold five sleeves": live[BH][1]})
    fp = factor_fingerprint(ret_main, fr, rf_daily=rf)
    if "error" in fp:
        print(f"  factor fingerprint unavailable: {fp['error']}")
    else:
        print(f"  FACTOR FINGERPRINT vs NIFTY 500 and the Buy & Hold sleeves (the fund's own permitted series; the "
              f"NSE factor sleeves are outside this run's sources):")
        print(f"    alpha (ann.) {fp['alpha_ann']:.2%}   alpha t (HAC) {fp['alpha_t_hac']:.2f}   R^2 {fp['r_squared']:.2f}   n {fp['n_obs']}")
        print(f"    loadings: {fp['loadings']}")
        print(f"    {fp.get('interpretation', '')}")
        res["factor_fingerprint"] = {k: fp[k] for k in ("alpha_ann", "alpha_t_hac", "r_squared", "n_obs", "loadings") if k in fp}
    corr_n = float(np.corrcoef(ret_main, nret.reindex(ret_main.index).fillna(0.0))[0, 1])
    print(f"  correlation of daily returns with NIFTY 500: {corr_n:.2f}; with Buy & Hold sleeves: "
          f"{float(np.corrcoef(ret_main, live[BH][1])[0, 1]):.2f}")
    res["corr_to_nifty500"] = corr_n

    if not a.no_charts:
        try:
            from universal_backtester.clean_charts import save_clean_charts
            charts = save_clean_charts(
                v_main, nv, outdir=os.path.join(OUT, "charts"), tag=SLUG,
                strategy_name="10-month switch, five sleeves", benchmark_name="NIFTY 500",
                weights=wm, sleeve=live[BH][0], sleeve_name="Buy & Hold, same five sleeves",
                footnote="Price return (no dividends) for every sleeve and NIFTY 500; cash earns a flat 6%. 30bp round trip charged.")
            res["charts"] = [os.path.relpath(c, REPO).replace("\\", "/") for c in charts]
            print("  charts:", *res["charts"], sep="\n    ")
        except Exception as e:  # charts are a convenience; never fail the run on them
            print(f"  charts skipped: {e!r}")

    # ---------------- Gate B inputs, judged by the repo's own gate_b() ---------------------------
    from ros.cards.schema import load_card
    from ros.governance.gates import gate_b
    research = {"deflated_sharpe": {"deflated_sharpe_prob": float(dsr),
                                    "interpretation": f"n_trials={N_CONFIGS_TRIED} (the card's floor), trial Sharpe std 0.3, excess of 6% cash"},
                "oos_min_sharpe": float(oos["sharpe"].min()) if not oos.empty else None,
                "bootstrap_p_not_positive": float(paired["NIFTY 500"]["p_not_positive"])}
    avg_cash = 1 - expo
    portfolio = {"alpha_t_hac": (float(fp["alpha_t_hac"]) if "error" not in fp else None),
                 "annual_turnover": ann_to,
                 "mandate": {"passes": avg_cash < 1e-6,
                             "violations": ([f"holds cash {avg_cash:.0%} of the time on average; card portfolio.mandate_allow_cash is false "
                                             f"(the fully invested variant is in the appendix)"] if avg_cash >= 1e-6 else [])}}
    gb = gate_b(load_card(CARD), research, portfolio)
    print("\n" + "=" * 100)
    print("GATE B CRITERIA, as the repo's own gate_b() computes them from this run (decision stays PENDING)")
    print(f"  paired test for 'advantage over benchmark': MAIN minus NIFTY 500 (price-return), "
          f"P(Sharpe difference <= 0) = {paired['NIFTY 500']['p_not_positive']:.3f}")
    print("=" * 100)
    print(gb.render())
    res["gate_b"] = gb.to_dict()
    res["gate_b_inputs"] = {"research": research, "portfolio": portfolio}

    dr = pd.DataFrame({"strategy": ret_main, "benchmark": nret.reindex(ret_main.index).fillna(0.0), "sleeve": live[BH][1]})
    dr.index.name = "date"
    dr.to_csv(os.path.join(OUT, f"{SLUG}_daily_returns.csv"))
    json.dump(res, open(os.path.join(OUT, f"{SLUG}_results.json"), "w", encoding="utf-8"), indent=1, default=str)
    print(f"\nResults written to {OUT} ({SLUG}_*). Gate B is a human decision and is NOT assigned by this script.")
    print("\nGATE B: decision PENDING. To record a decision, a named human runs:")
    print('  python run_pipeline.py --card cards/ssrn_962461.yaml --decision <APPROVE|OBSERVE|FIX|REJECT> '
          '--decided-by "<name>" --rationale "<why>"')


if __name__ == "__main__":
    main()
