"""Steps 04 to 07 for cards/method_nifty_equity_indices.yaml: NSE's Nifty500 Momentum 50 rules, rebuilt.

The source is NSE's index methodology (PDF pages 205-208). Rules as the approved card states them:

CUT-OFF    last trading day of May and November (2022-11-30 ... 2026-05-29, eight reviews).
UNIVERSE   official NIFTY 500 members that day (data/raw/nifty500/nifty500_membership.csv via ros.data.nifty500,
           regular entries), joined to NSE bhavcopy on ISIN (then ISIN at the start of the spell, then the day's
           symbol), and still members on the trade date.
SCREENS    >= 252 trading days in bhavcopy; not bottom 10% of members by 6-month average daily traded value; not
           bottom 10% by turnover ratio (that ADT / 6-month average free-float market cap); non-holdings with
           price-band hits on >= 20% of the 6 months' trading days are out. No pledge screen (no data).
SCORE      12- and 6-month price return (cut-off close / close on the last trading day 12 or 6 months earlier)
           each / annualised 1-year volatility of daily log returns (252 days, sqrt(252), >= 200 returns);
           z-scores across the eligible pool (sample std); 50/50 average Z; score = 1+Z if Z>=0 else 1/(1-Z).
SELECT     holdings ranked 1-75 stay; non-holdings ranked 1-25 forced in (replacing the lowest-ranked keeps);
           fill to 50 from the top. Ties: higher free-float cap, then ISIN.
WEIGHT     free-float cap x score, capped at min(5%, 5 x plain free-float weight), excess pro rata, iterated.
           Free-float cap = adjusted close x shares at the cut-off x (1 - promoter holding), Screener proxy.
TRADE      at the close on the last trading day of June / December; weights then drift. Sensitivity: trade at
           the first close after the cut-off. A holding removed from NIFTY 500 outside the March/September
           NIFTY 500 reviews (merger, delisting, suspension) is sold at the first close after it has left the
           index (the day the removal is in force, never read a day early) and the money buys the best-ranked
           eligible non-holding from the latest review, same close.
COSTS      30bp round trip = 15bp on every rupee bought or sold (the card). Gross rebuild kept as appendix.
DATA       cached only: cache/*.pkl bhavcopy (2021-10-04 on), the corporate-action event list of run
           20261021-104144-801e, Screener caches (data/raw/master, scr/), the index workbook. Nothing fetched.

`--checks-only` stops after the build checks and look-ahead tripwires. Gate B decision is never assigned here.
"""
from __future__ import annotations

import argparse
import glob
import itertools
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from ros.data import nifty500 as N500
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
SLUG = "method_nifty_equity_indices"
CARD = os.path.join(REPO, "cards", f"{SLUG}.yaml")
RUN = os.environ.get("MOM50_RUN", os.path.join(REPO, "outputs", "lightyear", "20261022-153434-39aa"))
SCRATCH = os.path.join(RUN, "scratch")
OUT = os.path.join(RUN, "out")
CACHE = os.path.join(REPO, "cache")
# The signed-off bhavcopy-only corporate-action list from the 21 Oct run (card inputs_required), kept under
# data/processed/ as a declared input so this script no longer reads another run's gitignored folder.
# CA_EVENTS overrides it; its sha256 is written into the run's manifest.json.
EVENTS = os.environ.get("CA_EVENTS", os.path.join(REPO, "data", "processed", "corporate_actions",
                                                  "corporate_action_events_20261021.csv"))
INDEX_PATH = os.path.join(REPO, "data", "raw", "NSE_Broad_Factor_Indices_Historical_Data.xlsx")
SHARES = os.path.join(REPO, "data", "raw", "master", "screener_shares_snapshot.csv")
FIN = os.path.join(REPO, "data", "raw", "master", "screener_annual_financials.csv")
SCR = os.path.join(REPO, "scr")

PANEL_START = pd.Timestamp("2021-10-04")
SAMPLE_END = pd.Timestamp("2026-09-18")          # last NIFTY 500 close in the workbook
CUTOFFS = [(2022, 11), (2023, 5), (2023, 11), (2024, 5), (2024, 11), (2025, 5), (2025, 11), (2026, 5)]
N_HOLD, KEEP_RANK, FORCE_RANK = 50, 75, 25
CAP_ABS, CAP_MULT = 0.05, 5.0
LIQ_CUT, BAND_LIMIT, BAND_TOL = 0.10, 0.20, 0.001
BANDS = (0.02, 0.05, 0.10, 0.20)
VOL_DAYS, MIN_RETS, MIN_LIST_DAYS = 252, 200, 252
COST_BP_RT = 30.0                                  # card: 30bp round trip
RF_ANNUAL = 0.06                                   # flat hurdle, Sharpe only
RF_D = (1 + RF_ANNUAL) ** (1 / 252) - 1
N_CONFIGS_CARD = 7                                 # card n_configs_tried
START_NAV = 1e8
BLOCK = 21
EC_LAG_DAYS = 75                                   # annual balance sheet usable 75 days after March year-end
SH_LAG_DAYS = 45                                   # shareholding pattern usable 45 days after quarter end
SUSPEND_DAYS = 3
NAMES: dict = {}


# ------------------------------------------------------------------ step 04: point-in-time data ----------
def load_raw():
    pk = os.path.join(SCRATCH, "bhav_raw.pkl")
    if os.path.exists(pk):
        return pd.read_pickle(pk)
    cols = ["DATE", "SYMBOL", "SERIES", "ISIN", "HIGH", "LOW", "CLOSE", "PREV", "VAL"]
    fs = [f for f in sorted(glob.glob(os.path.join(CACHE, "20*.pkl")))
          if pd.Timestamp(os.path.basename(f)[:10]) <= SAMPLE_END]
    raw = pd.concat([pd.read_pickle(f)[cols] for f in fs], ignore_index=True)
    raw = raw[raw["SERIES"].isin(["EQ", "BE", "BZ"]) & raw["ISIN"].notna() & raw["ISIN"].str.startswith("INE")]
    raw.to_pickle(pk)
    return raw


def build_panel():
    raw = load_raw()
    raw = raw.sort_values(["DATE", "ISIN", "VAL"]).drop_duplicates(["DATE", "ISIN"], keep="last")
    s = raw.sort_values(["SYMBOL", "DATE"]).reset_index(drop=True)
    prev_sym, prev_isin, prev_date = s["SYMBOL"].shift(), s["ISIN"].shift(), s["DATE"].shift()
    # same symbol, new ISIN, old one traded within a week: one security re-issued its ISIN (split/bonus)
    chg = (s["SYMBOL"] == prev_sym) & (s["ISIN"] != prev_isin) & ((s["DATE"] - prev_date).dt.days <= 7)
    link = dict(zip(prev_isin[chg], s.loc[chg, "ISIN"]))

    def root(i):
        seen = 0
        while i in link and seen < 10:
            i = link[i]; seen += 1
        return i

    raw["ID"] = raw["ISIN"].map(root)
    raw = raw.sort_values(["DATE", "ID", "VAL"]).drop_duplicates(["DATE", "ID"], keep="last")
    P = {k: raw.pivot(index="DATE", columns="ID", values=k).sort_index() for k in ("CLOSE", "HIGH", "LOW", "PREV", "VAL")}
    idx = P["CLOSE"].index
    for k in P:
        P[k] = P[k].reindex(index=idx, columns=P["CLOSE"].columns)
    names = raw.sort_values("DATE").drop_duplicates("ID", keep="last").set_index("ID")["SYMBOL"].to_dict()
    syms = (raw.sort_values("DATE", ascending=False).groupby("ID")["SYMBOL"].apply(lambda x: list(dict.fromkeys(x))).to_dict())
    ev = pd.read_csv(EVENTS, parse_dates=["date"])
    ev["ID"] = ev["isin"].map(root)
    ev = ev[ev["label"].isin(["SPLIT/BONUS", "DEMERGER"]) & ev["adjust_factor"].notna() & (ev["adjust_factor"] != 1.0)]
    ev = ev[ev["date"] <= SAMPLE_END].copy()
    adj = P["CLOSE"].copy()
    for _, e in ev.iterrows():
        if e["ID"] in adj.columns:
            adj.loc[adj.index < e["date"], e["ID"]] *= float(e["adjust_factor"])
    sym_day = raw[["DATE", "SYMBOL", "ID"]]
    return P, adj, names, syms, ev, root, sym_day, len(link)


class Membership:
    """Official NIFTY 500 membership as a trading-day x ID boolean panel (regular entries)."""

    def __init__(self, root, cols, days, sym_day):
        m = N500.load_membership()
        self.spells = m
        colset = set(cols)
        panel = pd.DataFrame(False, index=days, columns=cols)
        self.unjoined = []
        ids = []
        for _, r in m.iterrows():
            end = r["end_date"] if pd.notna(r["end_date"]) else pd.Timestamp("2099-12-31")
            if end <= days[0] or r["start_date"] > days[-1]:
                ids.append(None); continue
            sid = None
            for cand in (r["isin"], r["isin_at_start"]):
                if isinstance(cand, str) and cand and root(cand) in colset:
                    sid = root(cand); break
            if sid is None:
                x = sym_day[(sym_day["SYMBOL"] == r["symbol"]) & (sym_day["DATE"] >= r["start_date"]) & (sym_day["DATE"] < end)]
                if len(x):
                    sid = x["ID"].mode().iloc[0]
            ids.append(sid)
            if sid is None:
                self.unjoined.append((r["symbol"], str(r["start_date"].date()), str(end.date())))
                continue
            panel.loc[(days >= r["start_date"]) & (days < end), sid] = True
        m = m.assign(ID=ids)
        self.m = m
        self.panel = panel

    def on(self, d):
        row = self.panel.loc[d]
        return pd.Index(row.index[row.values])

    def raw_count(self, d):
        return int(((self.m["start_date"] <= d) & (self.m["end_date"].isna() | (self.m["end_date"] > d))).sum())

    def unjoined_on(self, d):
        x = self.m[(self.m["start_date"] <= d) & (self.m["end_date"].isna() | (self.m["end_date"] > d)) & self.m["ID"].isna()]
        return list(x["symbol"])


