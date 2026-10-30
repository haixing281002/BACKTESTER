"""Steps 04 to 07 for cards/oceanofpdf_com_stocks_on_the_move_andreas_clenow.yaml (Gate A rerun 2, 2026-10-16).

Clenow's "Stocks on the Move" ranking, held as a plain monthly top-20, 5% each, long only, GROSS (0bp everywhere).
Data: NSE bhavcopy from cache/ (nothing fetched), the corporate-action event list in the run folder, the OFFICIAL
NSE NIFTY 500 membership file data/raw/nifty500/nifty500_membership.csv, and the NIFTY 500 workbook for the benchmark.

MAIN       last trading day of each month d: score every list member (point-in-time OFFICIAL NIFTY 500, see
           data/raw/nifty500/nifty500_membership.csv) on d's close by exp(slope*250)-1 times R^2 of an OLS fit of ln(adj close) on day
           number over 120 trading days; rule out close < 100-day average and any one-day move > 15% in the last
           120 days; hold the first 20 left walking down the full ranking, 5% each, whole shares, Rs 10 crore start.
           EVERY trade is at THAT SAME close d; the new book earns returns from d+1. No position earns a return on or
           before the close it was chosen at, so it is causal. First book: 2022-04-29 close. Last rebalance
           2026-08-31 close; tracked to 2026-09-18.
Fills      a held name with no bhavcopy row at d: the sale carries to its next traded close. A purchase is only ever
           made in a name that has a close at d (it is ranked on it), so a slot passes to the next eligible name.
Cash       earns 0% everywhere. Costs: none. No cost book, no cost sweep.
Checks     the churn checks run FIRST and must all pass before any performance number is printed.
           `--checks-only` stops after them.
Variants   rebalance on trading day 1, 6, 11, 16 (own signal day close, same-close fills); 20% jump limit; medium/low
           confidence SPLIT/BONUS rows treated as REAL.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from ros.validation.portfolio import factor_fingerprint
from universal_backtester.data import load_banner_workbook
from universal_backtester.metrics import ann_vol as _ann_vol
from universal_backtester.metrics import cagr as _cagr
from universal_backtester.metrics import max_drawdown as _mdd
from universal_backtester.validation import (
    bootstrap_sharpe_ci,
    deflated_sharpe_from_returns,
    oos_stability_summary,
    walk_forward_windows,
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(REPO, "cache")
INDEX_PATH = os.path.join(REPO, "data", "raw", "NSE_Broad_Factor_Indices_Historical_Data.xlsx")
CARD = os.path.join(REPO, "cards", "oceanofpdf_com_stocks_on_the_move_andreas_clenow.yaml")
# The run folder the hand-off files go to. CLENOW_RUN selects it; the default is the run that holds the published
# results (20261021-104144-801e, a rerun of 20261016-102923-bdc1). A run folder without scratch/all_raw.pkl rebuilds
# the panel from cache/, which is deterministic, so the numbers do not depend on which folder is chosen.
RUN = os.environ.get("CLENOW_RUN", os.path.join(REPO, "outputs", "lightyear", "20261021-104144-801e"))
# The signed-off corporate-action list (operator, 2026-10-21), kept under data/processed/ as a declared input
# rather than read from a gitignored run folder. CA_EVENTS overrides it; its sha256 goes into manifest.json.
EVENTS = os.environ.get("CA_EVENTS", os.path.join(REPO, "data", "processed", "corporate_actions",
                                                  "corporate_action_events_20261021.csv"))
# HARDCODED (operator, 2026-10-21): the repo's official NIFTY 500 membership file,
# data/raw/nifty500/nifty500_membership.csv, read through ros.data.nifty500. Rebuilt from NSE's month-end
# constituent files, IndexInclExcl.xls and every NSE Indices press release, checked against 128 NSE snapshots.
# A change effective on a month-end day is already in force at that day's close, so that rebalance ranks the
# NEW list. Replaces the run-folder file nifty500_pit_official.csv used by rerun 3 (and the Accord proxy before it).
from ros.data import nifty500 as N500

SCRATCH = os.path.join(RUN, "scratch")
# The bhavcopy panel cache (all_raw.pkl). CLENOW_PANEL_CACHE lets a rerun reuse the original run's cache so
# the prices are identical and only the universe changes.
PANEL_CACHE = os.environ.get("CLENOW_PANEL_CACHE", os.path.join(SCRATCH, "all_raw.pkl"))
OUT = os.environ.get("CLENOW_OUT", os.path.join(REPO, "outputs"))   # summary tables and charts; a rerun keeps its own
SLUG = "oceanofpdf_com_stocks_on_the_move_andreas_clenow"

FIRST_SIGNAL = pd.Timestamp("2022-04-29")
SAMPLE_END = pd.Timestamp("2026-09-18")
WINDOW, MA, JUMP = 120, 100, 0.15
N_HOLD = 20
START_NAV = 1e8
RF_ANNUAL = 0.06             # the fund's hurdle, used only inside Sharpe-type statistics. Cash earns 0%.
RF_D = (1 + RF_ANNUAL) ** (1 / 252) - 1
N_CONFIGS_CARD = 8           # the card's own count (a floor)
BLOCK = 21
MIN_VALID = 110              # of the 120 window days a stock needs a price on
SUSPEND_DAYS = 3             # consecutive market days with no price = suspended / delisted -> sold at last price
NAMES = {}


# ------------------------------------------------------------------ data (step 04) ------------------------
def build_panel():
    pk = PANEL_CACHE
    if os.path.exists(pk):
        raw = pd.read_pickle(pk)
    else:
        import glob
        raw = pd.concat([pd.read_pickle(f)[["DATE", "SYMBOL", "SERIES", "ISIN", "CLOSE", "VAL", "QTY"]]
                         for f in sorted(glob.glob(os.path.join(CACHE, "20*.pkl")))])
        raw.to_pickle(pk)
    raw = raw[raw["SERIES"].isin(["EQ", "BE", "BZ"]) & raw["ISIN"].notna() & raw["ISIN"].str.startswith("INE")]
    raw = raw.sort_values(["DATE", "ISIN", "VAL"]).drop_duplicates(["DATE", "ISIN"], keep="last")
    s = raw.sort_values(["SYMBOL", "DATE"]).reset_index(drop=True)
    prev_sym, prev_isin, prev_date = s["SYMBOL"].shift(), s["ISIN"].shift(), s["DATE"].shift()
    # same symbol, ISIN changes, old ISIN was trading within a week before: one security (a split or bonus
    # re-issued its ISIN). A longer gap is a symbol re-used by a different company and is not linked.
    chg = (s["SYMBOL"] == prev_sym) & (s["ISIN"] != prev_isin) & ((s["DATE"] - prev_date).dt.days <= 7)
    link = dict(zip(prev_isin[chg], s.loc[chg, "ISIN"]))

    def root(i):
        seen = 0
        while i in link and seen < 10:
            i = link[i]; seen += 1
        return i

    raw["ID"] = raw["ISIN"].map(root)
    raw = raw.sort_values(["DATE", "ID", "VAL"]).drop_duplicates(["DATE", "ID"], keep="last")
    close = raw.pivot(index="DATE", columns="ID", values="CLOSE").sort_index()
    val_cr = raw.pivot(index="DATE", columns="ID", values="VAL").reindex(close.index) / 1e7
    names = raw.sort_values("DATE").drop_duplicates("ID", keep="last").set_index("ID")["SYMBOL"].to_dict()
    ev_all = pd.read_csv(EVENTS, parse_dates=["date"])        # re-read from disk: the corrected file (PFC, NMDC)
    ev_all["ID"] = ev_all["isin"].map(root)
    ev = ev_all[ev_all["label"].isin(["SPLIT/BONUS", "DEMERGER"])].copy()
    ev = ev[ev["adjust_factor"].notna() & (ev["adjust_factor"] != 1.0)]
    return close, val_cr, names, ev, ev_all, root, len(link)


def apply_events(close, ev, upto=None, skip_medium_low_splitbonus=False):
    """Back-adjust the close for each event: every price BEFORE the ex-date is multiplied by the factor."""
    adj = close.copy()
    n = 0
    for _, e in ev.iterrows():
        if upto is not None and e["date"] > upto:
            continue
        if skip_medium_low_splitbonus and e["label"] == "SPLIT/BONUS" and e["confidence"] in ("medium", "low"):
            continue
        if e["ID"] in adj.columns:
            adj.loc[adj.index < e["date"], e["ID"]] *= float(e["adjust_factor"])
            n += 1
    return adj, n


class Membership:
    """Point-in-time OFFICIAL NIFTY 500: the list in effect on a date, as ISIN roots present in the panel."""

    def __init__(self, root, columns):
        m = N500.load_membership()                       # regular members only (no demerger placeholders)
        cuts = [d for d in N500.change_dates(m) if d >= N500.FIRST_DATE] + [pd.Timestamp("2099-12-31")]
        self.periods = []
        self.missing = 0
        cols = set(columns)
        for ef, nxt in zip(cuts[:-1], cuts[1:]):
            g = N500.members_on(ef, m)
            g_ids = pd.Index(g["isin"].map(root).unique())
            ids = [i for i in g_ids if i in cols]
            if nxt > FIRST_SIGNAL - pd.Timedelta(days=40):
                self.missing += len(g_ids) - len(ids)
            # (effective_from, effective_to inclusive, members, the date this list took effect)
            self.periods.append((ef, nxt - pd.Timedelta(days=1), pd.Index(ids), ef))
        self.periods.sort(key=lambda x: x[0])

    def on(self, d):
        for ef, et, ids, lf in self.periods:
            if ef <= d <= et:
                return ids
        return pd.Index([])

    def list_date(self, d):
        for ef, et, ids, lf in self.periods:
            if ef <= d <= et:
                return lf
        return None


def first_positions(adj):
    v = adj.notna().values
    return np.where(v.any(axis=0), v.argmax(axis=0), 10 ** 9)


def signals_at(adj, i, jump=JUMP, firstpos=None):
    """Score every stock using prices up to and including row i (the signal close) only."""
    if firstpos is None:
        firstpos = first_positions(adj.iloc[: i + 1])
    w = adj.iloc[i - WINDOW + 1: i + 1]
    x = np.arange(WINDOW, dtype=float)
    lw = np.log(w.values)
    ok = ~np.isnan(lw)
    n = ok.sum(axis=0)
    xm = np.where(ok, x[:, None], 0.0)
    ym = np.where(ok, lw, 0.0)
    sx, sy = xm.sum(0), ym.sum(0)
    with np.errstate(all="ignore"):
        mx, my = sx / n, sy / n
        dx = np.where(ok, x[:, None] - mx, 0.0)
        dy = np.where(ok, lw - my, 0.0)
        sxx, syy, sxy = (dx * dx).sum(0), (dy * dy).sum(0), (dx * dy).sum(0)
        slope = sxy / sxx
        r2 = sxy ** 2 / (sxx * syy)
        ann = np.exp(slope) ** 250 - 1.0
        score = ann * r2
    have_last = ok[-1]
    ma = w.iloc[-MA:].mean(skipna=True).values
    below = w.iloc[-1].values < ma
    wf = w.ffill()
    ret = wf.pct_change(fill_method=None).iloc[1:]
    big = (ret.abs() > jump).any().values
    history = firstpos <= (i - WINDOW + 1)               # at least 120 trading days of the stock's own prices
    ranked = have_last & history & (n >= MIN_VALID) & np.isfinite(score)
    elig = ranked & ~below & ~big
    # explanation only (does not feed the ranking or the filters): how far from the 100-day average, and the
    # single largest one-day move in the window with its date -- both scale-free, so unaffected by adjustments
    with np.errstate(all="ignore"):
        pct_vs_ma = w.iloc[-1].values / ma - 1.0
    absr = ret.abs().fillna(-1.0).values
    pos = absr.argmax(axis=0)
    has_move = absr.max(axis=0) >= 0
    max_move = np.where(has_move, ret.values[pos, np.arange(ret.shape[1])], np.nan)
    max_move_date = pd.Series(ret.index[pos], index=adj.columns).where(has_move)
    return pd.DataFrame({"score": score, "ann_slope": ann, "r2": r2, "ranked": ranked, "below_ma": below,
                         "jump": big, "eligible": elig, "pct_vs_ma": pct_vs_ma, "max_move": max_move,
                         "max_move_date": max_move_date.values}, index=adj.columns)


def explain(action, r, member, cutoff, slot, jump):
    """One plain sentence: why this name was bought, kept, sold, skipped or not needed at this rebalance."""
    lim = f"{jump:.0%}"
    if r is None:
        why_out = "it left the NIFTY 500 list" if not member else "it could not be scored (no price or under 120 days of history)"
        return f"SOLD: {why_out}." if action.startswith("SELL") else f"Not scored: {why_out}."
    rk, sc, an, r2 = int(r["rank"]), r["score"], r["ann_slope"], r["r2"]
    pm, mm, md = r["pct_vs_ma"], r["max_move"], r["max_move_date"]
    mdt = pd.Timestamp(md).date() if pd.notna(md) else "-"
    stats = f"score {sc:.2f} = slope {an:+.0%} a year x R-squared {r2:.2f}"
    fails = []
    if r["below_ma"]:
        fails.append(f"closed {pm:+.1%} versus its 100-day average (must be above it)")
    if r["jump"]:
        fails.append(f"had a {mm:+.1%} one-day move on {mdt} (limit {lim})")
    if action == "BUY":
        return (f"BOUGHT: rank {rk}, eligible pick no. {slot} of 20; {stats}; {pm:+.1%} above its 100-day average; "
                f"biggest one-day move in 120 days {mm:+.1%} (limit {lim}).")
    if action == "KEEP":
        return f"KEPT: still an eligible top-20 pick (rank {rk}, pick no. {slot}); {stats}; traded back to 5%."
    if action.startswith("SELL"):
        carried = " The sale waited for the next day it traded." if "carried" in action else ""
        if not member:
            return f"SOLD: it left the NIFTY 500 list.{carried}"
        if fails:
            return f"SOLD: it {' and '.join(fails)}.{carried}"
        return (f"SOLD: fell to rank {rk}; enough eligible names ranked above it to fill all 20 slots "
                f"(the 20th pick was rank {cutoff}).{carried}")
    if fails:
        return f"SKIPPED: rank {rk} but it {' and '.join(fails)}."
    if cutoff is not None and rk > cutoff:
        return f"NOT NEEDED: eligible (rank {rk}), but the 20 slots were filled by higher-ranked names (20th pick was rank {cutoff})."
    return f"SKIPPED: rank {rk}, eligible, but it did not trade at the signal close."


def rank_table(sg, members):
    sg = sg[sg.index.isin(members) & sg["ranked"].values].copy()
    sg["isin"] = sg.index
    sg = sg.sort_values(["score", "isin"], ascending=[False, True])
    sg["rank"] = np.arange(1, len(sg) + 1)
    return sg


def signal_dates(index, mode):
    """mode 'ME' = last trading day of month; int k = k-th trading day of the month. First >= FIRST_SIGNAL."""
    s = pd.Series(index, index=index)
    g = s.groupby([index.year, index.month])
    d = g.last() if mode == "ME" else g.nth(mode - 1)
    d = pd.DatetimeIndex(pd.Series(d.values).values)
    return d[(d >= FIRST_SIGNAL) & (d <= SAMPLE_END)]


# ------------------------------------------------------------------ simulator (step 05) -------------------
def simulate(adj, rawpx, val20, mem, sigdates, firstpos, jump=JUMP):
    """Rank on day d's close and trade at that same close d. Gross: no cost anywhere."""
    idx = adj.index
    px, rp = adj.values, rawpx.values
    cols = adj.columns
    colpos = {c: j for j, c in enumerate(cols)}
    sigset = set(sigdates)
    start = idx.get_loc(min(sigset))
    end = idx.get_loc(SAMPLE_END)
    cash = START_NAV
    units = {}                      # col index -> units, valued at the adjusted close (real shares = units * adj/raw)
    last_px, miss, pending = {}, {}, set()
    nav, cashw, contrib = {}, {}, {}
    buys_val = sells_val = 0.0
    recs, ledger, trades, suspensions = [], [], [], []

    def val_of(j, t):
        p = px[t][j]
        return units[j] * (p if not np.isnan(p) else last_px[j])

    for t in range(start, end + 1):
        d = idx[t]
        row, rrow = px[t], rp[t]
        if t > start:      # positions held from the prior close earn today's move
            for j in units:
                if not np.isnan(row[j]) and j in last_px:
                    contrib[j] = contrib.get(j, 0.0) + units[j] * (row[j] - last_px[j])
        for j in list(units):
            p = row[j]
            if np.isnan(p):
                miss[j] = miss.get(j, 0) + 1
                if miss[j] >= SUSPEND_DAYS:
                    proceeds = units[j] * last_px[j]
                    cash += proceeds; sells_val += proceeds
                    suspensions.append({"date": d, "id": cols[j], "proceeds": proceeds})
                    trades.append((d, cols[j], "SELL", proceeds, np.nan, "suspended or delisted: sold at last traded price"))
                    del units[j]; pending.discard(j); miss.pop(j, None)
            else:
                miss[j] = 0
                last_px[j] = p
        for j in list(pending):      # a sale that could not trade at the signal close goes at the next traded close
            if j in units and not np.isnan(row[j]):
                proceeds = units[j] * row[j]
                cash += proceeds; sells_val += proceeds
                trades.append((d, cols[j], "SELL", proceeds, rrow[j], "carried sell"))
                del units[j]; pending.discard(j)
        if d in sigset:
            members = mem.on(d)
            sg_all = signals_at(adj, t, jump, firstpos)
            sg = rank_table(sg_all, members)
            elig = sg[sg["eligible"]]
            target, skipped = [], []
            for c in elig.index:        # walk down the ranking; a slot passes to the next eligible name
                j = colpos[c]
                if np.isnan(row[j]) or np.isnan(rrow[j]):
                    skipped.append(c); continue
                target.append(j)
                if len(target) == N_HOLD:
                    break
            held_before = set(units)
            nav_before = cash + sum(val_of(j, t) for j in units)
            w_before = {j: val_of(j, t) / nav_before for j in units}
            shares_before = {j: units[j] * row[j] / rrow[j] if not np.isnan(rrow[j]) else np.nan for j in units}
            slot = nav_before / N_HOLD
            tset = set(target)
            actions = {}
            for j in list(units):
                if j not in tset:
                    if np.isnan(row[j]):
                        pending.add(j); actions[j] = "SELL (carried: cannot trade today)"; continue
                    proceeds = units[j] * row[j]
                    cash += proceeds; sells_val += proceeds
                    trades.append((d, cols[j], "SELL", proceeds, rrow[j], "not in the new top 20"))
                    actions[j] = "SELL"
                    del units[j]
            for j in target:
                if j in units:
                    F = row[j] / rrow[j]
                    want = math.floor(slot / rrow[j])
                    have = units[j] * F
                    if want < have - 1e-9:
                        proceeds = (have - want) * rrow[j]
                        cash += proceeds; sells_val += proceeds
                        trades.append((d, cols[j], "TRIM", proceeds, rrow[j], "reset to 5%"))
                        units[j] = want / F
            for j in target:
                F = row[j] / rrow[j]
                want = math.floor(slot / rrow[j])
                have = units.get(j, 0.0) * F
                if want > have + 1e-9:
                    add = want - have
                    cost = add * rrow[j]
                    if cost > cash:
                        add = math.floor(cash / rrow[j]); cost = add * rrow[j]
                    if add > 0:
                        cash -= cost; buys_val += cost
                        trades.append((d, cols[j], "BUY" if j not in held_before else "ADD", cost, rrow[j], "reset to 5%"))
                        units[j] = units.get(j, 0.0) + add / F
                        last_px[j] = row[j]; miss[j] = 0
                if j not in actions:
                    actions[j] = "BUY" if j not in held_before else "KEEP"
            for j in list(units):
                if units[j] <= 0:
                    del units[j]
            nav_after = cash + sum(val_of(j, t) for j in units)
            w_after = {j: val_of(j, t) / nav_after for j in units}
            shares_after = {j: units[j] * row[j] / rrow[j] if not np.isnan(rrow[j]) else np.nan for j in units}
            n_elig = len(elig)
            reason = ""
            if len(target) < N_HOLD:
                a = int((sg["below_ma"] & ~sg["jump"]).sum()); b = int((sg["jump"] & ~sg["below_ma"]).sum()); both = int((sg["jump"] & sg["below_ma"]).sum())
                if n_elig < N_HOLD:
                    reason = (f"only {n_elig} of {len(sg)} ranked members passed both filters "
                              f"({a} under the 100-day average only, {b} with a >{jump:.0%} one-day move only, {both} both)")
                else:
                    reason = f"{n_elig} passed the filters but only {len(target)} could trade at the signal close"
            liq = {}
            for j in units:
                v20 = val20.iloc[t, j]
                liq[cols[j]] = (float(units[j] * row[j] / 1e7 / v20) if (v20 and not np.isnan(v20) and v20 > 0) else np.nan)
            recs.append({"signal_date": d, "fill_date": d, "list_date": mem.list_date(d),
                         "n_members": len(members), "n_ranked": len(sg), "n_eligible": n_elig,
                         "n_below_ma": int(sg["below_ma"].sum()), "n_jump": int(sg["jump"].sum()),
                         "target": [cols[j] for j in target], "skipped_untradeable": skipped,
                         "elig_order": list(elig.index[:N_HOLD + len(skipped) + 5]),
                         "held_before": [cols[j] for j in held_before], "held_after": [cols[j] for j in units],
                         "n_held": len(units), "empty_slots": N_HOLD - len(target), "reason": reason,
                         "max_weight": max(w_after.values()) if w_after else 0.0,
                         "cash_weight": cash / nav_after, "nav": nav_after, "nav_before": nav_before,
                         "w_after": {cols[j]: w for j, w in w_after.items()}, "liq": liq,
                         "sg": sg, "universe_ids": list(members)})
            ids = list(dict.fromkeys(list(sg.index[:45]) + [cols[j] for j in held_before] + [cols[j] for j in units]))
            mset = set(members)
            cutoff = int(sg.loc[cols[target[-1]], "rank"]) if target else None
            slot_of = {j: k + 1 for k, j in enumerate(target)}
            for c in ids:
                j = colpos[c]
                r = sg.loc[c] if c in sg.index else None
                act = actions.get(j, "" if j in tset or j in held_before else "not held")
                xtra = {"in_nifty500_list": c in mset, "pick_no": slot_of.get(j, np.nan), "rank_of_20th_pick": cutoff,
                        "pct_vs_100d_avg": float(r["pct_vs_ma"]) if r is not None else np.nan,
                        "biggest_move_120d": float(r["max_move"]) if r is not None else np.nan,
                        "biggest_move_date": (pd.Timestamp(r["max_move_date"]).date() if r is not None and pd.notna(r["max_move_date"]) else None),
                        "why": explain(act, r, c in mset, cutoff, slot_of.get(j), jump)}
                ledger.append({"signal_date": d.date(), "fill_date": d.date(), "isin": c, "symbol": NAMES.get(c, c),
                               "rank": int(r["rank"]) if r is not None else np.nan,
                               "annualised_slope": float(r["ann_slope"]) if r is not None else np.nan,
                               "r_squared": float(r["r2"]) if r is not None else np.nan,
                               "score": float(r["score"]) if r is not None else np.nan,
                               "below_100d_avg": bool(r["below_ma"]) if r is not None else np.nan,
                               "jump_over_limit": bool(r["jump"]) if r is not None else np.nan,
                               "eligible": bool(r["eligible"]) if r is not None else False,
                               "in_target": j in tset, "action": actions.get(j, "" if j in tset or j in held_before else "not held"),
                               "shares_before": shares_before.get(j, 0.0), "shares_after": shares_after.get(j, 0.0),
                               "weight_before": w_before.get(j, 0.0), "weight_after": w_after.get(j, 0.0),
                               "raw_close": rrow[j], **xtra})
        nav_t = cash + sum(val_of(j, t) for j in units)
        nav[d] = nav_t
        cashw[d] = cash / nav_t
        for j in units:
            last_px[j] = row[j] if not np.isnan(row[j]) else last_px.get(j, np.nan)
    navs = pd.Series(nav)
    out = {"nav": navs, "ret": navs.pct_change().iloc[1:], "recs": recs, "ledger": pd.DataFrame(ledger),
           "trades": pd.DataFrame(trades, columns=["date", "isin", "action", "value", "price", "reason"]),
           "cashw": pd.Series(cashw), "suspensions": suspensions, "contrib": contrib, "cols": cols,
           "buys": buys_val, "sells": sells_val}
    yrs = (navs.index[-1] - navs.index[0]).days / 365.25
    out["turnover_one_way"] = float((buys_val + sells_val) / 2 / navs.mean() / yrs)     # measured, not converted to cost
    out["turnover_two_way"] = float((buys_val + sells_val) / navs.mean() / yrs)
    return out