# ------------------------------------------------------------------ Screener: free-float proxy -------------
def _period_end(p):
    t = pd.to_datetime(p, format="%b %Y", errors="coerce")
    return t + pd.offsets.MonthEnd(0) if pd.notna(t) else pd.NaT


def _promoter_rows(sym):
    out = {}
    for f in ("shareholding_1.csv", "shareholding_0.csv"):     # annual (March) first, quarterly overrides
        p = os.path.join(SCR, sym, "csv", f)
        if not os.path.exists(p):
            continue
        try:
            t = pd.read_csv(p)
        except Exception as e:                                    # noqa: BLE001
            print(f"WARN promoter holding: {p} unreadable, skipped ({e!r})", file=sys.stderr)
            continue
        r = t[t.iloc[:, 0].astype(str).str.startswith("Promoters")]
        if r.empty:
            continue
        for c in t.columns[1:]:
            pe = _period_end(c)
            v = str(r.iloc[0][c]).replace("%", "").strip()
            try:
                out[pe] = float(v)
            except ValueError:
                pass
    return out


class FreeFloat:
    """Shares at a cut-off (in today's adjusted-price units) and promoter holding published before it."""

    def __init__(self, syms, ev):
        sh = pd.read_csv(SHARES)
        self.snap = sh.drop_duplicates("symbol", keep="last").set_index("symbol")
        fin = pd.read_csv(FIN)
        fin = fin[fin["field"] == "Equity Capital"].copy()
        fin["pe"] = fin["period"].map(_period_end)
        self.fin = fin.dropna(subset=["pe", "value"])
        self.syms = syms
        self.ev = ev[ev["label"] == "SPLIT/BONUS"]
        self.cache = {}
        self.log = []

    def _meta(self, s):
        p = os.path.join(SCR, s, "meta.json")
        if not os.path.exists(p):
            return None
        try:
            m = json.load(open(p, encoding="utf-8"))
            if m.get("mcap_cr") and m.get("price"):
                return m
        except Exception as e:                                    # noqa: BLE001
            print(f"WARN share count: {p} unreadable, symbol skipped ({e!r})", file=sys.stderr)
        return None

    def symbol_for(self, i):
        """The Screener symbol with a usable share count: the snapshot first, then the cached page's
        market cap / price (scr/<symbol>/meta.json) where the snapshot's share count is blank."""
        for s in self.syms.get(i, []):
            if s in self.snap.index and pd.notna(self.snap.loc[s, "shares_cr"]):
                return s
        for s in self.syms.get(i, []):
            if self._meta(s) is not None:
                return s
        return None

    def now_shares(self, sym):
        if sym in self.snap.index and pd.notna(self.snap.loc[sym, "shares_cr"]):
            return float(self.snap.loc[sym, "shares_cr"]), self.snap.loc[sym, "view"], "snapshot"
        m = self._meta(sym)
        return float(m["mcap_cr"]) / float(m["price"]), m.get("view", "consolidated"), "cached page market cap / price"

    def promoter(self, i, sym, cutoff):
        if (i, "prom") not in self.cache:
            rows = {}
            for s in self.syms.get(i, []):
                rows = _promoter_rows(s)
                if rows:
                    break
            self.cache[(i, "prom")] = rows
        rows = self.cache[(i, "prom")]
        ok = {k: v for k, v in rows.items() if k + pd.Timedelta(days=SH_LAG_DAYS) <= cutoff}
        if ok:
            return ok[max(ok)], f"Screener shareholding {max(ok).strftime('%b %Y')}"
        snap = self.snap.loc[sym, "promoter_pct"] if (sym is not None and sym in self.snap.index) else np.nan
        if pd.notna(snap):
            return float(snap), "Screener snapshot 2026-10-06 (no earlier figure on disk)"
        return 0.0, "no promoter row: 100% free float"

    def shares(self, i, sym, cutoff):
        """Crore shares in today's adjusted units at the cut-off; (value, ratio applied, basis)."""
        now, view, src = self.now_shares(sym)
        f = self.fin[(self.fin["symbol"] == sym)]
        if (f["view"] == view).any():
            f = f[f["view"] == view]
        f = f.sort_values("pe")
        if f.empty:
            return now, 1.0, f"current share count ({src}; no Equity Capital on disk)"
        ec_now = float(f["value"].iloc[-1])
        av = f[f["pe"] + pd.Timedelta(days=EC_LAG_DAYS) <= cutoff]
        if av.empty or ec_now <= 0:
            return now, 1.0, "current share count (no Equity Capital before the cut-off)"
        ec_then, pe_then = float(av["value"].iloc[-1]), av["pe"].iloc[-1]
        ec_ratio = ec_then / ec_now
        evs = self.ev[(self.ev["ID"] == i) & (self.ev["date"] > pe_then)]["adjust_factor"].astype(float).tolist()
        # Which split/bonus events after that balance sheet were bonuses (Equity Capital grows) and which were splits
        # (it does not)? Pick the subset whose correction leaves the share count change closest to none: issues and
        # buybacks are small next to a bonus.
        best = (abs(math.log(ec_ratio)) if ec_ratio > 0 else 9.0, ec_ratio, ())
        for k in range(1, len(evs) + 1):
            for sub in itertools.combinations(range(len(evs)), k):
                r = ec_ratio / float(np.prod([evs[j] for j in sub]))
                if r > 0 and abs(math.log(r)) < best[0]:
                    best = (abs(math.log(r)), r, sub)
        ratio = best[1]
        basis = f"current count x Equity Capital {pe_then.strftime('%b %Y')}/{f['pe'].iloc[-1].strftime('%b %Y')}"
        if best[2]:
            basis += f", {len(best[2])} bonus event(s) undone"
        if not (1 / 3 <= ratio <= 3):
            return now, 1.0, f"current share count (Equity Capital ratio {ratio:.2f} implausible, ignored)"
        return now * ratio, ratio, basis

    def ff_cap_inputs(self, i, cutoff):
        sym = self.symbol_for(i)
        if sym is None:
            return None
        key = (i, cutoff)
        if key not in self.cache:
            sh, ratio, sb = self.shares(i, sym, cutoff)
            prom, pb = self.promoter(i, sym, cutoff)
            self.cache[key] = {"screener_symbol": sym, "shares_cr": sh, "share_ratio": ratio, "shares_basis": sb,
                               "promoter_pct": prom, "promoter_basis": pb, "ff_frac": 1.0 - prom / 100.0}
        return self.cache[key]


# ------------------------------------------------------------------ the rules ------------------------------
def last_td(days, y, m):
    d = days[(days.year == y) & (days.month == m)]
    return d.max() if len(d) else None


def months_back(y, m, k):
    t = y * 12 + (m - 1) - k
    return t // 12, t % 12 + 1


def band_hits(P, lo, hi):
    c, h, l, pv = (P[k].loc[(P[k].index > lo) & (P[k].index <= hi)] for k in ("CLOSE", "HIGH", "LOW", "PREV"))
    mv = c / pv - 1.0
    near = pd.DataFrame(False, index=mv.index, columns=mv.columns)
    for b in BANDS:
        near |= (mv.abs() - b).abs() <= BAND_TOL
    up = near & (mv > 0) & (c >= h - 1e-9)
    dn = near & (mv < 0) & (c <= l + 1e-9)
    return (up.sum() + dn.sum()), len(mv)