def ew_universe(adj, mem, sigdates):
    """Equal-weight every name on that day's list that has a close on the signal day: no filters, same signal
    closes, same same-close fills, gross, 0% cash. Weights drift inside the month; a halted name earns 0."""
    idx = adj.index
    px = adj.ffill()
    rets = px.pct_change(fill_method=None).fillna(0.0)
    sds = [d for d in sigdates if d <= SAMPLE_END]
    out = {}
    for k, sd in enumerate(sds):
        nxt = sds[k + 1] if k + 1 < len(sds) else SAMPLE_END
        members = [m for m in mem.on(sd) if not np.isnan(adj.loc[sd, m])]
        seg = rets.loc[(rets.index > sd) & (rets.index <= nxt), members]
        g = (1 + seg).cumprod()
        port = g.mean(axis=1)
        prev = port.shift(1).fillna(1.0)
        out.update((port / prev - 1.0).to_dict())
    return pd.Series(out).sort_index()


def stats(v, r, label, rf_annual=RF_ANNUAL):
    # Sharpe is (mean daily return x 252 - hurdle) / (daily std x sqrt 252): the one definition every Lightyear
    # script and the workbook use. Until 2026-10-28 this script used (CAGR - hurdle) / vol, which gave a
    # different number under the same label.
    c, vol = _cagr(v), _ann_vol(r)
    sharpe = float((r.mean() * 252 - rf_annual) / (r.std() * math.sqrt(252))) if vol > 0 else float("nan")
    return {"name": label, "cagr": float(c), "vol": float(vol), "sharpe_over_hurdle": sharpe,
            "max_dd": float(_mdd(v)), "total_return": float(v.iloc[-1] / v.iloc[0] - 1.0), "n_days": len(r),
            "start": str(v.index[0].date()), "end": str(v.index[-1].date())}