def review(P, adj, mem, ff, cutoff, trade, held, firstpos):
    """Everything the rules decide at one review, using data to the cut-off close only (plus membership on the
    trade date). Returns a table over the cut-off universe and the chosen 50 with weights."""
    days = adj.index
    i = days.get_loc(cutoff)
    y, m = cutoff.year, cutoff.month
    d6, d12 = last_td(days, *months_back(y, m, 6)), last_td(days, *months_back(y, m, 12))
    uni = mem.on(cutoff)
    t = pd.DataFrame(index=uni)
    t["symbol"] = [NAMES.get(c, c) for c in uni]
    t["member_on_trade_date"] = t.index.isin(mem.on(trade))
    t["days_in_bhavcopy"] = [int(i - firstpos.get(c, 10 ** 9) + 1) if firstpos.get(c, 10 ** 9) <= i else 0 for c in uni]
    w6 = (days > d6) & (days <= cutoff)
    val6 = P["VAL"].loc[w6, uni].fillna(0.0)
    t["adt_6m_cr"] = (val6.mean() / 1e7).values
    hits, ndays = band_hits(P, d6, cutoff)
    t["band_hits_6m"] = hits.reindex(uni).fillna(0).astype(int).values
    t["band_hit_share"] = t["band_hits_6m"] / ndays
    pc, p6, p12 = adj.loc[cutoff, uni], adj.loc[d6, uni], adj.loc[d12, uni]
    t["close_cutoff_adj"], t["close_6m_ago_adj"], t["close_12m_ago_adj"] = pc.values, p6.values, p12.values
    t["ret_12m"] = (pc / p12 - 1.0).values
    t["ret_6m"] = (pc / p6 - 1.0).values
    lr = np.log(adj.iloc[i - VOL_DAYS: i + 1][uni]).diff().iloc[1:]
    t["n_returns_1y"] = lr.notna().sum().values
    t["vol_1y"] = (lr.std() * math.sqrt(252)).values
    t["scoreable"] = t[["ret_12m", "ret_6m", "vol_1y"]].notna().all(axis=1) & (t["n_returns_1y"] >= MIN_RETS) & (t["vol_1y"] > 0)
    # free-float market cap at the cut-off and its 6-month average (for the turnover ratio)
    rows = []
    for c in uni:
        x = ff.ff_cap_inputs(c, cutoff)
        rows.append(x or {"screener_symbol": None, "shares_cr": np.nan, "share_ratio": np.nan, "shares_basis": "no Screener share count",
                          "promoter_pct": np.nan, "promoter_basis": "", "ff_frac": np.nan})
    fx = pd.DataFrame(rows, index=uni)
    t = t.join(fx)
    t["ffmcap_cr"] = t["close_cutoff_adj"] * t["shares_cr"] * t["ff_frac"]
    avg_px6 = adj.loc[w6, uni].mean()
    t["ffmcap_6m_avg_cr"] = avg_px6.values * t["shares_cr"] * t["ff_frac"]
    t["turnover_ratio"] = t["adt_6m_cr"] / t["ffmcap_6m_avg_cr"]
    # screens: percentiles within the universe that has prices
    t["pass_listing"] = t["days_in_bhavcopy"] >= MIN_LIST_DAYS
    adt_cut = t["adt_6m_cr"].quantile(LIQ_CUT)
    t["pass_adt"] = t["adt_6m_cr"] > adt_cut
    tr_cut = t["turnover_ratio"].dropna().quantile(LIQ_CUT)
    t["pass_turnover_ratio"] = t["turnover_ratio"].isna() | (t["turnover_ratio"] > tr_cut)
    t["held_before"] = t.index.isin(held)
    t["pass_band"] = t["held_before"] | (t["band_hit_share"] < BAND_LIMIT)
    t["has_trade_price"] = adj.loc[trade, uni].notna().values
    t["eligible"] = (t["pass_listing"] & t["pass_adt"] & t["pass_turnover_ratio"] & t["pass_band"] & t["scoreable"]
                     & t["member_on_trade_date"] & t["has_trade_price"])
    e = t[t["eligible"]]
    mr12, mr6 = e["ret_12m"] / e["vol_1y"], e["ret_6m"] / e["vol_1y"]
    z12, z6 = (mr12 - mr12.mean()) / mr12.std(), (mr6 - mr6.mean()) / mr6.std()
    z = 0.5 * z12 + 0.5 * z6
    score = np.where(z >= 0, 1.0 + z, 1.0 / (1.0 - z))
    t.loc[e.index, "mr12"], t.loc[e.index, "mr6"] = mr12, mr6
    t.loc[e.index, "z12"], t.loc[e.index, "z6"], t.loc[e.index, "z_avg"] = z12, z6, z
    t.loc[e.index, "score"] = score
    r = t[t["eligible"]].copy()
    r["isin"] = r.index
    r["_ff"] = r["ffmcap_cr"].fillna(-1.0)
    r = r.sort_values(["score", "_ff", "isin"], ascending=[False, False, True])
    t["rank"] = pd.Series(np.arange(1, len(r) + 1), index=r.index)
    order = list(r.index)
    rank = {c: k + 1 for k, c in enumerate(order)}
    # selection with the 75 / 25 buffer
    keep = [c for c in order if c in held and rank[c] <= KEEP_RANK]
    forced = [c for c in order if c not in held and rank[c] <= FORCE_RANK]
    chosen = set(keep) | set(forced)
    if len(chosen) > N_HOLD:                      # forced entries push out the lowest-ranked keeps
        drop = sorted([c for c in keep if c not in forced], key=lambda c: rank[c], reverse=True)
        for c in drop:
            if len(chosen) <= N_HOLD:
                break
            chosen.discard(c)
    for c in order:
        if len(chosen) >= N_HOLD:
            break
        chosen.add(c)
    target = sorted(chosen, key=lambda c: rank[c])
    # weights
    s = t.loc[target]
    ffc = s["ffmcap_cr"].copy()
    stand_in = list(ffc.index[ffc.isna()])
    if stand_in:
        ffc[stand_in] = ffc.median()
    raw_w = ffc * s["score"]
    w = raw_w / raw_w.sum()
    ffw = ffc / ffc.sum()
    cap = np.minimum(CAP_ABS, CAP_MULT * ffw)
    capped = pd.Series(False, index=w.index)
    for _ in range(100):
        over = (w > cap + 1e-12) & ~capped
        if not over.any():
            break
        capped |= over
        excess = (w[capped] - cap[capped]).clip(lower=0).sum()
        w[capped] = cap[capped]
        free = ~capped
        w[free] += excess * w[free] / w[free].sum()
    t["chosen"] = t.index.isin(target)
    t.loc[target, "weight_target"] = w
    t.loc[target, "ff_weight_plain"] = ffw
    t.loc[target, "cap_limit"] = cap
    t.loc[target, "cap_binds"] = capped
    t.loc[target, "cap_binds_on"] = np.where(capped, np.where(cap >= CAP_ABS - 1e-12, "5% absolute", "5x free-float weight"), "")
    t["ff_stand_in"] = t.index.isin(stand_in)
    meta = {"cutoff": cutoff, "trade": trade, "d6": d6, "d12": d12, "adt_cut_cr": float(adt_cut), "tr_cut": float(tr_cut),
            "band_days": int(ndays), "order": order, "rank": rank, "keep": keep, "forced": forced, "stand_in": stand_in,
            "rank_of_last_pick": int(max(rank[c] for c in target))}
    return t, w, meta


# ------------------------------------------------------------------ step 05: simulator ---------------------
def simulate(P, adj, mem, ff, firstpos, schedule, cost_bp_rt=COST_BP_RT, keep_tables=True):
    """schedule: list of (cutoff, trade_date). Value-based book at adjusted closes; fractional shares."""
    days = adj.index
    px = adj.values
    raw = P["CLOSE"].values
    cols = adj.columns
    cpos = {c: j for j, c in enumerate(cols)}
    side = cost_bp_rt / 2 / 1e4
    trade_at = {tr: co for co, tr in schedule}
    start = days.get_loc(schedule[0][1])
    end = days.get_loc(SAMPLE_END)
    memv = mem.panel.reindex(columns=cols).values
    pos, last, miss = {}, {}, {}
    cash = START_NAV
    nav, costs, traded = {}, {}, {}
    reviews, trades, holdings, adhoc = [], [], [], []
    contrib = {}
    latest = None

    def mark():
        return cash + sum(pos.values())

    def do_trades(t, target_val, why, kind):
        nonlocal cash
        d = days[t]
        tv = 0.0
        for c in set(pos) | set(target_val):
            before = pos.get(c, 0.0)
            after = target_val.get(c, 0.0)
            dv = after - before
            if abs(dv) < 1e-6:
                continue
            tv += abs(dv)
            j = cpos[c]
            rp = raw[t][j]
            act = ("BUY" if before == 0 else "ADD") if dv > 0 else ("SELL" if after == 0 else "TRIM")
            trades.append({"date": d, "isin": c, "action": act, "value": abs(dv), "price": rp, "why": why.get(c, kind),
                           "kind": kind})
        return tv

    for t in range(start, end + 1):
        d = days[t]
        row = px[t]
        if t > start:
            for c in list(pos):
                j = cpos[c]
                p = row[j]
                if np.isnan(p):
                    miss[c] = miss.get(c, 0) + 1
                    continue
                miss[c] = 0
                g = pos[c] * (p / last[c] - 1.0)
                contrib[c] = contrib.get(c, 0.0) + g
                pos[c] += g
                last[c] = p
        cost_today, tv_today = 0.0, 0.0
        if d in trade_at:
            co = trade_at[d]
            held = set(pos)
            tab, w, meta = review(P, adj, mem, ff, co, d, held, firstpos)
            latest = meta
            N = mark()
            # post-trade NAV solves N' = N - side * sum|w N' - v|
            Np = N
            for _ in range(50):
                tv = sum(abs(w.get(c, 0.0) * Np - pos.get(c, 0.0)) for c in set(pos) | set(w.index))
                Np_new = N - side * tv
                if abs(Np_new - Np) < 1e-6:
                    break
                Np = Np_new
            target_val = {c: float(w[c] * Np) for c in w.index}
            why = {}
            w_before = {c: pos[c] / N for c in pos}
            tv_today = do_trades(t, target_val, why, "review")
            cost_today = N - Np
            pos = {c: v for c, v in target_val.items()}
            for c in pos:
                last[c] = row[cpos[c]]; miss[c] = 0
            cash = N - cost_today - sum(pos.values())
            reviews.append({"cutoff": co, "trade": d, "table": tab if keep_tables else None, "weights": w, "meta": meta,
                            "held_before": sorted(held), "w_before": w_before, "nav_before": N, "nav_after": mark(),
                            "cost": cost_today, "traded": tv_today})
            for c in pos:
                holdings.append({"date": d, "isin": c, "weight": pos[c] / mark(), "event": "review"})
        elif latest is not None and t >= 1 and pos:
            # ad hoc: a holding that left NIFTY 500 today (member yesterday, not today), outside a March/September
            # review, or one suspended for SUSPEND_DAYS, is sold at today's close and replaced. The exit reads
            # today's membership, never tomorrow's: the day the removal is in force is the day it is acted on,
            # the engines' "sold on the day learned" rule. Until 2026-10-28 this read memv[t + 1] on day t.
            out = []
            for c in list(pos):
                j = cpos[c]
                if miss.get(c, 0) >= SUSPEND_DAYS:
                    out.append((c, "suspended: no NSE price for 3 trading days, sold at its last price"))
                elif memv[t - 1][j] and not memv[t][j] and d.month not in (3, 9):
                    out.append((c, f"removed from NIFTY 500 effective {d.date()} (outside a regular review): sold at the first close after removal"))
            if out:
                N = mark()
                rank = latest["rank"]
                cands = [c for c in latest["order"] if c not in pos and memv[t][cpos[c]] and not np.isnan(row[cpos[c]])]
                target_val = dict(pos)
                why = {}
                for (c, reason), rep in zip(out, cands):
                    v = target_val.pop(c)
                    target_val[rep] = v * (1 - side) / (1 + side)      # sell v paying side*v, buy b paying side*b
                    why[c] = reason
                    why[rep] = (f"ad hoc replacement for {NAMES.get(c, c)}: best-ranked eligible non-holding from the "
                                f"{latest['cutoff'].date()} review (rank {rank[rep]})")
                    adhoc.append({"date": d, "out": NAMES.get(c, c), "out_isin": c, "in": NAMES.get(rep, rep), "in_isin": rep,
                                  "in_rank": rank[rep], "reason": reason, "value": v})
                tv_today = do_trades(t, target_val, why, "ad hoc")
                cost_today = sum(pos.values()) - sum(target_val.values())
                pos = target_val
                for c in pos:
                    if c in why:                                     # the replacements, bought at today's close
                        last[c] = row[cpos[c]]; miss[c] = 0
                for c in pos:
                    holdings.append({"date": d, "isin": c, "weight": pos[c] / mark(), "event": "ad hoc"})
        nav[d] = mark()
        costs[d] = cost_today
        traded[d] = tv_today
    navs = pd.Series(nav)
    yrs = (navs.index[-1] - navs.index[0]).days / 365.25
    tv = pd.Series(traded)
    return {"nav": navs, "ret": navs.pct_change().iloc[1:], "reviews": reviews, "trades": pd.DataFrame(trades),
            "holdings": pd.DataFrame(holdings), "adhoc": adhoc, "costs": pd.Series(costs), "contrib": contrib,
            "turnover_two_way": float(tv.sum() / navs.mean() / yrs), "turnover_one_way": float(tv.sum() / 2 / navs.mean() / yrs),
            "cost_total_frac": float(pd.Series(costs).sum() / START_NAV)}