def load_bench(index):
    wb = load_banner_workbook(INDEX_PATH, sheet="Broad Market")[0]
    fac = load_banner_workbook(INDEX_PATH, sheet="Factor Indices")[0]
    allb = {"NIFTY 500": wb["NIFTY 500 Close"].dropna()}
    for n in ["NIFTY500 MOMENTUM 50", "NIFTY500 VALUE 50", "NIFTY500 QUALITY 50", "NIFTY500 LOW VOLATILITY 50"]:
        allb[n] = fac[n + " Close"].dropna()
    return {k: v.reindex(index.union(v.index)).ffill().reindex(index) for k, v in allb.items()}


def drawdown_dates(v):
    """Peak, trough and recovery date of the deepest fall from a peak, and its depth (a positive fraction)."""
    peak = v.cummax()
    dd = v / peak - 1.0
    tr = dd.idxmin()
    pk = v.loc[:tr].idxmax()
    rec = v.loc[tr:][v.loc[tr:] >= v.loc[pk]]
    return {"peak": str(pk.date()), "trough": str(tr.date()), "recovered": (str(rec.index[0].date()) if len(rec) else None),
            "depth": float(-dd.min())}


# ------------------------------------------------------------------ churn checks ---------------------------
def churn_checks(sim, adj, close, ev, ev_all, mem, root, out_path):
    """Every check here must pass before any performance number is looked at. Returns (all_passed, text)."""
    L, ok_all = [], True

    def rec(name, passed, detail=""):
        nonlocal ok_all
        ok_all = ok_all and bool(passed)
        L.append(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))

    recs = sim["recs"]; tr = sim["trades"]
    L.append("Execution convention (operator decision, Gate A rerun 2): rank on the month-end close, trade at THAT SAME close; "
             "the new book earns returns from the next trading day. Fills assume the official closing price.")
    bad = [r for r in recs if r["n_held"] != N_HOLD and not r["reason"]]
    rec("each rebalance holds 20 names, or a reason is logged", not bad,
        f"{len(recs)} rebalances; {sum(1 for r in recs if r['n_held'] < N_HOLD)} with fewer than 20, all with a reason")
    bad2, bad_univ = [], []
    for r in recs:
        sg = r["sg"]; elig = sg[sg["eligible"]]
        walk = []
        for c in elig.index:
            if c in r["skipped_untradeable"]:
                continue
            walk.append(c)
            if len(walk) == N_HOLD:
                break
        if walk != r["target"]:
            bad2.append(str(r["signal_date"].date()))
        if not set(r["target"]).issubset(set(elig.index)) or not set(r["target"]).issubset(set(r["universe_ids"])):
            bad_univ.append(str(r["signal_date"].date()))
    rec("target = first 20 eligible names walking down the full ranking (untradeable skipped)", not bad2, str(bad2[:5]))
    rec("every target name is eligible AND in that signal day's official NIFTY 500 list", not bad_univ, str(bad_univ[:5]))
    bad3 = []
    led = sim["ledger"]
    for r in recs:
        prev = set(r["held_before"]); tgt = set(r["target"])
        sub = led[led["fill_date"] == r["fill_date"].date()]
        sells = set(sub[sub["action"].str.startswith("SELL")]["isin"]); buys = set(sub[sub["action"] == "BUY"]["isin"]); keeps = set(sub[sub["action"] == "KEEP"]["isin"])
        if sells != prev - tgt or buys != tgt - prev or keeps != prev & tgt:
            bad3.append(str(r["fill_date"].date()))
    rec("SELL = held minus target, BUY = target minus held, KEEP = both (every month)", not bad3, str(bad3[:5]))
    bad4 = []
    for r in recs:
        for c in r["target"]:
            w = r["w_after"].get(c, 0.0)
            tol = float(close.loc[r["fill_date"], c]) / r["nav"]
            if not (0.05 - tol - 0.002 <= w <= 0.05 + 1e-9):
                bad4.append((str(r["fill_date"].date()), NAMES.get(c, c), round(w, 5)))
    rec("target weights are 5% less whole-share rounding (never above 5%)", not bad4, str(bad4[:5]))
    bad5 = [str(r["fill_date"].date()) for r in recs if abs(sum(r["w_after"].values()) + r["cash_weight"] - 1.0) > 1e-9]
    rec("stocks + cash = 100% of the account at every rebalance (never scaled up)", not bad5, str(bad5[:5]))
    bad6 = []
    for r in recs:
        b = tr[(tr["date"] == r["fill_date"]) & tr["action"].isin(["BUY", "ADD"])]["isin"]
        if not set(b).issubset(set(r["universe_ids"])) or not set(b).issubset(set(r["sg"][r["sg"]["eligible"]].index)):
            bad6.append(str(r["fill_date"].date()))
    rec("no purchase outside that signal day's list, and none outside the eligible ranking", not bad6, str(bad6[:5]))
    # look-ahead tripwire: recompute 3 random months with ALL data after the signal close removed
    rng = np.random.default_rng(7)
    picks = rng.choice(len(recs), size=3, replace=False)
    la = []
    for k in picks:
        r = recs[k]; sd = r["signal_date"]; i = adj.index.get_loc(sd)
        cut = close.iloc[: i + 1]
        adj_cut, _ = apply_events(cut, ev, upto=sd)
        fp_ = first_positions(adj_cut)
        sg = rank_table(signals_at(adj_cut, i, JUMP, fp_), mem.on(sd))
        e = sg[sg["eligible"]]
        walk = [c for c in e.index if c not in r["skipped_untradeable"]][:N_HOLD]
        la.append((str(sd.date()), walk == r["target"], list(e.index[:N_HOLD]) == r["elig_order"][:N_HOLD]))
    rec("look-ahead tripwire: 3 random months recomputed with every price AFTER the signal close deleted give the same top 20",
        all(a[1] for a in la), "; ".join(f"{a[0]}:{'same' if a[1] else 'DIFFERENT'}" for a in la))
    from scipy import stats as st
    hc = []
    for k in picks:
        r = recs[k]; sd = r["signal_date"]; i = adj.index.get_loc(sd)
        for c in r["sg"].index[:3]:
            y = np.log(adj[c].iloc[i - WINDOW + 1: i + 1].astype(float).values)
            m = ~np.isnan(y)
            res = st.linregress(np.arange(WINDOW)[m], y[m])
            sc = (math.exp(res.slope) ** 250 - 1) * res.rvalue ** 2
            hc.append((str(sd.date()), NAMES.get(c, c), abs(sc - r["sg"].loc[c, "score"]) < 1e-9 * max(1, abs(sc))))
    rec("hand-check: top 3 scores in 3 months match an independent least-squares fit (Excel SLOPE/RSQ equivalent)", all(h[2] for h in hc),
        f"{sum(h[2] for h in hc)}/{len(hc)} match")
    # corporate-action days
    ret_adj = adj.pct_change(fill_method=None)
    ret_raw = close.pct_change(fill_method=None)
    evk = set(zip(ev["date"], ev["ID"]))
    fills = [r["fill_date"] for r in recs]
    big_events, unexplained = [], []
    for k, r in enumerate(recs):
        nxt = fills[k + 1] if k + 1 < len(fills) else SAMPLE_END
        for c in r["held_after"]:
            s = ret_adj[c].loc[(ret_adj.index > r["fill_date"]) & (ret_adj.index <= nxt)].dropna()
            for d_, v in s.items():
                if (d_, c) in evk:
                    big_events.append((str(d_.date()), NAMES.get(c, c), float(ret_raw.loc[d_, c]), float(v)))
                elif abs(v) > 0.25:
                    unexplained.append((str(d_.date()), NAMES.get(c, c), float(v)))
    bad9 = [b for b in big_events if abs(b[3]) > 0.25]
    rec("no held name jumps on a corporate-action day beyond its adjusted return", not bad9,
        f"{len(big_events)} held-name event days seen, {len(bad9)} with adjusted return > 25%")
    for b in big_events[:20]:
        L.append(f"      event day {b[0]} {b[1]}: raw move {b[2]:+.1%}, adjusted move {b[3]:+.1%}")
    L.append(f"      other held-name days with an adjusted move over 25% (real gaps or missed actions): {len(unexplained)}")
    for u in unexplained[:15]:
        L.append(f"        {u[0]} {u[1]} {u[2]:+.1%}")
    sim["unexplained_moves"] = unexplained
    # PFC 2023-09-21 and NMDC 2022-10-27 explicitly (corrected rows in the event file)
    for sym, dt, fac in (("PFC", "2023-09-21", 0.8), ("NMDC", "2022-10-27", 0.7977)):
        row = ev_all[(ev_all["symbol"] == sym) & (ev_all["date"] == pd.Timestamp(dt))]
        okrow = (len(row) == 1 and abs(float(row["adjust_factor"].iloc[0]) - fac) < 1e-6)
        c = row["ID"].iloc[0] if len(row) else None
        held_on = [str(r["fill_date"].date()) for r in recs if c in r["held_after"] and r["fill_date"] < pd.Timestamp(dt)]
        if c is not None and pd.Timestamp(dt) in ret_adj.index:
            ra, rr = float(ret_adj.loc[pd.Timestamp(dt), c]), float(ret_raw.loc[pd.Timestamp(dt), c])
        else:
            ra = rr = float("nan")
        rec(f"{sym} {dt}: event file factor {fac} is applied and the adjusted one-day move is small", okrow and abs(ra) < 0.10,
            f"raw move {rr:+.1%}, adjusted move {ra:+.1%}; file factor {float(row['adjust_factor'].iloc[0]) if len(row) else None}")
    ins = [len(set(r["target"]) - set(r["held_before"])) for r in recs[1:]]
    outs = [len(set(r["held_before"]) - set(r["target"])) for r in recs[1:]]
    stays, cur = [], {}
    for r in recs:
        for c in r["held_after"]:
            cur[c] = cur.get(c, 0) + 1
        for c in list(cur):
            if c not in r["held_after"]:
                stays.append(cur.pop(c))
    stays += list(cur.values())
    L.append(f"CHURN REPORT: names in per month avg {np.mean(ins):.1f} (max {max(ins)}); names out avg {np.mean(outs):.1f} (max {max(outs)}); "
             f"average stay {np.mean(stays):.1f} months; names held at least once {len({c for r in recs for c in r['held_after']})}")
    L.append(f"              one-way annual turnover {sim['turnover_one_way']:.2f}x average account; two-way {sim['turnover_two_way']:.2f}x (measured; no cost is charged)")
    sim["churn"] = {"names_in_avg": float(np.mean(ins)), "names_out_avg": float(np.mean(outs)), "avg_stay_months": float(np.mean(stays)),
                    "names_in_max": int(max(ins)), "names_out_max": int(max(outs)),
                    "names_ever_held": len({c for r in recs for c in r['held_after']})}
    text = "\n".join(L)
    open(out_path, "w", encoding="utf-8").write(text + "\n")
    return ok_all, text


# ------------------------------------------------------------------ main ---------------------------------
def main():
    global NAMES
    ap = argparse.ArgumentParser()
    ap.add_argument("--handoff", default=RUN)
    ap.add_argument("--no-charts", action="store_true")
    ap.add_argument("--checks-only", action="store_true")
    a = ap.parse_args()
    os.makedirs(SCRATCH, exist_ok=True)
    close, val_cr, NAMES, ev, ev_all, root, nlinks = build_panel()
    adj, n_applied = apply_events(close, ev)
    adj_v, n_applied_v = apply_events(close, ev, skip_medium_low_splitbonus=True)
    mem = Membership(root, close.columns)
    fp = first_positions(adj)
    fp_v = first_positions(adj_v)
    val20 = val_cr.rolling(20, min_periods=15).sum()
    info = {"securities": int(close.shape[1]), "trading_days": int(close.shape[0]), "events_applied_base": n_applied,
            "events_applied_variant": n_applied_v, "isin_links": nlinks, "first_date": str(close.index[0].date()),
            "last_date": str(close.index[-1].date()), "pit_slots_not_in_panel": mem.missing}
    print("PANEL", info)
    res = {"panel": info}
    sd_me = signal_dates(adj.index, "ME")

    # ---------------- main simulation, then CHURN CHECKS BEFORE ANY RESULT IS READ ----------------
    base = simulate(adj, close, val20, mem, sd_me, fp)
    ok, text = churn_checks(base, adj, close, ev, ev_all, mem, root, os.path.join(a.handoff, "churn_checks.txt"))
    print("\nCHURN CHECKS (all must pass before any result is read)\n" + text)
    if not ok:
        print("\nCHURN CHECKS FAILED. No result is shown.")
        sys.exit(2)
    print("\nALL CHURN CHECKS PASSED.")
    led = base["ledger"]
    led.to_csv(os.path.join(OUT, f"{SLUG}_monthly_ledger.csv"), index=False, float_format="%.8f")
    led.to_csv(os.path.join(a.handoff, "monthly_ledger.csv"), index=False, float_format="%.8f")
    res["churn_checks_text"] = text
    res["churn"] = base["churn"]
    if a.checks_only:
        return

    # ---------------- cash, breadth and liquidity ----------------
    recs = base["recs"]
    cw = base["cashw"]
    cash_months = [{"fill_date": str(r["fill_date"].date()), "names_held": r["n_held"], "empty_slots": r["empty_slots"],
                    "cash_weight": r["cash_weight"], "reason": r["reason"] or "whole-share leftover only"} for r in recs if r["empty_slots"] > 0]
    res["cash"] = {"avg_daily_cash_weight": float(cw.mean()), "max_daily_cash_weight": float(cw.max()),
                   "max_cash_date": str(cw.idxmax().date()), "avg_cash_at_rebalance": float(np.mean([r["cash_weight"] for r in recs])),
                   "max_cash_at_rebalance": float(max(r["cash_weight"] for r in recs)),
                   "months_with_empty_slot": len(cash_months), "months": cash_months,
                   "suspensions": [{"date": str(s["date"].date()), "name": NAMES.get(s["id"], s["id"]), "proceeds": s["proceeds"]} for s in base["suspensions"]]}
    print(f"\nCASH: average {cw.mean():.3%} of account, maximum {cw.max():.3%} on {cw.idxmax().date()}; {len(cash_months)} of {len(recs)} months with an empty slot; "
          f"{len(base['suspensions'])} suspension/delisting sales")
    for m in cash_months:
        print(f"   {m['fill_date']}: {m['names_held']} names, {m['empty_slots']} empty, cash {m['cash_weight']:.1%} -- {m['reason']}")
    lg = pd.DataFrame([{k: v for k, v in r.items() if k in ("signal_date", "fill_date", "list_date", "n_members", "n_ranked", "n_eligible", "n_below_ma",
                                                           "n_jump", "n_held", "empty_slots", "reason", "max_weight", "cash_weight", "nav")} for r in recs])
    lg.to_csv(os.path.join(OUT, f"{SLUG}_rebalance_log.csv"), index=False)
    res["breadth"] = {"rebalances": len(lg), "min_held": int(lg["n_held"].min()), "months_below_20": int((lg["n_held"] < N_HOLD).sum()),
                      "months_below_5": int((lg["n_held"] < 5).sum()), "max_single_weight": float(lg["max_weight"].max()),
                      "months_over_25pct": int((lg["max_weight"] > 0.25).sum()), "avg_eligible": float(lg["n_eligible"].mean()),
                      "min_eligible": int(lg["n_eligible"].min()), "avg_ranked": float(lg["n_ranked"].mean()),
                      "avg_members": float(lg["n_members"].mean())}
    print("BREADTH", res["breadth"])
    liq_rows = [{"fill_date": str(r["fill_date"].date()), "symbol": NAMES.get(c, c), "position_share_of_20d_traded_value": v,
                 "position_rs_crore": r["w_after"].get(c, 0.0) * r["nav"] / 1e7}
                for r in recs for c, v in r["liq"].items()]
    ldf = pd.DataFrame(liq_rows)
    ldf.to_csv(os.path.join(a.handoff, "liquidity_check.csv"), index=False)
    top = ldf.sort_values("position_share_of_20d_traded_value", ascending=False).iloc[0]
    res["liquidity"] = {"max_share_of_20d_traded_value": float(top["position_share_of_20d_traded_value"]), "symbol": top["symbol"],
                        "date": top["fill_date"], "position_rs_crore": float(top["position_rs_crore"]),
                        "median_share": float(ldf["position_share_of_20d_traded_value"].median()),
                        "p99_share": float(ldf["position_share_of_20d_traded_value"].quantile(0.99))}
    print("LIQUIDITY (largest position as share of the stock's 20-day traded value)", res["liquidity"])

    # ---------------- benchmark, equal-weight universe ----------------
    bench = load_bench(adj.index)
    vg, rg = base["nav"], base["ret"]
    b = bench["NIFTY 500"].reindex(vg.index)
    vb = b / b.iloc[0]
    rb = vb.pct_change().iloc[1:]
    ew_r = ew_universe(adj, mem, sd_me).reindex(rg.index).fillna(0.0)
    ew_v = pd.concat([pd.Series([1.0], index=[vg.index[0]]), (1 + ew_r).cumprod()])
    rows = [stats(vg / vg.iloc[0], rg, "Clenow top-20 (gross, 0bp)"),
            stats(vb, rb, "NIFTY 500 (price)"),
            stats(ew_v, ew_r, "Equal-weight official NIFTY 500 list, monthly, gross")]
    perf = pd.DataFrame(rows)
    print("\nPERFORMANCE\n" + perf.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    perf.to_csv(os.path.join(OUT, f"{SLUG}_performance.csv"), index=False)
    res["performance"] = rows
    res["turnover"] = {"one_way_annual": base["turnover_one_way"], "two_way_annual": base["turnover_two_way"]}
    print(f"  turnover (measured): one-way {base['turnover_one_way']:.2f}x, two-way {base['turnover_two_way']:.2f}x a year; no cost charged")
    cal = lambda x: (1 + x).groupby(x.index.year).prod() - 1
    res["calendar_year"] = {"strategy": {int(k): float(v) for k, v in cal(rg).items()}, "nifty500": {int(k): float(v) for k, v in cal(rb.reindex(rg.index)).items()},
                            "equal_weight": {int(k): float(v) for k, v in cal(ew_r).items()}}

    worst = rg.nsmallest(5)
    wl = []
    for d, r in worst.items():
        i = adj.index.get_loc(d)
        rr = [x for x in recs if x["fill_date"] < d][-1]
        names = rr["held_after"]
        mv = (adj.iloc[i][names] / adj.iloc[i - 1][names] - 1).dropna().sort_values()
        wl.append({"date": str(d.date()), "strategy": float(r), "nifty500": float(rb.get(d, np.nan)),
                   "worst_names": [(NAMES.get(k, k), float(v)) for k, v in mv.head(3).items()]})
        print(f"  WORST DAY {d.date()} strategy {r:.2%} NIFTY500 {rb.get(d, np.nan):.2%} laggards {[(NAMES.get(k, k), round(v, 3)) for k, v in mv.head(3).items()]}")
    res["worst_days"] = wl
    oc = pd.Series({base["cols"][j]: v for j, v in base["contrib"].items()}).sort_values(ascending=False)
    pos_total = oc[oc > 0].sum()
    res["top2_share_of_gains"] = float(oc.head(2).sum() / pos_total) if pos_total > 0 else float("nan")
    res["best_contributors"] = [(NAMES.get(k, k), float(v / START_NAV)) for k, v in oc.head(5).items()]
    res["worst_contributors"] = [(NAMES.get(k, k), float(v / START_NAV)) for k, v in oc.tail(3).items()]
    print("  top-2 names share of gross rupee gains", f"{res['top2_share_of_gains']:.0%}", res["best_contributors"][:3])

    # ---------------- variants: timing luck (ONE common window), 20% jump, corporate-action variant ----------------
    print("\nVARIANTS")
    base_nifty = float(_cagr(vb))
    sens = []

    def add(name, r_):
        v_ = r_["nav"] / r_["nav"].iloc[0]
        bk = bench["NIFTY 500"].reindex(v_.index); bk = bk / bk.iloc[0]
        s = stats(v_, r_["ret"], name)
        s["nifty500_cagr"] = float(_cagr(bk)); s["minus_nifty500_cagr"] = s["cagr"] - s["nifty500_cagr"]
        s["annual_turnover_two_way"] = r_["turnover_two_way"]
        sens.append(s)

    add("BASE month-end, 15% jump, gross", base)
    timing = {"month-end": base}
    for k in (1, 6, 11, 16):
        sdk = signal_dates(adj.index, k)
        r_g = simulate(adj, close, val20, mem, sdk, fp)
        add(f"rebalance on trading day {k} (gross), own full window", r_g)
        timing[f"trading day {k}"] = r_g
    jmp_g = simulate(adj, close, val20, mem, sd_me, fp, jump=0.20)
    add("20% jump limit, month-end (gross)", jmp_g)
    var = simulate(adj_v, close, val20, mem, sd_me, fp_v)
    add("medium/low SPLIT/BONUS rows treated as REAL, month-end (gross)", var)
    sens = pd.DataFrame(sens)
    print(sens[["name", "cagr", "vol", "max_dd", "minus_nifty500_cagr", "annual_turnover_two_way"]].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    sens.to_csv(os.path.join(OUT, f"{SLUG}_sensitivities.csv"), index=False)
    res["sensitivities"] = sens.to_dict("records")

    # timing luck on one common window: starts at the close of the LATEST first trade, ends 2026-09-18
    latest_first = max(t_["nav"].index[0] for t_ in timing.values())
    tw = []
    nb = bench["NIFTY 500"]
    nb_w = nb.loc[latest_first:SAMPLE_END]
    nifty_c = float(_cagr(nb_w))
    for nm, t_ in timing.items():
        v_ = t_["nav"].loc[latest_first:SAMPLE_END]
        c_ = float(_cagr(v_))
        tw.append({"timing": nm, "first_trade": str(t_["nav"].index[0].date()), "window_start": str(latest_first.date()),
                   "window_end": str(v_.index[-1].date()), "cagr": c_, "nifty500_cagr": nifty_c, "cagr_minus_nifty500": c_ - nifty_c,
                   "max_dd": float(_mdd(v_ / v_.iloc[0]))})
    twdf = pd.DataFrame(tw)
    print(f"\nTIMING LUCK, common window {latest_first.date()} to {SAMPLE_END.date()} (the first return day is the next trading day)")
    print(twdf.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    twdf.to_csv(os.path.join(a.handoff, "timing_common_window.csv"), index=False)
    res["timing_common_window"] = tw
    res["timing_band"] = {"min": float(twdf["cagr"].min()), "max": float(twdf["cagr"].max()), "window_start": str(latest_first.date()),
                          "nifty500_cagr": nifty_c, "all_beat_nifty500": bool((twdf["cagr_minus_nifty500"] > 0).all())}

    # corporate-action variant: every stock whose selection differs
    diffs = []
    for r1, r2 in zip(recs, var["recs"]):
        s1, s2 = set(r1["target"]), set(r2["target"])
        if s1 != s2:
            diffs.append({"fill_date": str(r1["fill_date"].date()),
                          "only_in_base": sorted(NAMES.get(c, c) for c in s1 - s2), "only_in_variant": sorted(NAMES.get(c, c) for c in s2 - s1)})
    res["ca_variant_diffs"] = diffs
    res["ca_variant_rows_treated_as_real"] = int(((ev["label"] == "SPLIT/BONUS") & ev["confidence"].isin(["medium", "low"])).sum())
    affected = sorted({n for d in diffs for n in d["only_in_base"] + d["only_in_variant"]})
    res["ca_variant_affected"] = affected
    print(f"\nCA VARIANT: {res['ca_variant_rows_treated_as_real']} medium/low SPLIT/BONUS rows treated as REAL; selection differs in {len(diffs)} of {len(recs)} months; "
          f"stocks affected: {affected}")
    pd.DataFrame(diffs).to_csv(os.path.join(a.handoff, "corporate_action_variant_differences.csv"), index=False)

    # 20% jump variant diagnosis (operator note H)
    ever_base = {c for r in recs for c in r["held_after"]}
    ever_j = {c for r in jmp_g["recs"] for c in r["held_after"]}
    only_j = sorted(ever_j - ever_base)
    vj = jmp_g["nav"] / jmp_g["nav"].iloc[0]
    ddj = drawdown_dates(vj)
    held_at_trough = []
    tr_d = pd.Timestamp(ddj["trough"])
    rj = [x for x in jmp_g["recs"] if x["fill_date"] <= tr_d][-1]
    held_at_trough = [NAMES.get(c, c) for c in rj["held_after"]]
    ret_adj = adj.pct_change(fill_method=None); ret_raw = close.pct_change(fill_method=None)
    evk = ev_all.set_index(["date", "ID"])
    diag_rows = []
    for c in only_j:
        months = [str(r["fill_date"].date()) for r in jmp_g["recs"] if c in r["held_after"]]
        lo = pd.Timestamp(months[0]) - pd.Timedelta(days=190)
        seg = ret_adj[c].loc[lo:SAMPLE_END].dropna()
        mv = seg[(seg.abs() > 0.15) & (seg.abs() <= 0.20)]
        if mv.empty:
            diag_rows.append({"symbol": NAMES.get(c, c), "isin": c, "months_held": len(months), "first_held": months[0], "last_held": months[-1],
                              "move_date": "", "adjusted_move": np.nan, "raw_move": np.nan, "event_file_label": "", "event_file_confidence": "",
                              "event_file_near_standard_ratio": "", "reading": "no one-day move between 15% and 20% in the look-back"})
        for d_, v in mv.items():
            if (d_, c) in evk.index:
                e = evk.loc[(d_, c)]
                e = e.iloc[0] if isinstance(e, pd.DataFrame) else e
                lab, conf, near = e["label"], e["confidence"], e["near_standard_ratio"]
                reading = ("event file: adjusted as a split/bonus/demerger" if lab in ("SPLIT/BONUS", "DEMERGER") else
                           f"event file: kept as a REAL move ({conf}); {str(e['evidence'])[:140]}")
            else:
                lab = conf = near = ""
                reading = "no event-file row: not near a standard split/bonus ratio, so a real move"
            diag_rows.append({"symbol": NAMES.get(c, c), "isin": c, "months_held": len(months), "first_held": months[0], "last_held": months[-1],
                              "move_date": str(d_.date()), "adjusted_move": float(v), "raw_move": float(ret_raw.loc[d_, c]),
                              "event_file_label": lab, "event_file_confidence": conf, "event_file_near_standard_ratio": near, "reading": reading})
    ddf = pd.DataFrame(diag_rows)
    ddf.to_csv(os.path.join(a.handoff, "jump20_diagnosis.csv"), index=False)
    n_with_move = int(ddf[ddf["move_date"] != ""]["symbol"].nunique()) if len(ddf) else 0
    n_possible_ca = int(((ddf["event_file_near_standard_ratio"].astype(str) != "") & (ddf["event_file_label"] == "REAL")).sum()) if len(ddf) else 0
    res["jump20"] = {"names_only_in_20pct": [NAMES.get(c, c) for c in only_j], "n_names_only": len(only_j), "deepest_drawdown": ddj,
                     "base_deepest_drawdown": drawdown_dates(vg / vg.iloc[0]), "held_at_trough": held_at_trough,
                     "only_names_held_at_trough": [n for n in held_at_trough if n in [NAMES.get(c, c) for c in only_j]],
                     "names_with_15_20_move": n_with_move, "moves_flagged_near_standard_ratio_kept_real": n_possible_ca,
                     "moves": ddf[ddf["move_date"] != ""].to_dict("records")}
    print("\n20% JUMP DIAGNOSIS", json.dumps({k: v for k, v in res["jump20"].items() if k != "moves"}, default=str, indent=1))
    print(ddf[ddf["move_date"] != ""][["symbol", "move_date", "adjusted_move", "raw_move", "event_file_label", "event_file_confidence", "event_file_near_standard_ratio"]].to_string(index=False))

    # ---------------- step 06: validation (gross book, excess of the 6% hurdle) ----------------
    print("\nRESEARCH VALIDATION (gross book, excess of the 6% hurdle)")
    rf = pd.Series(RF_D, index=rg.index)
    boot = bootstrap_sharpe_ci(rg, block_size=BLOCK, n_resamples=2000, rf_daily=rf, seed=0)
    print(f"  block-bootstrap Sharpe 90% CI [{boot.ci_low:.2f}, {boot.ci_high:.2f}] point {boot.point_estimate:.2f}")
    res["bootstrap_main"] = {"ci_low": boot.ci_low, "ci_high": boot.ci_high, "point": boot.point_estimate, "frac_positive": boot.fraction_positive}
    paired = {}
    for nm, other in (("NIFTY 500", rb.reindex(rg.index).fillna(0.0)), ("Equal-weight official NIFTY 500 list", ew_r)):
        pb = bootstrap_sharpe_ci((rg - other).fillna(0.0), block_size=BLOCK, n_resamples=2000, seed=0)
        paired[nm] = {"ci_low": pb.ci_low, "ci_high": pb.ci_high, "point": pb.point_estimate, "p_not_positive": 1.0 - pb.fraction_positive}
        print(f"  PAIRED strategy minus {nm}: Sharpe of difference [{pb.ci_low:.2f}, {pb.ci_high:.2f}] P(<=0)={1.0 - pb.fraction_positive:.3f}")
    res["paired"] = paired
    n_wide = N_CONFIGS_CARD + 6          # 4 timings + 20% jump + corporate-action variant
    dsr8 = deflated_sharpe_from_returns(rg, n_trials=N_CONFIGS_CARD, trial_sharpe_std=0.3, rf_daily=rf)
    dsr = deflated_sharpe_from_returns(rg, n_trials=n_wide, trial_sharpe_std=0.3, rf_daily=rf)
    print(f"  Deflated Sharpe: n_trials={N_CONFIGS_CARD} (card floor) {dsr8:.3f}; n_trials={n_wide} (counting this run's 6 variants) {dsr:.3f}")
    res["deflated_sharpe_card_floor"] = float(dsr8); res["deflated_sharpe"] = float(dsr); res["n_trials_used"] = n_wide
    vnn = vg / vg.iloc[0]
    windows = walk_forward_windows(vnn.index, n_folds=4, min_train_years=1.0)
    oos = oos_stability_summary(vnn, rg, windows, rf_daily=rf, min_obs=60)
    print(oos.to_string(index=False) if not oos.empty else "  not enough history")
    oos.to_csv(os.path.join(OUT, f"{SLUG}_oos_stability.csv"), index=False)
    res["oos"] = oos.to_dict("records")

    # ---------------- step 07: factor fingerprint ----------------
    print("\nFACTOR FINGERPRINT")
    fnames = ["NIFTY 500", "NIFTY500 MOMENTUM 50", "NIFTY500 VALUE 50", "NIFTY500 QUALITY 50", "NIFTY500 LOW VOLATILITY 50"]
    fr = pd.DataFrame({n: bench[n].reindex(vg.index).pct_change(fill_method=None) for n in fnames}).iloc[1:]
    fpr = factor_fingerprint(rg, fr, rf_daily=rf)
    if "error" in fpr:
        print("  unavailable:", fpr["error"])
    else:
        print(f"  alpha {fpr['alpha_ann']:.2%} t(HAC) {fpr['alpha_t_hac']:.2f} R2 {fpr['r_squared']:.2f}  loadings { {k: round(v, 3) for k, v in fpr['loadings'].items()} }")
        res["factor_fingerprint"] = {k: fpr[k] for k in ("alpha_ann", "alpha_t_hac", "r_squared", "n_obs", "loadings") if k in fpr}
    te = float((rg - rb.reindex(rg.index).fillna(0.0)).std() * math.sqrt(252))
    res["tracking"] = {"tracking_error": te, "correlation_to_nifty500": float(rg.corr(rb.reindex(rg.index))),
                       "beta_to_nifty500": float(np.cov(rg, rb.reindex(rg.index).fillna(0))[0, 1] / rb.reindex(rg.index).fillna(0).var())}
    print(f"  tracking error {te:.2%}, correlation with NIFTY 500 {res['tracking']['correlation_to_nifty500']:.2f}, beta {res['tracking']['beta_to_nifty500']:.2f}")

    # ---------------- Gate B ----------------
    from ros.cards.schema import load_card
    from ros.governance.gates import gate_b
    research = {"deflated_sharpe": {"deflated_sharpe_prob": float(dsr),
                                    "interpretation": f"n_trials={n_wide} (card floor 8 plus this run's 6 variants), trial Sharpe std 0.3, gross book, over a 6% hurdle"},
                "oos_min_sharpe": float(oos["sharpe"].min()) if not oos.empty else None,
                "bootstrap_p_not_positive": float(paired["NIFTY 500"]["p_not_positive"])}
    portfolio = {"alpha_t_hac": (float(fpr["alpha_t_hac"]) if "error" not in fpr else None), "annual_turnover": base["turnover_two_way"]}
    gb = gate_b(load_card(CARD), research, portfolio)
    print("\n" + "=" * 100 + "\nGATE B CRITERIA (computed by gate_b(); decision stays PENDING)\n" + "=" * 100)
    print(gb.render())
    res["gate_b"] = gb.to_dict()
    res["gate_b_inputs"] = {"research": research, "portfolio": portfolio}

    # ---------------- hand-off files ----------------
    os.makedirs(a.handoff, exist_ok=True)
    daily = pd.DataFrame({"strategy": rg, "benchmark": rb.reindex(rg.index)})
    daily.index = daily.index.strftime("%Y-%m-%d"); daily.index.name = "date"
    daily.to_csv(os.path.join(a.handoff, "daily_returns.csv"), float_format="%.10f")
    comp = pd.DataFrame({"Equal-weight official NIFTY 500 list (gross)": ew_r,
                         "Strategy with 20% one-day-move limit (gross)": jmp_g["ret"],
                         "Strategy, medium/low split-bonus rows as REAL (gross)": var["ret"]}).reindex(rg.index)
    comp.index = comp.index.strftime("%Y-%m-%d"); comp.index.name = "date"
    comp.to_csv(os.path.join(a.handoff, "comparators.csv"), float_format="%.10f")
    rows_h = []
    for r in recs:
        for c in r["held_after"]:
            s = r["sg"].loc[c] if c in r["sg"].index else None
            rows_h.append({"date": r["fill_date"].strftime("%Y-%m-%d"), "symbol": NAMES.get(c, c), "leg": "long", "weight": r["w_after"].get(c, 0.0),
                           "price": float(close.loc[r["fill_date"], c]), "isin": c,
                           "rank": int(s["rank"]) if s is not None else np.nan, "signal_score": float(s["score"]) if s is not None else np.nan,
                           "r_squared": float(s["r2"]) if s is not None else np.nan})
    pd.DataFrame(rows_h).to_csv(os.path.join(a.handoff, "holdings.csv"), index=False, float_format="%.8f")
    # trades.csv = the trades the simulation actually executed, one row each, with the dates and prices used so every
    # one can be checked against that day's NSE bhavcopy (raw CLOSE). Weights and the reason come from the ledger.
    led_k = base["ledger"].copy()
    led_k["signal_date"] = pd.to_datetime(led_k["signal_date"])
    led_k = led_k.set_index(["signal_date", "isin"])
    sig_sorted = pd.DatetimeIndex(sorted(sd_me))
    rows_t = []
    for (td, isin, act, val, prc, why_t) in base["trades"].itertuples(index=False, name=None):
        td = pd.Timestamp(td)
        sd = sig_sorted[sig_sorted <= td][-1] if (sig_sorted <= td).any() else td
        on_signal = sd == td
        lk = led_k.loc[(sd, isin)] if (sd, isin) in led_k.index else None
        rows_t.append({"date": td.date(), "symbol": NAMES.get(isin, isin), "action": act,
                       "weight_before": float(lk["weight_before"]) if lk is not None and on_signal else np.nan,
                       "weight_after": float(lk["weight_after"]) if lk is not None and on_signal else np.nan,
                       "isin": isin, "signal_date": sd.date(), "execution_date": td.date(),
                       "price_date": td.date() if not np.isnan(prc) else None,
                       "price": prc,
                       "price_basis": ("NSE bhavcopy CLOSE on the execution date (raw, not adjusted)" if not np.isnan(prc)
                                       else "no trade that day: valued at the last traded close"),
                       "shares": round(val / prc, 4) if prc and not np.isnan(prc) else np.nan,
                       "value_rs": round(val, 2),
                       "why": (lk["why"] if lk is not None and on_signal else why_t)})
    order = {"SELL": 0, "TRIM": 1, "ADD": 2, "BUY": 3}
    tdf = pd.DataFrame(rows_t)
    tdf["_o"] = tdf["action"].map(order)
    tdf = tdf.sort_values(["date", "_o", "symbol"]).drop(columns="_o")
    tdf.to_csv(os.path.join(a.handoff, "trades.csv"), index=False, float_format="%.6f")
    # selection.csv = why each name was bought, kept, sold, skipped or not needed at every rebalance
    sel = base["ledger"].copy()
    sel["decision"] = sel["why"].str.split(":").str[0]
    sel = sel.rename(columns={"fill_date": "execution_date", "raw_close": "close_raw"})
    sel["price_date"] = sel["execution_date"]
    dorder = {"BOUGHT": 0, "KEPT": 1, "SOLD": 2, "SKIPPED": 3, "NOT NEEDED": 4, "Not scored": 5}
    sel["_o"] = sel["decision"].map(dorder).fillna(9)
    sel = sel.sort_values(["signal_date", "_o", "rank"]).drop(columns="_o")
    sel = sel[["signal_date", "execution_date", "price_date", "decision", "pick_no", "rank", "symbol", "isin", "score",
               "annualised_slope", "r_squared", "pct_vs_100d_avg", "biggest_move_120d", "biggest_move_date",
               "in_nifty500_list", "close_raw", "shares_before", "shares_after", "weight_before", "weight_after",
               "rank_of_20th_pick", "why"]]
    sel.to_csv(os.path.join(a.handoff, "selection.csv"), index=False, float_format="%.6f")
    tr = base["trades"].copy()
    tr["symbol"] = tr["isin"].map(NAMES); tr["date"] = pd.to_datetime(tr["date"]).dt.strftime("%Y-%m-%d")
    tr.to_csv(os.path.join(OUT, f"{SLUG}_trades_detail.csv"), index=False)
    pd.DataFrame(cash_months).to_csv(os.path.join(a.handoff, "cash_months.csv"), index=False)
    res["files_written"] = ["daily_returns.csv", "comparators.csv", "holdings.csv", "trades.csv", "monthly_ledger.csv", "churn_checks.txt",
                            "cash_months.csv", "selection.csv", "corporate_action_variant_differences.csv", "timing_common_window.csv",
                            "jump20_diagnosis.csv", "liquidity_check.csv"]

    if not a.no_charts:
        try:
            from universal_backtester.clean_charts import save_clean_charts
            charts = save_clean_charts(vnn, vb.reindex(vnn.index), outdir=os.path.join(OUT, "charts"), tag=SLUG,
                                       strategy_name="Clenow momentum top 20 (gross)", benchmark_name="NIFTY 500",
                                       footnote="Price return. Official NSE NIFTY 500 membership on each date (NSE lists and press releases); no costs; cash earns 0%; monthly reset to 5% each; fills at the month-end close.")
            res["charts"] = [os.path.relpath(c, REPO) for c in charts]
            print("charts:", res["charts"])
        except Exception as e:
            print("charts skipped:", repr(e))
    # ---------------- lineage: what exactly this run read, with hashes ----------------
    from ros.data.lineage import write_run_manifest
    res["manifest"] = os.path.relpath(write_run_manifest(
        a.handoff, __file__,
        inputs={"card": CARD, "corporate_action_events": EVENTS, "nifty500_membership": N500.MEMBERSHIP_CSV,
                "index_workbook": INDEX_PATH, "bhavcopy_cache": CACHE},
        params={"first_signal": str(FIRST_SIGNAL.date()), "sample_end": str(SAMPLE_END.date()), "window": WINDOW, "ma": MA,
                "jump": JUMP, "n_hold": N_HOLD, "cost_bp_round_trip": 0.0, "rf_annual": RF_ANNUAL,
                "n_trials_card": N_CONFIGS_CARD, "n_trials_used": n_wide,
                "sharpe_definition": "(mean daily return x 252 - rf_annual) / (daily std x sqrt 252)"},
        outputs=("daily_returns.csv", "comparators.csv", "holdings.csv", "trades.csv", "selection.csv")), REPO)
    print("manifest:", res["manifest"])
    json.dump(res, open(os.path.join(OUT, f"{SLUG}_results.json"), "w", encoding="utf-8"), indent=1, default=str)
    print("\nDone. Gate B decision is not assigned by this script.")


if __name__ == "__main__":
    main()