# ------------------------------------------------------------------ helpers -------------------------------
def card_sharpe(r):
    return float((r.mean() * 252 - RF_ANNUAL) / (r.std() * math.sqrt(252)))


def stats(v, r, label):
    c, vol = float(_cagr(v)), float(_ann_vol(r))
    return {"name": label, "cagr": c, "vol": vol, "sharpe_card": card_sharpe(r), "max_dd": float(_mdd(v)),
            "total_return": float(v.iloc[-1] / v.iloc[0] - 1.0), "start": str(v.index[0].date()), "end": str(v.index[-1].date()),
            "n_days": len(r)}


def load_bench(days):
    bm = load_banner_workbook(INDEX_PATH, sheet="Broad Market")[0]
    fac = load_banner_workbook(INDEX_PATH, sheet="Factor Indices")[0]
    allb = {"NIFTY 500": bm["NIFTY 500 Close"].dropna()}
    for n in ["NIFTY500 MOMENTUM 50", "NIFTY500 VALUE 50", "NIFTY500 QUALITY 50", "NIFTY500 LOW VOLATILITY 50"]:
        allb[n] = fac[n + " Close"].dropna()
    return {k: v.reindex(days.union(v.index)).ffill().reindex(days) for k, v in allb.items()}, allb


def schedule_for(days, mode):
    out = []
    for y, m in CUTOFFS:
        co = last_td(days, y, m)
        if mode == "month_after":
            ty, tm = months_back(y, m, -1)
            tr = last_td(days, ty, tm)
        else:
            tr = days[days.get_loc(co) + 1]
        out.append((co, tr))
    return out


def rel(p):
    return os.path.relpath(p, REPO).replace("\\", "/")


# ------------------------------------------------------------------ main ---------------------------------
def main():
    global NAMES
    ap = argparse.ArgumentParser()
    ap.add_argument("--checks-only", action="store_true")
    ap.add_argument("--no-charts", action="store_true")
    a = ap.parse_args()
    os.makedirs(SCRATCH, exist_ok=True); os.makedirs(OUT, exist_ok=True)
    P, adj, NAMES, syms, ev, root, sym_day, nlinks = build_panel()
    days = adj.index
    mem = Membership(root, adj.columns, days, sym_day)
    fpv = adj.notna().values
    firstpos = dict(zip(adj.columns, np.where(fpv.any(axis=0), fpv.argmax(axis=0), 10 ** 9)))
    ff = FreeFloat(syms, ev)
    res = {"panel": {"securities": int(adj.shape[1]), "trading_days": len(days), "first": str(days[0].date()),
                     "last": str(days[-1].date()), "isin_links": nlinks, "events_applied": len(ev)}}
    print("PANEL", res["panel"])
    sched = schedule_for(days, "month_after")
    sched_early = schedule_for(days, "next_day")
    print("SCHEDULE", [(str(c.date()), str(t.date())) for c, t in sched])

    # ---------------- step 04 checks ----------------
    L, ok_all = [], True

    def rec(name, passed, detail=""):
        nonlocal ok_all
        ok_all = ok_all and bool(passed)
        L.append(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))

    cov = []
    for co, tr in sched:
        cov.append({"cutoff": str(co.date()), "trade": str(tr.date()), "official_members": mem.raw_count(co),
                    "joined_to_prices": len(mem.on(co)), "unjoined": ";".join(mem.unjoined_on(co))})
    covdf = pd.DataFrame(cov)
    rec("every official NIFTY 500 member on each cut-off joins to a bhavcopy price series (TATAMTRDVR allowed)",
        all(set(x.split(";")) <= {"", "TATAMTRDVR"} for x in covdf["unjoined"]),
        "; ".join(f"{r.cutoff}: {r.joined_to_prices}/{r.official_members}" for r in covdf.itertuples()))
    rec("panel ends at the benchmark's last date; no price after 2026-09-18 is loaded", days[-1] <= SAMPLE_END, str(days[-1].date()))

    base = simulate(P, adj, mem, ff, firstpos, sched)
    R = base["reviews"]
    # each review: 50 names, weights sum to 1, caps respected
    bad = [str(r["trade"].date()) for r in R if len(r["weights"]) != N_HOLD]
    rec("exactly 50 holdings after every review", not bad, str(bad))
    bad = [str(r["trade"].date()) for r in R if abs(r["weights"].sum() - 1) > 1e-9]
    rec("target weights sum to 100% at every review", not bad, str(bad))
    bad = []
    for r in R:
        tb = r["table"].loc[r["weights"].index]
        if (r["weights"] > tb["cap_limit"] + 1e-9).any() or (r["weights"] > CAP_ABS + 1e-9).any():
            bad.append(str(r["trade"].date()))
    rec("no weight above min(5%, 5x plain free-float weight)", not bad, str(bad))
    bad = []
    for r in R:
        tb = r["table"]
        if not tb.loc[r["weights"].index, "eligible"].all():
            bad.append(str(r["trade"].date()))
    rec("every chosen name is eligible and a NIFTY 500 member on both the cut-off and trade date", not bad, str(bad))
    bad = []
    for r in R:
        rk = r["meta"]["rank"]
        hb = set(r["held_before"])
        ch = set(r["weights"].index)
        for c in ch - hb:
            pass
        if any(rk[c] > KEEP_RANK for c in ch & hb):
            bad.append((str(r["trade"].date()), "kept beyond 75"))
        if any(c not in ch for c in rk if rk[c] <= FORCE_RANK):
            bad.append((str(r["trade"].date()), "top-25 non-holding left out"))
        if any(rk[c] <= KEEP_RANK for c in hb - ch if c in rk) and not any(rk[c] <= FORCE_RANK for c in ch - hb):
            bad.append((str(r["trade"].date()), "a top-75 holding dropped without a forced entry"))
    rec("75/25 buffer: holdings ranked >75 leave, every eligible top-25 name is held", not bad, str(bad[:5]))
    # look-ahead tripwire: every review recomputed with all prices after its cut-off deleted
    la = []
    for r in R:
        co, tr = r["cutoff"], r["trade"]
        Pc = {k: v.loc[:co] for k, v in P.items()}
        adjc = adj.loc[:co]
        # the trade-date price check needs the trade-date row; keep only that one row, prices set to 1
        stub = pd.DataFrame(np.where(adj.loc[[tr]].notna(), 1.0, np.nan), index=[tr], columns=adj.columns)
        adjc = pd.concat([adjc, stub])
        Pc = {k: pd.concat([v, stub.reindex(columns=v.columns)]) for k, v in Pc.items()}
        tb2, w2, _ = review(Pc, adjc, mem, ff, co, tr, set(r["held_before"]), firstpos)
        same = list(w2.index) == list(r["weights"].index) and np.allclose(w2.values, r["weights"].values)
        la.append((str(co.date()), same))
    rec("look-ahead tripwire: each review recomputed with every price after its cut-off deleted gives the same 50 and weights",
        all(x[1] for x in la), "; ".join(f"{a_}:{'same' if b_ else 'DIFFERENT'}" for a_, b_ in la))
    # hand-check the score of the top 3 at two reviews from raw arrays
    hc = []
    for r in (R[0], R[-1]):
        tb = r["table"]
        e = tb[tb["eligible"]]
        for c in r["meta"]["order"][:3]:
            co = r["cutoff"]
            p0 = float(adj.loc[co, c]); p6 = float(adj.loc[r["meta"]["d6"], c]); p12 = float(adj.loc[r["meta"]["d12"], c])
            seg = adj[c].iloc[days.get_loc(co) - VOL_DAYS: days.get_loc(co) + 1].values
            lr = np.diff(np.log(seg)); lr = lr[~np.isnan(lr)]
            vol = lr.std(ddof=1) * math.sqrt(252)
            m12 = (p0 / p12 - 1) / vol; m6 = (p0 / p6 - 1) / vol
            a12 = (e["ret_12m"] / e["vol_1y"]).values; a6 = (e["ret_6m"] / e["vol_1y"]).values
            zz = 0.5 * (m12 - a12.mean()) / a12.std(ddof=1) + 0.5 * (m6 - a6.mean()) / a6.std(ddof=1)
            sc = 1 + zz if zz >= 0 else 1 / (1 - zz)
            hc.append(abs(sc - tb.loc[c, "score"]) < 1e-9)
    rec("hand-check: top-3 scores at the first and last review match an independent recomputation", all(hc), f"{sum(hc)}/{len(hc)}")
    # corporate-action days inside holdings: no held name moves > 40% in a day on adjusted prices
    big = []
    ra = adj.pct_change(fill_method=None)
    for k, r in enumerate(R):
        nxt = R[k + 1]["trade"] if k + 1 < len(R) else SAMPLE_END
        seg = ra.loc[(ra.index > r["trade"]) & (ra.index <= nxt), list(r["weights"].index)]
        s = seg.stack()
        for (d_, c), v in s[s.abs() > 0.25].items():
            big.append((str(d_.date()), NAMES.get(c, c), float(v)))
    rec("no held name has an unexplained one-day adjusted move over 40%", not [b for b in big if abs(b[2]) > 0.40],
        f"{len(big)} held-name days over 25%: " + "; ".join(f"{b[0]} {b[1]} {b[2]:+.1%}" for b in big[:10]))
    checks = "\n".join(L)
    open(os.path.join(RUN, "checks.txt"), "w", encoding="utf-8").write(checks + "\n")
    print("\nCHECKS\n" + checks)
    covdf.to_csv(os.path.join(OUT, "universe_coverage_by_review.csv"), index=False)
    res["checks"] = L
    res["coverage"] = cov
    if not ok_all:
        print("\nCHECKS FAILED. No result is shown.")
        json.dump(res, open(os.path.join(OUT, "results_raw.json"), "w"), indent=1, default=str)
        sys.exit(2)
    print("\nALL CHECKS PASSED.")
    if a.checks_only:
        return

    # ---------------- step 05: variants ----------------
    gross = simulate(P, adj, mem, ff, firstpos, sched, cost_bp_rt=0.0, keep_tables=False)
    early = simulate(P, adj, mem, ff, firstpos, sched_early, keep_tables=False)
    early_g = simulate(P, adj, mem, ff, firstpos, sched_early, cost_bp_rt=0.0, keep_tables=False)
    bench, braw = load_bench(days)
    rg = base["ret"]
    idx = rg.index
    v = base["nav"] / base["nav"].iloc[0]
    nb = bench["NIFTY 500"].reindex(base["nav"].index); vb = nb / nb.iloc[0]; rb = vb.pct_change().iloc[1:]
    mo = bench["NIFTY500 MOMENTUM 50"].reindex(base["nav"].index); vm = mo / mo.iloc[0]; rm = vm.pct_change().iloc[1:]
    vg = gross["nav"] / gross["nav"].iloc[0]
    rows = [stats(v, rg, "Momentum 50 rebuild, net of 30bp"), stats(vb, rb, "NIFTY 500 (price)"),
            stats(vg, gross["ret"], "Momentum 50 rebuild, gross"), stats(vm, rm, "NSE NIFTY500 MOMENTUM 50 (published, price)")]
    perf = pd.DataFrame(rows)
    print("\nPERFORMANCE (from the first trade close, 2022-12-30, to 2026-09-18)\n" + perf.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    perf.to_csv(os.path.join(OUT, "performance.csv"), index=False)
    res["performance"] = rows
    res["turnover"] = {"one_way": base["turnover_one_way"], "two_way": base["turnover_two_way"], "cost_total_frac": base["cost_total_frac"]}
    # early-trade variant on its own window and on the common window
    ve = early["nav"] / early["nav"].iloc[0]
    nbe = bench["NIFTY 500"].reindex(ve.index); nbe = nbe / nbe.iloc[0]
    common0 = max(early["nav"].index[0], base["nav"].index[0])
    def window_cagr(nav_):
        x = nav_.loc[common0:SAMPLE_END]; return float(_cagr(x / x.iloc[0]))
    nbc = bench["NIFTY 500"].loc[common0:SAMPLE_END]
    timing = [{"variant": "trade at the close on the last trading day of June/December (base)", "first_trade": str(base['nav'].index[0].date()),
               "cagr_own_window": float(_cagr(v)), "nifty500_cagr_own_window": float(_cagr(vb)),
               "cagr_common_window": window_cagr(base["nav"]), "nifty500_cagr_common_window": float(_cagr(nbc / nbc.iloc[0])),
               "sharpe_card": card_sharpe(rg), "turnover_two_way": base["turnover_two_way"]},
              {"variant": "trade at the first close after the cut-off", "first_trade": str(early['nav'].index[0].date()),
               "cagr_own_window": float(_cagr(ve)), "nifty500_cagr_own_window": float(_cagr(nbe)),
               "cagr_common_window": window_cagr(early["nav"]), "nifty500_cagr_common_window": float(_cagr(nbc / nbc.iloc[0])),
               "sharpe_card": card_sharpe(early["ret"]), "turnover_two_way": early["turnover_two_way"]}]
    for x in timing:
        x["edge_own_window"] = x["cagr_own_window"] - x["nifty500_cagr_own_window"]
        x["edge_common_window"] = x["cagr_common_window"] - x["nifty500_cagr_common_window"]
    tdf = pd.DataFrame(timing)
    print("\nTRADE-DATE SENSITIVITY\n" + tdf.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    tdf.to_csv(os.path.join(OUT, "trade_date_sensitivity.csv"), index=False)
    res["trade_date_sensitivity"] = timing

    # cost sweep and breakeven
    nbc_full = float(_cagr(vb))
    sweep = []
    sims = {0.0: gross, COST_BP_RT: base}
    for bp in (0.0, 15.0, 30.0, 45.0, 60.0, 90.0, 120.0, 200.0):
        s_ = sims.get(bp) or simulate(P, adj, mem, ff, firstpos, sched, cost_bp_rt=bp, keep_tables=False)
        sims[bp] = s_
        vv = s_["nav"] / s_["nav"].iloc[0]
        sweep.append({"round_trip_cost_bp": bp, "cagr": float(_cagr(vv)), "sharpe_card": card_sharpe(s_["ret"]),
                      "minus_nifty500_cagr": float(_cagr(vv)) - nbc_full})
    swdf = pd.DataFrame(sweep)

    def edge_at(bp):
        s_ = simulate(P, adj, mem, ff, firstpos, sched, cost_bp_rt=bp, keep_tables=False)
        return float(_cagr(s_["nav"] / s_["nav"].iloc[0])) - nbc_full
    if swdf["minus_nifty500_cagr"].iloc[0] <= 0:
        breakeven = 0.0
    elif swdf["minus_nifty500_cagr"].iloc[-1] > 0:
        lo, hi = 200.0, 400.0
        while edge_at(hi) > 0 and hi < 5000:
            lo, hi = hi, hi * 2
        for _ in range(14):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if edge_at(mid) > 0 else (lo, mid)
        breakeven = (lo + hi) / 2
    else:
        k = int(np.argmax(swdf["minus_nifty500_cagr"].values <= 0))
        lo, hi = float(swdf["round_trip_cost_bp"].iloc[k - 1]), float(swdf["round_trip_cost_bp"].iloc[k])
        for _ in range(14):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if edge_at(mid) > 0 else (lo, mid)
        breakeven = (lo + hi) / 2
    print("\nCOST SWEEP\n" + swdf.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print(f"  breakeven round-trip cost vs NIFTY 500 on CAGR: {breakeven:.1f}bp")
    swdf.to_csv(os.path.join(OUT, "cost_sweep.csv"), index=False)
    res["cost_sweep"] = sweep
    res["breakeven_bp"] = float(breakeven)

    # reconciliation: gross rebuild vs NSE's published index
    rgg = gross["ret"]
    recon = {"daily_corr_gross_vs_published": float(rgg.corr(rm.reindex(rgg.index))),
             "cagr_gross": float(_cagr(vg)), "cagr_published": float(_cagr(vm)),
             "annual_gap_gross_minus_published": float(_cagr(vg) - _cagr(vm)),
             "tracking_error_gross_vs_published": float((rgg - rm.reindex(rgg.index)).std() * math.sqrt(252)),
             "daily_corr_net_vs_published": float(rg.corr(rm.reindex(rg.index)))}
    cal = lambda x: (1 + x).groupby(x.index.year).prod() - 1
    recon_year = pd.DataFrame({"rebuild_net": cal(rg), "rebuild_gross": cal(rgg), "nse_published_momentum50": cal(rm.reindex(rg.index)),
                               "nifty500": cal(rb.reindex(rg.index))})
    recon_year["gross_minus_published"] = recon_year["rebuild_gross"] - recon_year["nse_published_momentum50"]
    recon_year.index.name = "year"
    recon_year.to_csv(os.path.join(OUT, "calendar_year_returns.csv"))
    print("\nRECONCILIATION vs NSE's published index", json.dumps(recon, indent=1))
    print(recon_year.to_string(float_format=lambda x: f"{x:.4f}"))
    res["reconciliation"] = recon
    res["calendar_year"] = recon_year.reset_index().to_dict("records")
    # half-year (holding period) returns
    hp = []
    for k, r in enumerate(R):
        a0 = r["trade"]; a1 = R[k + 1]["trade"] if k + 1 < len(R) else SAMPLE_END
        def per(s):
            return float(s.loc[a1] / s.loc[a0] - 1)
        hp.append({"held_from": str(a0.date()), "held_to": str(a1.date()), "rebuild_net": per(base["nav"]),
                   "rebuild_gross": per(gross["nav"]), "nse_published_momentum50": per(mo), "nifty500": per(nb)})
    hpdf = pd.DataFrame(hp)
    hpdf["net_minus_nifty500"] = hpdf["rebuild_net"] - hpdf["nifty500"]
    hpdf["gross_minus_published"] = hpdf["rebuild_gross"] - hpdf["nse_published_momentum50"]
    hpdf.to_csv(os.path.join(OUT, "holding_period_returns.csv"), index=False)
    print("\nHOLDING PERIODS\n" + hpdf.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    res["holding_periods"] = hp

    # ---------------- breadth, concentration, screens, worst days, contributors ----------------
    rlog, scr_rows, univ_rows, pool_rows, cons_rows, ff_rows = [], [], [], [], [], []
    for k, r in enumerate(R):
        tb, w, meta = r["table"], r["weights"], r["meta"]
        hb = set(r["held_before"]); ch = set(w.index)
        n_scoreable = int(tb["scoreable"].sum())
        scr_rows.append({"cutoff": str(r["cutoff"].date()), "trade": str(r["trade"].date()), "members_joined": len(tb),
                         "fail_listing": int((~tb["pass_listing"]).sum()), "fail_adt_bottom10": int((~tb["pass_adt"]).sum()),
                         "fail_turnover_ratio_bottom10": int((~tb["pass_turnover_ratio"]).sum()),
                         "fail_band_20pct": int((~tb["pass_band"]).sum()), "not_scoreable": int((~tb["scoreable"]).sum()),
                         "left_nifty500_before_trade": int((~tb["member_on_trade_date"]).sum()),
                         "no_trade_date_price": int((~tb["has_trade_price"]).sum()),
                         "no_share_count_turnover_ratio_not_tested": int(tb["turnover_ratio"].isna().sum()),
                         "eligible": int(tb["eligible"].sum()), "adt_cut_rs_cr": meta["adt_cut_cr"], "turnover_ratio_cut": meta["tr_cut"]})
        rlog.append({"cutoff": str(r["cutoff"].date()), "trade": str(r["trade"].date()), "n_held": len(w), "max_weight": float(w.max()),
                     "max_weight_name": NAMES.get(w.idxmax()), "top5_weight": float(w.nlargest(5).sum()),
                     "n_cap_binds_5pct": int((tb.loc[list(ch), "cap_binds_on"] == "5% absolute").sum()),
                     "n_cap_binds_5x": int((tb.loc[list(ch), "cap_binds_on"] == "5x free-float weight").sum()),
                     "entered": len(ch - hb), "stayed": len(ch & hb), "left": len(hb - ch),
                     "kept_by_buffer_rank_51_75": sum(1 for c in ch & hb if meta["rank"][c] > N_HOLD),
                     "forced_top25": len([c for c in meta["forced"]]), "rank_of_last_pick": meta["rank_of_last_pick"],
                     "ff_stand_ins": ";".join(NAMES.get(c, c) for c in meta["stand_in"]),
                     "traded_value_frac": r["traded"] / r["nav_before"], "cost_frac": r["cost"] / r["nav_before"]})
        for c in tb.index:
            x = tb.loc[c]
            univ_rows.append({"cutoff": str(r["cutoff"].date()), "symbol": NAMES.get(c, c), "isin": c, "member_on_trade_date": bool(x["member_on_trade_date"])})
            pool_rows.append({"cutoff": str(r["cutoff"].date()), "trade": str(r["trade"].date()), "symbol": NAMES.get(c, c), "isin": c,
                              **{k_: x[k_] for k_ in ("days_in_bhavcopy", "adt_6m_cr", "turnover_ratio", "band_hits_6m", "band_hit_share",
                                                     "ret_12m", "ret_6m", "vol_1y", "n_returns_1y", "pass_listing", "pass_adt",
                                                     "pass_turnover_ratio", "pass_band", "scoreable", "member_on_trade_date",
                                                     "has_trade_price", "held_before", "eligible", "rank", "score")}})
            if x["screener_symbol"] is not None or True:
                ff_rows.append({"cutoff": str(r["cutoff"].date()), "symbol": NAMES.get(c, c), "isin": c, "screener_symbol": x["screener_symbol"],
                                "shares_cr": x["shares_cr"], "share_ratio_vs_now": x["share_ratio"], "shares_basis": x["shares_basis"],
                                "promoter_pct": x["promoter_pct"], "promoter_basis": x["promoter_basis"], "ffmcap_cr": x["ffmcap_cr"]})
        for c in sorted(ch | hb, key=lambda c: meta["rank"].get(c, 10 ** 6)):
            x = tb.loc[c] if c in tb.index else None
            status = "entered" if c in ch - hb else ("stayed" if c in ch else "left")
            cons_rows.append({"cutoff": str(r["cutoff"].date()), "trade": str(r["trade"].date()), "symbol": NAMES.get(c, c), "isin": c,
                              "status": status, "rank": meta["rank"].get(c, np.nan),
                              "mr12": x["mr12"] if x is not None else np.nan, "mr6": x["mr6"] if x is not None else np.nan,
                              "score": x["score"] if x is not None else np.nan, "ffmcap_cr": x["ffmcap_cr"] if x is not None else np.nan,
                              "ff_weight_plain": x["ff_weight_plain"] if x is not None else np.nan,
                              "weight": float(w.get(c, 0.0)), "cap_binds_on": x["cap_binds_on"] if x is not None and c in ch else "",
                              "label": "rebuilt from NSE's rules on our data, not NSE's official list"})
    rlog = pd.DataFrame(rlog); scrdf = pd.DataFrame(scr_rows)
    rlog.to_csv(os.path.join(OUT, "rebalance_log.csv"), index=False)
    scrdf.to_csv(os.path.join(OUT, "screen_counts.csv"), index=False)
    pd.DataFrame(univ_rows).to_csv(os.path.join(OUT, "universe_by_review.csv"), index=False)
    pd.DataFrame(pool_rows).to_csv(os.path.join(OUT, "eligible_pool_by_review.csv"), index=False, float_format="%.6f")
    pd.DataFrame(cons_rows).to_csv(os.path.join(OUT, "constituents_by_review.csv"), index=False, float_format="%.6f")
    ffdf = pd.DataFrame(ff_rows)
    ffdf.to_csv(os.path.join(OUT, "free_float_inputs_by_review.csv"), index=False, float_format="%.6f")
    print("\nREBALANCE LOG\n" + rlog.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nSCREENS\n" + scrdf.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    res["rebalance_log"] = rlog.to_dict("records")
    res["screens"] = scrdf.to_dict("records")
    big_sh = ffdf[(ffdf["share_ratio_vs_now"] - 1).abs() > 0.10]
    res["free_float"] = {"rows": len(ffdf), "no_share_count": int(ffdf["shares_cr"].isna().sum()),
                         "share_count_changed_over_10pct_rows": len(big_sh),
                         "share_count_changed_over_10pct_names": sorted(big_sh["symbol"].unique().tolist())[:40],
                         "promoter_from_history_rows": int(ffdf["promoter_basis"].astype(str).str.startswith("Screener shareholding").sum()),
                         "promoter_from_snapshot_rows": int(ffdf["promoter_basis"].astype(str).str.startswith("Screener snapshot").sum()),
                         "promoter_missing_rows": int(ffdf["promoter_basis"].astype(str).str.startswith("no promoter").sum())}
    print("FREE FLOAT", res["free_float"])
    res["adhoc"] = [{**x, "date": str(x["date"].date())} for x in base["adhoc"]]
    print("AD HOC", res["adhoc"])
    # worst days
    wl = []
    for d, rv in rg.nsmallest(5).items():
        i = days.get_loc(d)
        rr = [x for x in R if x["trade"] < d][-1]
        names_ = list(rr["weights"].index)
        mv = (adj.iloc[i][names_] / adj.iloc[i - 1][names_] - 1).dropna().sort_values()
        wl.append({"date": str(d.date()), "strategy": float(rv), "nifty500": float(rb.get(d, np.nan)),
                   "momentum50_published": float(rm.get(d, np.nan)),
                   "worst_names": [(NAMES.get(k_, k_), round(float(x_), 4)) for k_, x_ in mv.head(3).items()],
                   "share_of_holdings_down": float((mv < 0).mean())})
    res["worst_days"] = wl
    for x in wl:
        print("  WORST DAY", x)
    oc = pd.Series(base["contrib"]).sort_values(ascending=False)
    pos_total = oc[oc > 0].sum()
    res["top2_share_of_gains"] = float(oc.head(2).sum() / pos_total)
    res["best_contributors"] = [(NAMES.get(k_, k_), float(x_ / START_NAV)) for k_, x_ in oc.head(5).items()]
    res["worst_contributors"] = [(NAMES.get(k_, k_), float(x_ / START_NAV)) for k_, x_ in oc.tail(5).items()]
    res["names_ever_held"] = len(oc)
    print("CONTRIBUTORS best", res["best_contributors"], "worst", res["worst_contributors"], "top2 share", res["top2_share_of_gains"])
    # sector-free concentration of the strategy vs NIFTY 500: beta, tracking
    rbb = rb.reindex(rg.index).fillna(0.0)
    res["tracking"] = {"tracking_error_vs_nifty500": float((rg - rbb).std() * math.sqrt(252)), "corr_nifty500": float(rg.corr(rbb)),
                       "beta_nifty500": float(np.cov(rg, rbb)[0, 1] / rbb.var())}
    dd = v / v.cummax() - 1
    tr_ = dd.idxmin(); pk_ = v.loc[:tr_].idxmax()
    res["drawdown"] = {"peak": str(pk_.date()), "trough": str(tr_.date()), "depth": float(-dd.min())}

    # ---------------- step 06: research validation ----------------
    rf = pd.Series(RF_D, index=rg.index)
    boot = bootstrap_sharpe_ci(rg, block_size=BLOCK, n_resamples=2000, rf_daily=rf, seed=0)
    res["bootstrap"] = {"ci_low": boot.ci_low, "ci_high": boot.ci_high, "point": boot.point_estimate, "frac_positive": boot.fraction_positive}
    paired = {}
    for nm, other in (("NIFTY 500", rbb), ("NSE published Momentum 50", rm.reindex(rg.index).fillna(0.0))):
        pb = bootstrap_sharpe_ci((rg - other), block_size=BLOCK, n_resamples=2000, seed=0)
        paired[nm] = {"ci_low": pb.ci_low, "ci_high": pb.ci_high, "point": pb.point_estimate, "p_not_positive": 1.0 - pb.fraction_positive}
    res["paired"] = paired
    n_trials = N_CONFIGS_CARD + 1                          # + the trade-date sensitivity
    dsr = deflated_sharpe_from_returns(rg, n_trials=n_trials, trial_sharpe_std=0.3, rf_daily=rf)
    res["deflated_sharpe"] = float(dsr); res["n_trials"] = n_trials
    windows = walk_forward_windows(v.index, n_folds=4, min_train_years=1.0)
    oos = oos_stability_summary(v, rg, windows, rf_daily=rf, min_obs=60)
    oos.to_csv(os.path.join(OUT, "walk_forward.csv"), index=False)
    res["oos"] = oos.to_dict("records")
    print(f"\nVALIDATION bootstrap Sharpe 90% CI [{boot.ci_low:.2f}, {boot.ci_high:.2f}] point {boot.point_estimate:.2f}; "
          f"paired {json.dumps(paired)}; DSR(n={n_trials}) {dsr:.3f}")
    print(oos.to_string(index=False))

    # ---------------- step 07: factor fingerprint ----------------
    fnames = ["NIFTY 500", "NIFTY500 MOMENTUM 50", "NIFTY500 VALUE 50", "NIFTY500 QUALITY 50", "NIFTY500 LOW VOLATILITY 50"]
    fr = pd.DataFrame({n: bench[n].reindex(base["nav"].index).pct_change(fill_method=None) for n in fnames}).iloc[1:]
    fpr = factor_fingerprint(rg, fr, rf_daily=rf)
    fpr2 = factor_fingerprint(rg, fr.drop(columns=["NIFTY500 MOMENTUM 50"]), rf_daily=rf)
    for key, f_ in (("factor_fingerprint", fpr), ("factor_fingerprint_without_momentum", fpr2)):
        if "error" in f_:
            res[key] = {"error": f_["error"]}
        else:
            res[key] = {k_: f_[k_] for k_ in ("alpha_ann", "alpha_t_hac", "r_squared", "n_obs", "loadings") if k_ in f_}
        print(key, res[key])

    # ---------------- Gate B ----------------
    from ros.cards.schema import load_card
    from ros.governance.gates import gate_b
    research = {"deflated_sharpe": {"deflated_sharpe_prob": float(dsr),
                                    "interpretation": f"n_trials={n_trials} (card's 7 momentum rule sets + the trade-date sensitivity), trial Sharpe std 0.3, net of 30bp, over a 6% hurdle"},
                "oos_min_sharpe": float(oos["sharpe"].min()) if not oos.empty else None,
                "bootstrap_p_not_positive": float(paired["NIFTY 500"]["p_not_positive"])}
    portfolio = {"alpha_t_hac": (float(fpr["alpha_t_hac"]) if "error" not in fpr else None), "annual_turnover": base["turnover_two_way"]}
    gb = gate_b(load_card(CARD), research, portfolio)
    print("\nGATE B CRITERIA (computed by gate_b(); decision stays PENDING)\n" + gb.render())
    res["gate_b"] = gb.to_dict()
    res["gate_b_inputs"] = {"research": research, "portfolio": portfolio}
    # card's own success / failure bar
    s_net, s_b = rows[0], rows[1]
    res["card_bar"] = {
        "beats_nifty500_cagr_net": s_net["cagr"] > s_b["cagr"], "beats_nifty500_sharpe_net": s_net["sharpe_card"] > s_b["sharpe_card"],
        "edge_keeps_sign_with_early_trade": bool(np.sign(timing[0]["edge_common_window"]) == np.sign(timing[1]["edge_common_window"])),
        "breakeven_at_least_60bp": breakeven >= 60.0, "gross_corr_above_095": recon["daily_corr_gross_vs_published"] > 0.95,
        "gross_gap_under_2pts": abs(recon["annual_gap_gross_minus_published"]) < 0.02,
        "no_rebalance_under_5_names_or_over_25pct": bool((rlog["n_held"] >= 5).all() and (rlog["max_weight"] <= 0.25).all())}
    print("CARD BAR", res["card_bar"])

    # ---------------- hand-off files ----------------
    h = RUN
    daily = pd.DataFrame({"strategy": rg, "benchmark": rb.reindex(idx), "sleeve": rm.reindex(idx)})
    daily.index = daily.index.strftime("%Y-%m-%d"); daily.index.name = "date"
    daily.to_csv(os.path.join(h, "daily_returns.csv"), float_format="%.10f")
    comp = pd.DataFrame({"Rebuild gross of costs": gross["ret"], "NSE published Momentum 50 index": rm,
                         "Rebuild, trade the day after cut-off (net 30bp)": early["ret"]}).reindex(idx)
    comp.index = comp.index.strftime("%Y-%m-%d"); comp.index.name = "date"
    comp.to_csv(os.path.join(h, "comparators.csv"), float_format="%.10f")
    hd = base["holdings"].copy()
    tabs = {r["trade"]: r["table"] for r in R}
    def sigval(d_, c, col):
        rr = [x for x in R if x["trade"] <= d_][-1]["table"]
        return rr.loc[c, col] if c in rr.index else np.nan
    hd["symbol"] = hd["isin"].map(lambda c: NAMES.get(c, c))
    hd["leg"] = "long"
    hd["price"] = [float(P["CLOSE"].loc[d_, c]) for d_, c in zip(hd["date"], hd["isin"])]
    hd["rank"] = [sigval(d_, c, "rank") for d_, c in zip(hd["date"], hd["isin"])]
    hd["score"] = [sigval(d_, c, "score") for d_, c in zip(hd["date"], hd["isin"])]
    hd["ffmcap_cr"] = [sigval(d_, c, "ffmcap_cr") for d_, c in zip(hd["date"], hd["isin"])]
    hd["date"] = pd.to_datetime(hd["date"]).dt.strftime("%Y-%m-%d")
    hd[["date", "symbol", "leg", "weight", "price", "isin", "rank", "score", "ffmcap_cr", "event"]].to_csv(
        os.path.join(h, "holdings.csv"), index=False, float_format="%.8f")
    # trades
    trd = base["trades"].copy()
    co_of = {}
    for r in R:
        co_of[r["trade"]] = r["cutoff"]
    rows_t = []
    wb_map = {(r["trade"], c): r["w_before"].get(c, 0.0) for r in R for c in set(r["w_before"]) | set(r["weights"].index)}
    wa_map = {(r["trade"], c): float(r["weights"].get(c, 0.0)) for r in R for c in set(r["w_before"]) | set(r["weights"].index)}
    for x in trd.itertuples(index=False):
        d_ = pd.Timestamp(x.date)
        rv = [r for r in R if r["trade"] <= d_][-1]
        sd = co_of.get(d_, rv["cutoff"])
        tb = rv["table"]
        rk = rv["meta"]["rank"].get(x.isin)
        if x.kind == "review":
            if x.action == "BUY":
                why = (f"Entered: rank {rk} on the {sd.date()} cut-off" + (" (top 25, forced in)" if rk and rk <= FORCE_RANK else " (filled an empty place)")
                       + f"; score {tb.loc[x.isin, 'score']:.2f}; target weight {wa_map.get((d_, x.isin), 0):.2%}.")
            elif x.action == "SELL":
                if x.isin not in tb.index:
                    why = "Left: no longer a NIFTY 500 member at the cut-off."
                elif not tb.loc[x.isin, "eligible"]:
                    why = "Left: failed an eligibility screen or left NIFTY 500 before the trade date."
                elif rk and rk > KEEP_RANK:
                    why = f"Left: rank {rk}, beyond the 75 buffer."
                else:
                    why = f"Left: rank {rk}, pushed out by a top-25 newcomer (lowest-ranked holding)."
            else:
                why = f"Kept (rank {rk}); reset to its new target weight {wa_map.get((d_, x.isin), 0):.2%}."
        else:
            why = x.why
        rows_t.append({"date": d_.strftime("%Y-%m-%d"), "symbol": NAMES.get(x.isin, x.isin), "action": x.action,
                       "weight_before": wb_map.get((d_, x.isin), np.nan) if x.kind == "review" else np.nan,
                       "weight_after": wa_map.get((d_, x.isin), np.nan) if x.kind == "review" else np.nan,
                       "isin": x.isin, "signal_date": sd.strftime("%Y-%m-%d"), "execution_date": d_.strftime("%Y-%m-%d"),
                       "price_date": d_.strftime("%Y-%m-%d") if not np.isnan(x.price) else "", "price": x.price,
                       "price_basis": "NSE bhavcopy CLOSE on the execution date (raw, not adjusted)" if not np.isnan(x.price) else "no trade that day: last traded close",
                       "shares": round(x.value / x.price, 4) if x.price and not np.isnan(x.price) else np.nan,
                       "value_rs": round(x.value, 2), "why": why})
    order = {"SELL": 0, "TRIM": 1, "ADD": 2, "BUY": 3}
    tdf2 = pd.DataFrame(rows_t)
    tdf2["_o"] = tdf2["action"].map(order)
    tdf2.sort_values(["date", "_o", "symbol"]).drop(columns="_o").to_csv(os.path.join(h, "trades.csv"), index=False, float_format="%.6f")
    # selection.csv: every member considered at every review
    sel = []
    for r in R:
        tb, w, meta = r["table"], r["weights"], r["meta"]
        hb = set(r["held_before"]); ch = set(w.index)
        for c in tb.index:
            x = tb.loc[c]
            rk = meta["rank"].get(c)
            fails = []
            if not x["pass_listing"]: fails.append(f"only {x['days_in_bhavcopy']} trading days in bhavcopy (needs 252)")
            if not x["pass_adt"]: fails.append(f"6-month average traded value Rs {x['adt_6m_cr']:.2f} cr is in the bottom 10% (cut Rs {meta['adt_cut_cr']:.2f} cr)")
            if not x["pass_turnover_ratio"]: fails.append(f"turnover ratio {x['turnover_ratio']:.4f} is in the bottom 10% (cut {meta['tr_cut']:.4f})")
            if not x["pass_band"]: fails.append(f"hit a price band on {x['band_hit_share']:.0%} of the last 6 months' days (limit 20%)")
            if not x["scoreable"]: fails.append("no close on a look-back date or under 200 daily returns in the year")
            if not x["member_on_trade_date"]: fails.append("left NIFTY 500 before the trade date")
            if not x["has_trade_price"]: fails.append("no price on the trade date")
            if c in ch and c not in hb:
                dec, why = "BOUGHT", f"Rank {rk} of {len(meta['order'])} eligible; score {x['score']:.2f}; {'forced in as a top-25 name' if rk <= FORCE_RANK else 'filled an empty place'}; weight {w[c]:.2%}."
            elif c in ch:
                dec, why = "KEPT", f"Held and ranked {rk} (within the top 75); score {x['score']:.2f}; weight {w[c]:.2%}."
            elif c in hb:
                dec = "SOLD"
                why = ("Held but " + "; ".join(fails) + ".") if fails else (f"Held but ranked {rk}, beyond 75." if rk > KEEP_RANK else f"Held, ranked {rk}, pushed out by a top-25 newcomer.")
            elif fails:
                dec, why = "SKIPPED", "Not eligible: " + "; ".join(fails) + "."
            else:
                dec, why = "NOT NEEDED", f"Eligible, rank {rk}, but not in the top 25 and the 50 places were full (last pick was rank {meta['rank_of_last_pick']})."
            sel.append({"signal_date": str(r["cutoff"].date()), "execution_date": str(r["trade"].date()), "symbol": NAMES.get(c, c), "isin": c,
                        "decision": dec, "rank": rk, "pick_no": (sorted(ch, key=lambda q: meta["rank"][q]).index(c) + 1) if c in ch else np.nan,
                        "score": x["score"], "z_avg": x["z_avg"], "mr12": x["mr12"], "mr6": x["mr6"], "ret_12m": x["ret_12m"], "ret_6m": x["ret_6m"],
                        "vol_1y": x["vol_1y"], "adt_6m_cr": x["adt_6m_cr"], "turnover_ratio": x["turnover_ratio"], "band_hit_share": x["band_hit_share"],
                        "ffmcap_cr": x["ffmcap_cr"], "weight_before": r["w_before"].get(c, 0.0), "weight_after": float(w.get(c, 0.0)),
                        "close_raw": float(P["CLOSE"].loc[r["trade"], c]) if not np.isnan(P["CLOSE"].loc[r["trade"], c]) else np.nan,
                        "rank_of_last_pick": meta["rank_of_last_pick"], "why": why})
        for c in hb - set(tb.index):
            sel.append({"signal_date": str(r["cutoff"].date()), "execution_date": str(r["trade"].date()), "symbol": NAMES.get(c, c), "isin": c,
                        "decision": "SOLD", "weight_before": r["w_before"].get(c, 0.0), "weight_after": 0.0,
                        "rank_of_last_pick": meta["rank_of_last_pick"],
                        "why": "Held but no longer a NIFTY 500 member at the cut-off, so it leaves at this review (rule, PDF page 208)."})
    seldf = pd.DataFrame(sel)
    dorder = {"BOUGHT": 0, "KEPT": 1, "SOLD": 2, "NOT NEEDED": 3, "SKIPPED": 4}
    seldf["_o"] = seldf["decision"].map(dorder)
    seldf.sort_values(["signal_date", "_o", "rank"]).drop(columns="_o").to_csv(os.path.join(h, "selection.csv"), index=False, float_format="%.6f")
    res["selection_counts"] = seldf.groupby(["signal_date", "decision"]).size().unstack(fill_value=0).reset_index().to_dict("records")

    if not a.no_charts:
        try:
            from universal_backtester.clean_charts import save_clean_charts
            wts = base["holdings"].pivot_table(index="date", columns="isin", values="weight", aggfunc="last")
            charts = save_clean_charts(v, vb.reindex(v.index), outdir=os.path.join(OUT, "charts"), tag=SLUG,
                                       strategy_name="Momentum 50 rebuild (net 30bp)", benchmark_name="NIFTY 500",
                                       sleeve=vm.reindex(v.index), sleeve_name="NSE NIFTY500 Momentum 50 (published)",
                                       footnote="Price return. Official NIFTY 500 membership; NSE bhavcopy; 30bp round trip; semi-annual, trade at end-June/December close.")
            res["charts"] = [rel(c) for c in charts]
        except Exception as e:
            print("charts skipped:", repr(e))
    # ---------------- lineage: what exactly this run read, with hashes ----------------
    from ros.data.lineage import write_run_manifest
    res["manifest"] = rel(write_run_manifest(
        h, __file__,
        inputs={"card": CARD, "corporate_action_events": EVENTS, "nifty500_membership": N500.MEMBERSHIP_CSV,
                "index_workbook": INDEX_PATH, "screener_shares": SHARES, "screener_financials": FIN, "bhavcopy_cache": CACHE},
        params={"panel_start": str(PANEL_START.date()), "sample_end": str(SAMPLE_END.date()), "cutoffs": CUTOFFS,
                "n_hold": N_HOLD, "keep_rank": KEEP_RANK, "force_rank": FORCE_RANK, "cost_bp_round_trip": COST_BP_RT,
                "rf_annual": RF_ANNUAL, "n_trials": n_trials, "ec_lag_days": EC_LAG_DAYS, "sh_lag_days": SH_LAG_DAYS,
                "sharpe_definition": "(mean daily return x 252 - rf_annual) / (daily std x sqrt 252)"},
        outputs=("daily_returns.csv", "comparators.csv", "holdings.csv", "trades.csv", "selection.csv")))
    print("manifest:", res["manifest"])
    json.dump(res, open(os.path.join(OUT, "results_raw.json"), "w", encoding="utf-8"), indent=1, default=str)
    print("\nDone. Gate B decision is not assigned by this script.")


if __name__ == "__main__":
    main()
