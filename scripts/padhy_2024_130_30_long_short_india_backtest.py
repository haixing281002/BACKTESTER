"""Step 05 to 07 for cards/padhy_2024_130_30_long_short.yaml, run AS APPROVED AT GATE A.

Two data sources only, NSE bhavcopy and Screener.in, through the master CSV that
data/raw/MANIFEST.yaml declares. Nothing else enters except the NIFTY index closes
(NIFTY 500, NIFTY 50, NIFTY500 MOMENTUM 50 and the factor sleeves for the fingerprint),
which the card names.

What it runs:
  MAIN       every last trading day of March and September: rebuild a NIFTY500 Momentum 50
             lookalike (top 500 by free-float cap, then the average of z-scored 6m and 12m
             returns over one-year volatility, top 50); score the 50 against the NIFTY500
             MOMENTUM 50 index over 126 days on tracking error, IR, Sharpe and Treynor;
             long the names in the best 40% on all four (+130% equal weight), short the
             names in the worst 40% on all four (-30% equal weight); if either leg is
             empty, hold the 50 in equal weight, long only. Trade at the NEXT day's close,
             hold six months with weights drifting. 30bp round trip, 150bp a year borrow.
  comparators NIFTY 500, the NIFTY500 MOMENTUM 50 index, the equal-weight rebuilt 50, the
             long leg alone at 100%, and the paper-faithful top-30 mega-cap version
             scored against NIFTY 50.
  sensitivities  list rebuilt one quarter earlier; cash at 6% in empty-leg half-years;
             short leg limited to names that traded every day; screen fraction 30/40/50%;
             costs 30/60/90bp and borrow 50 to 500bp.

The universe and the screens live in plain functions below (testable, read only data up to
the formation close). The allocator FormationBook only carries the formed book between
formations and handles a name that stops trading. universal_backtester's engine does all
accounting, the causal one-day shift and costs (allow_short=True, never ros/engine).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from universal_backtester.allocators import Allocator, AllocatorContext, _cap_and_redistribute
from universal_backtester.data import load_banner_workbook
from universal_backtester.engine import Backtester, LookaheadError, assert_causal
from universal_backtester.metrics import ann_vol as _ann_vol
from universal_backtester.metrics import cagr as _cagr
from universal_backtester.metrics import max_drawdown as _mdd
from universal_backtester.validation import (
    bootstrap_sharpe_ci, deflated_sharpe_from_returns, oos_stability_summary,
    parameter_sensitivity_sweep, sensitivity_verdict, walk_forward_windows,
)
from ros.validation.portfolio import factor_fingerprint

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER = os.path.join(REPO, "data", "raw", "master", "bhavcopy_screener_master.csv")
INDEX_PATH = os.path.join(REPO, "data", "raw", "NSE_Broad_Factor_Indices_Historical_Data.xlsx")
CARD = os.path.join(REPO, "cards", "padhy_2024_130_30_long_short.yaml")
OUT = os.path.join(REPO, "outputs")
SLUG = "padhy_2024_130_30_long_short"

SAMPLE_END = pd.Timestamp("2026-09-18")      # card backtest_plan.sample_end (index workbook ends here)
FIRST_FORMATION = pd.Timestamp("2022-09-30")  # card: the momentum rule needs ~12 months of prices
SCREEN_DAYS, MOM6, MOM12 = 126, 126, 252
N_PARENT, N_PICK, N_MEGA = 500, 50, 30
FRAC = 0.40
LONG_W, SHORT_W = 1.30, 0.30
SPREAD_BPS, BORROW_BPS = 30.0, 150.0
RF_ANNUAL = 0.06                             # flat 6% hurdle, operator-declared
N_CONFIGS_TRIED = 2                          # the card's own number
BLOCK = 126                                  # bootstrap block = one holding period
ENGINE_LAG = 0                               # engine adds its own 1-day shift: form at t, trade at t+1 close
# The card sets the engine gross cap at 2.0 so drift between formations is never rescaled. A first
# run showed drift reaching 2.065 (a short that rose 3.5x), which made the engine rescale and trade.
# The cap is raised to 3.0 so the card's intent holds (no rescale between formations); the days
# above 2.0 are reported. Books are still formed at exactly 1.6 gross.
GROSS_CAP = 3.0

BENCH_COLS = {
    "NIFTY 500": ("Broad Market", "NIFTY 500 Close"),
    "NIFTY 50": ("Broad Market", "NIFTY 50 Close"),
    "NIFTY500 MOMENTUM 50": ("Factor Indices", "NIFTY500 MOMENTUM 50 Close"),
    "NIFTY500 VALUE 50": ("Factor Indices", "NIFTY500 VALUE 50 Close"),
    "NIFTY500 QUALITY 50": ("Factor Indices", "NIFTY500 QUALITY 50 Close"),
    "NIFTY500 LOW VOLATILITY 50": ("Factor Indices", "NIFTY500 LOW VOLATILITY 50 Close"),
}


# ---------------------------------------------------------------- data ------------------------
def load_panel(path):
    p = pd.read_csv(path, parse_dates=["date"])
    p = p[p["date"] <= SAMPLE_END]
    adj = p.pivot(index="date", columns="security_id", values="adj_close").sort_index()
    mcap = p.pivot(index="date", columns="security_id", values="market_cap").reindex(adj.index)
    adv = p.pivot(index="date", columns="security_id", values="adv").reindex(adj.index)
    ff = p.groupby("security_id")["free_float_frac"].last().reindex(adj.columns)
    names = p.drop_duplicates("security_id", keep="last").set_index("security_id")["symbol"].to_dict()
    # Carry a price across a non-trading gap inside a name's life (a zero return), but never past
    # its last trade: after that the name is dead and the engine closes it.
    alive = adj.notna().iloc[::-1].cummax().iloc[::-1] & adj.notna().cummax()
    px = adj.ffill().where(alive)
    ffmcap = mcap.mul(ff.fillna(1.0), axis=1)   # blank free float = 1.0 (card, selection.rule)
    return adj, px, alive, ffmcap, adv, names, ff


def load_benchmarks(index):
    out = {}
    cache = {}
    for disp, (sheet, col) in BENCH_COLS.items():
        if sheet not in cache:
            cache[sheet] = load_banner_workbook(INDEX_PATH, sheet=sheet)[0]
        s = cache[sheet][col].dropna()
        out[disp] = s.reindex(index.union(s.index)).ffill().reindex(index)
    return out


def formation_dates(index, months=(3, 9)):
    s = pd.Series(index, index=index)
    last = s.groupby(index.to_period("M")).last()
    d = pd.DatetimeIndex([v for k, v in last.items() if k.month in months])
    return d[(d >= FIRST_FORMATION) & (d <= SAMPLE_END) & (d < index[-1])]


def quarter_before(index, f):
    """The last trading day of the quarter before formation date f (Dec for Mar, Jun for Sep)."""
    q = (f.to_period("Q") - 1)
    s = index[(index.to_period("Q") == q)]
    return s[-1]


# ------------------------------------------------------- universe (step 1) --------------------
def momentum_universe(px, ffmcap, i, n_parent=N_PARENT, n_pick=N_PICK):
    """NIFTY500 Momentum 50 lookalike on row i, reading rows <= i only."""
    l12 = min(MOM12, i)
    p_t, p_6, p_12 = px.iloc[i], px.iloc[i - MOM6], px.iloc[i - l12]
    cap = ffmcap.iloc[i].where(p_t.notna())
    parent = cap.dropna().sort_values(ascending=False).index[:n_parent]
    win = np.log(px[parent].iloc[i - l12:i + 1]).diff().iloc[1:]
    ok = p_12[parent].notna() & p_6[parent].notna() & (win.notna().sum() >= 0.95 * l12)
    el = parent[ok.values]
    vol = win[el].std(ddof=1) * np.sqrt(252)
    m6 = (p_t[el] / p_6[el] - 1.0) / vol
    m12 = (p_t[el] / p_12[el] - 1.0) / vol
    z = lambda s: (s - s.mean()) / s.std(ddof=1)
    score = ((z(m6) + z(m12)) / 2.0).dropna()
    order = sorted(score.index, key=lambda c: (-score[c], c))
    pick = order[:n_pick]
    return pick, score[pick], cap[pick], len(parent), len(el)


def mega_universe(px, ffmcap, i, n=N_MEGA):
    cap = ffmcap.iloc[i].where(px.iloc[i].notna()).dropna()
    order = sorted(cap.index, key=lambda c: (-cap[c], c))
    return order[:n]


# --------------------------------------------------------- screens (step 2) -------------------
def screens(px, bench, ids, i, frac=FRAC):
    """The paper's four screens over the trailing 126 daily returns ending on row i."""
    R = px[ids].iloc[i - SCREEN_DAYS:i + 1].pct_change(fill_method=None).iloc[1:]
    b = bench.iloc[i - SCREEN_DAYS:i + 1].pct_change(fill_method=None).iloc[1:]
    full = R.notna().all() & px[ids].iloc[i - SCREEN_DAYS].notna()
    R = R.loc[:, full.values]
    act = R.sub(b, axis=0)
    te = act.std(ddof=1)
    ir = act.mean() / te
    rf6 = (1.0 + RF_ANNUAL) ** 0.5 - 1.0
    ex = (1.0 + R).prod() - 1.0 - rf6
    sharpe = ex / R.std(ddof=1)
    beta = R.apply(lambda c: np.cov(c, b)[0, 1]) / b.var(ddof=1)
    treynor = (ex / beta).where(beta > 0)
    m = pd.DataFrame({"tracking_error": te, "information_ratio": ir, "sharpe": sharpe,
                      "beta": beta, "treynor": treynor, "six_month_return": ex + rf6})
    n = len(m)
    k = int(np.floor(frac * n + 0.5))

    def top(col, best_low):
        s = m[col].dropna()
        o = sorted(s.index, key=lambda c: ((s[c] if best_low else -s[c]), c))
        return set(o[:k])

    def bottom(col, best_low):
        s = m[col].dropna()
        o = sorted(s.index, key=lambda c: ((-s[c] if best_low else s[c]), c))
        return set(o[:k])

    long = top("tracking_error", True) & top("information_ratio", False) & top("sharpe", False) & top("treynor", False)
    short = (bottom("tracking_error", True) & bottom("information_ratio", False)
             & bottom("sharpe", False) & bottom("treynor", False))
    return sorted(long), sorted(short), m, k


def book_row(cols, universe, long, short, fallback="ew", long_w=LONG_W, short_w=SHORT_W):
    """Target weights for one formation. fallback: 'ew' = equal-weight universe long only,
    'cash' = all zero (cash at 6%)."""
    w = pd.Series(0.0, index=cols)
    formed = bool(long) and bool(short)
    if formed:
        w[list(long)] = long_w / len(long)
        if short_w:
            w[list(short)] = -short_w / len(short)
    elif fallback == "ew":
        w[list(universe)] = 1.0 / len(universe)
    return w, formed


# ---------------------------------------------------------------- allocator -------------------
class FormationBook(Allocator):
    """Holds the book formed at the last formation (alpha row all finite on a formation day,
    NaN otherwise), lets weights drift, and when a held name stops trading closes it at its
    last price and spreads its weight over the rest of its own leg (card, strategy.template_gap).
    Net exposure is kept where the formation put it."""
    template_name = "padhy_formation_book"

    def __init__(self, assets, **params):
        super().__init__(assets, **params)
        self.started = False
        self.long_set, self.short_set = set(), set()
        self.max_gross = 0.0
        self.days_over_2 = 0
        self.redistributions = 0

    def ready(self, ctx: AllocatorContext) -> bool:
        if ctx.alpha is not None and np.isfinite(ctx.alpha).all():
            self.started = True
        return self.started

    def target_weights(self, ctx: AllocatorContext) -> np.ndarray:
        el = ctx.eligible if ctx.eligible is not None else np.ones(self.n, bool)
        if ctx.alpha is not None and np.isfinite(ctx.alpha).all():
            t = ctx.alpha.copy()
            dead = (t != 0) & ~el
            if dead.any():
                t = self._respread(t, dead)
            self.long_set = set(np.flatnonzero(t > 0))
            self.short_set = set(np.flatnonzero(t < 0))
            self.net = float(t.sum())
            self.max_gross = max(self.max_gross, float(np.abs(t).sum()))
            return t
        w = ctx.current_weights.copy()
        held = np.zeros(self.n, bool)
        held[list(self.long_set | self.short_set)] = True
        dead = held & ~el
        if dead.any():
            w = self._respread(w, dead)
            self.long_set -= set(np.flatnonzero(dead))
            self.short_set -= set(np.flatnonzero(dead))
        g = float(np.abs(w).sum())
        self.max_gross = max(self.max_gross, g)
        self.days_over_2 += int(g > 2.0)
        return w

    def _respread(self, w, dead):
        self.redistributions += int(dead.sum())
        w = w.copy()
        short_tot = float(w[w < 0].sum())
        sl = (w < 0) & ~dead
        w[dead] = 0.0
        if sl.any():
            w[sl] = w[sl] * (short_tot / w[sl].sum())
            short_tot_after = short_tot
        else:
            short_tot_after = 0.0
        ll = (w > 0) & ~dead
        target_long = getattr(self, "net", 1.0) - short_tot_after
        if ll.any() and w[ll].sum() > 0:
            w[ll] = w[ll] * (target_long / w[ll].sum())
        return w

    def diagnostics(self):
        return {"max_gross": self.max_gross, "days_drifted_above_2": self.days_over_2,
                "names_respread": self.redistributions}


# ---------------------------------------------------------------- helpers ---------------------
def run_book(px, alive, rows, spread=SPREAD_BPS, borrow=BORROW_BPS, rf=None, name="book"):
    assets = list(px.columns)
    alpha = pd.DataFrame(np.nan, index=px.index, columns=assets)
    for d, w in rows.items():
        alpha.loc[d] = w.reindex(assets).fillna(0.0).values
    bt = Backtester(prices=px, assets=assets, spread_bps=spread, lag_days=ENGINE_LAG, allow_cash=True,
                    membership=alive, allow_short=True, max_gross_exposure=GROSS_CAP, short_borrow_bps=borrow,
                    rf_daily=rf)
    return bt.run(allocator=FormationBook(assets), rebalance="daily", alpha=alpha, name=name)


def live(value, f0):
    v = value.loc[f0:SAMPLE_END]
    v = v / v.iloc[0]
    return v, v.pct_change().iloc[1:]


def stats(v, r, label, rf_annual=RF_ANNUAL):
    c, vol = _cagr(v), _ann_vol(r)
    return {"name": label, "cagr": c, "vol": vol, "sharpe_vs_6pct": (c - rf_annual) / vol if vol > 0 else np.nan,
            "max_dd": _mdd(v), "total_return": float(v.iloc[-1] / v.iloc[0] - 1.0), "n_days": len(r),
            "start": str(v.index[0].date()), "end": str(v.index[-1].date())}


def build_books(px, adj, alive, ffmcap, adv, bench_mom, bench_n50, fdates, frac=FRAC, lagged=False,
                fallback="ew", liquid_shorts=False, mega=False):
    """Return {formation_date: weights}, a per-formation record list, and the long-only and EW books."""
    idx = px.index
    rows, ew_rows, lo_rows, recs = {}, {}, {}, []
    for f in fdates:
        i = idx.get_loc(f)
        if mega:
            uni = mega_universe(px, ffmcap, i)
            score_b = bench_n50
            info = {}
        else:
            src = idx.get_loc(quarter_before(idx, f)) if lagged else i
            uni, sc, cap, n_par, n_el = momentum_universe(px, ffmcap, src)
            score_b = bench_mom
            info = {"parent_size": n_par, "momentum_eligible": n_el}
        long, short, m, k = screens(px, score_b, uni, i, frac=frac)
        if liquid_shorts and short:
            win_ok = (adj[short].iloc[i - SCREEN_DAYS:i + 1].notna() & (adv[short].iloc[i - SCREEN_DAYS:i + 1] > 0)).all()
            short = [c for c in short if win_ok[c]]
        w, formed = book_row(px.columns, uni, long, short, fallback=fallback)
        rows[f] = w
        ew_rows[f] = book_row(px.columns, uni, [], [], fallback="ew")[0]
        lo_w, _ = book_row(px.columns, uni, long, short, fallback="ew", long_w=1.0, short_w=0.0)
        lo_rows[f] = lo_w
        recs.append({"formation": f, "universe": list(uni), "long": long, "short": short, "formed": formed,
                     "k": k, "n_screened": len(m), "metrics": m, **info})
    return rows, ew_rows, lo_rows, recs


def index_style_rows(px, ffmcap, fdates, cap_w=0.05):
    """Fidelity check only: the rebuilt 50 weighted the index's way as the drafter understands it
    (free-float cap times a score multiplier, 1+z above zero and 1/(1-z) below, capped at 5%)."""
    rows = {}
    for f in fdates:
        i = px.index.get_loc(f)
        uni, sc, cap, _, _ = momentum_universe(px, ffmcap, i)
        mult = np.where(sc.values >= 0, 1.0 + sc.values, 1.0 / (1.0 - sc.values))
        raw = cap.values * mult
        w = _cap_and_redistribute(raw / raw.sum(), cap_w)
        s = pd.Series(0.0, index=px.columns)
        s[uni] = w / w.sum()
        rows[f] = s
    return rows


def leg_return(px_last, names, d0, d1):
    if not names:
        return np.nan
    a = px_last.loc[d0, names]
    b = px_last.loc[d1, names]
    return float((b / a - 1.0).mean())


# ---------------------------------------------------------------- main ------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--master", default=MASTER)
    ap.add_argument("--no-charts", action="store_true")
    ap.add_argument("--handoff", default="", help="Lightyear hand-off directory for daily_returns.csv")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    res = {"card": os.path.relpath(CARD, REPO), "slug": SLUG}

    print("Card: padhy_2024_130_30_long_short  (as approved at Gate A on 2026-10-06)")
    adj, px, alive, ffmcap, adv, names, ff = load_panel(a.master)
    # Only names that can ever be ranked (a Screener market cap) can enter a book.
    cols = [c for c in px.columns if ffmcap[c].notna().any()]
    fdates = formation_dates(px.index)
    # Survivorship of the parent: names with no Screener page cannot be ranked. Count those that
    # were liquid enough to matter: in the top 500 by 126-day mean traded value on a formation date.
    tv126 = adv.rolling(SCREEN_DAYS, min_periods=60).mean()
    unrankable = [c for c in px.columns if c not in set(cols)]
    surv = []
    for f in fdates:
        top = tv126.loc[f].dropna().sort_values(ascending=False).index[:N_PARENT]
        miss = [c for c in top if c in set(unrankable)]
        surv.append({"formation": str(f.date()), "top500_by_traded_value_without_screener_cap": len(miss),
                     "examples": ", ".join(names.get(c, c) for c in miss[:8])})
    print("Unrankable (no Screener market cap) among the top 500 by traded value, per formation: "
          + "; ".join(f"{s['formation']} {s['top500_by_traded_value_without_screener_cap']}" for s in surv))
    pd.DataFrame(surv).to_csv(os.path.join(OUT, f"{SLUG}_survivorship.csv"), index=False)
    adj, px, alive, ffmcap, adv = adj[cols], px[cols], alive[cols], ffmcap[cols], adv[cols]
    bench = load_benchmarks(px.index)
    print(f"Panel: {len(cols)} rankable securities (Screener market cap present), "
          f"{px.index[0].date()} -> {px.index[-1].date()}; formations: {[str(d.date()) for d in fdates]}")
    print(f"Blank free float counted as 1.0 for {int(ff.reindex(cols).isna().sum())} of {len(cols)} rankable names.")
    res["formations"] = [str(d.date()) for d in fdates]
    res["survivorship"] = surv

    # ---------------- step 04: point-in-time tripwires ----------------
    print("\nPOINT-IN-TIME TRIPWIRES")
    f_test = [fdates[0], fdates[len(fdates) // 2]]
    pit = []
    for f in f_test:
        i = px.index.get_loc(f)
        u0, *_ = momentum_universe(px, ffmcap, i)
        l0, s0, _, _ = screens(px, bench["NIFTY500 MOMENTUM 50"], u0, i)
        rng = np.random.default_rng(1)
        px_f = px.copy()
        px_f.iloc[i + 1:] = px_f.iloc[i + 1:] * rng.uniform(0.3, 3.0, size=px_f.iloc[i + 1:].shape)
        mc_f = ffmcap.copy()
        mc_f.iloc[i + 1:] = mc_f.iloc[i + 1:] * 7.0
        b_f = bench["NIFTY500 MOMENTUM 50"].copy()
        b_f.iloc[i + 1:] = b_f.iloc[i + 1:] * rng.uniform(0.3, 3.0, size=len(b_f.iloc[i + 1:]))
        u1, *_ = momentum_universe(px_f, mc_f, i)
        l1, s1, _, _ = screens(px_f, b_f, u1, i)
        same = (u0 == u1) and (l0 == l1) and (s0 == s1)
        pit.append({"formation": str(f.date()), "book_unchanged_after_scrambling_the_future": same})
        print(f"  {'PASS' if same else 'FAIL'}  formation {f.date()}: universe and both legs unchanged when every "
              "price, market cap and index level after the formation close is scrambled")
    res["pit_future_scramble"] = pit

    # ---------------- step 05: build and execute ----------------
    print("\nBuilding the books...")
    rows, ew_rows, lo_rows, recs = build_books(px, adj, alive, ffmcap, adv, bench["NIFTY500 MOMENTUM 50"],
                                               bench["NIFTY 50"], fdates)
    for r in recs:
        print(f"  {r['formation'].date()}  parent {r['parent_size']}  momentum-eligible {r['momentum_eligible']}  "
              f"screened {r['n_screened']}  k {r['k']}  long {len(r['long'])}  short {len(r['short'])}  "
              f"{'130/30 formed' if r['formed'] else 'EMPTY LEG -> equal-weight 50 long only'}")
    n_formed = sum(r["formed"] for r in recs)
    print(f"  130/30 book formed in {n_formed} of {len(recs)} half-years")

    # tripwire on the position frame the engine actually sees
    print("\nLOOK-AHEAD TRIPWIRES (held weight[t] after the engine's shift vs return[t], return[t+1]):")
    wframe = pd.DataFrame(np.nan, index=px.index, columns=px.columns)
    for d, w in rows.items():
        wframe.loc[d] = w.values
    wframe = wframe.ffill()
    rets = px.pct_change(fill_method=None)
    held_cols = [c for c in px.columns if (wframe[c].abs() > 0).any()]
    trip = {}
    for label, sig in (("main book weights", wframe[held_cols].shift(1 + ENGINE_LAG)),
                       ("planted same-bar leak", rets[held_cols]),
                       ("planted next-bar leak", rets[held_cols].shift(-1))):
        try:
            assert_causal(sig, rets[held_cols], label=label)
            ok = label == "main book weights"
            print(f"  {'PASS' if ok else 'BROKEN'}  {label}{'' if ok else ' was NOT caught'}")
        except LookaheadError as e:
            ok = label != "main book weights"
            print(f"  {'PASS' if ok else 'FAIL'}  {label}{' correctly caught' if ok else ': ' + str(e)}")
        trip[label] = ok
    res["tripwires"] = trip

    print("\nRunning the books (30bp round trip, 150bp a year borrow on short notional; trade at t+1 close)...")
    r_main = run_book(px, alive, rows, name="MAIN 130/30")
    r_ew = run_book(px, alive, ew_rows, borrow=0.0, name="EW rebuilt 50")
    r_lo = run_book(px, alive, lo_rows, borrow=0.0, name="long leg only")
    rows_mega, _, _, recs_mega = build_books(px, adj, alive, ffmcap, adv, bench["NIFTY500 MOMENTUM 50"],
                                             bench["NIFTY 50"], fdates, mega=True)
    r_mega = run_book(px, alive, rows_mega, name="top-30 mega-cap 130/30")
    r_idx = run_book(px, alive, index_style_rows(px, ffmcap, fdates), borrow=0.0, name="index-weighted rebuilt 50")
    diag = r_main.meta["allocator_diagnostics"]
    print(f"  MAIN max gross {diag['max_gross']:.3f}; days drifted above the card's 2.0: {diag['days_drifted_above_2']} "
          f"(engine cap {GROSS_CAP}: {'never reached' if diag['max_gross'] <= GROSS_CAP else 'REACHED, a rescale traded'}); "
          f"names closed mid-hold and respread {diag['names_respread']}; engine forced long exits {r_main.meta['forced_exits']}")
    res["main_diagnostics"] = {**diag, "forced_exits": r_main.meta["forced_exits"], "n_formed": n_formed,
                               "n_half_years": len(recs)}

    f0 = fdates[0]
    books = {"130/30 four-screen book (MAIN)": r_main.value, "Equal-weight rebuilt Momentum 50": r_ew.value,
             "Long leg only, 100%": r_lo.value, "Top-30 mega-cap 130/30 (vs NIFTY 50)": r_mega.value,
             "Index-weighted rebuilt 50 (fidelity check)": r_idx.value}
    lv = {k: live(v, f0) for k, v in books.items()}
    for bname in ("NIFTY 500", "NIFTY500 MOMENTUM 50", "NIFTY 50"):
        lv[bname] = live(bench[bname], f0)
    summary = pd.DataFrame([stats(v, r, k) for k, (v, r) in lv.items()])
    head_names = ["130/30 four-screen book (MAIN)", "NIFTY 500"]
    headline = summary[summary["name"].isin(head_names)]
    appendix = summary[~summary["name"].isin(head_names)]
    pd.set_option("display.width", 220)
    v_main, ret_main = lv["130/30 four-screen book (MAIN)"]
    print("\n" + "=" * 110)
    print(f"RESULTS, value from the first formation close {f0.date()} (first trade {ret_main.index[0].date()}) "
          f"to {v_main.index[-1].date()}; costs and borrow inside the books")
    print("=" * 110)
    print(headline.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nAPPENDIX (comparators for the card's must-beat tests):")
    print(appendix.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    headline.to_csv(os.path.join(OUT, f"{SLUG}_comparison.csv"), index=False)
    appendix.to_csv(os.path.join(OUT, f"{SLUG}_comparators_appendix.csv"), index=False)
    res["comparison"] = headline.to_dict("records")
    res["comparators_appendix"] = appendix.to_dict("records")

    # fidelity of the rebuilt list
    mom_r = lv["NIFTY500 MOMENTUM 50"][1]
    fid = {"corr_index_weighted_vs_official": float(lv["Index-weighted rebuilt 50 (fidelity check)"][1].corr(mom_r)),
           "corr_equal_weight_vs_official": float(lv["Equal-weight rebuilt Momentum 50"][1].corr(mom_r)),
           "tracking_error_index_weighted": float((lv["Index-weighted rebuilt 50 (fidelity check)"][1] - mom_r).std() * np.sqrt(252))}
    fid["passes_0_95"] = fid["corr_index_weighted_vs_official"] >= 0.95
    print(f"\nFIDELITY of the rebuilt 50 (card bar: daily-return correlation >= 0.95 with the official index):")
    print(f"  index-weighted rebuilt 50 vs NIFTY500 MOMENTUM 50: corr {fid['corr_index_weighted_vs_official']:.3f}, "
          f"tracking error {fid['tracking_error_index_weighted']:.2%} a year -> "
          f"{'result may be called on the index companies' if fid['passes_0_95'] else 'LABEL AS MOMENTUM LOOKALIKE'}")
    print(f"  equal-weight rebuilt 50 vs official: corr {fid['corr_equal_weight_vs_official']:.3f}")
    res["fidelity"] = fid

    # half-year table
    px_last = px.ffill()
    trade_days = [px.index[px.index.get_loc(f) + 1] for f in fdates] + [v_main.index[-1]]
    hy = []
    for j, r in enumerate(recs):
        d0, d1 = trade_days[j], trade_days[j + 1]
        g = lambda s: float(s.loc[d1] / s.loc[d0] - 1.0)
        hy.append({"formation": str(r["formation"].date()), "hold_from": str(d0.date()), "hold_to": str(d1.date()),
                   "formed_130_30": r["formed"], "n_long": len(r["long"]), "n_short": len(r["short"]),
                   "book": g(r_main.value), "momentum50_index": g(bench["NIFTY500 MOMENTUM 50"]),
                   "nifty500": g(bench["NIFTY 500"]), "ew_rebuilt_50": g(r_ew.value), "long_leg_only": g(r_lo.value),
                   "long_leg_ew_buy_hold": leg_return(px_last, r["long"], d0, d1),
                   "short_leg_ew_buy_hold": leg_return(px_last, r["short"], d0, d1),
                   "mega30_book": g(r_mega.value), "mega30_formed": recs_mega[j]["formed"]})
    hy = pd.DataFrame(hy)
    hy["book_minus_momentum50"] = hy["book"] - hy["momentum50_index"]
    hy["short_minus_momentum50"] = hy["short_leg_ew_buy_hold"] - hy["momentum50_index"]
    print("\nHALF-YEARS (holding period after each formation; the last ends at the data's end, 2026-09-18):")
    print(hy.drop(columns=["hold_to"]).to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    hy.to_csv(os.path.join(OUT, f"{SLUG}_half_years.csv"), index=False)
    formed = hy[hy["formed_130_30"]]
    hy_sum = {"n_formed": int(len(formed)), "n_half_years": int(len(hy)),
              "formed_beats_momentum50": int((formed["book_minus_momentum50"] > 0).sum()),
              "mean_short_minus_momentum50_formed": float(formed["short_minus_momentum50"].mean()) if len(formed) else None,
              "chained_book_formed_only": float((1 + formed["book"]).prod() - 1) if len(formed) else None,
              "chained_momentum50_formed_only": float((1 + formed["momentum50_index"]).prod() - 1) if len(formed) else None,
              "mega30_n_formed": int(hy["mega30_formed"].sum())}
    print(f"  130/30 formed in {hy_sum['n_formed']} of {hy_sum['n_half_years']}; beats the momentum index in "
          f"{hy_sum['formed_beats_momentum50']} of those; mean short-leg minus momentum index (formed) "
          f"{hy_sum['mean_short_minus_momentum50_formed']}; formed half-years chained: book "
          f"{hy_sum['chained_book_formed_only']}, momentum index {hy_sum['chained_momentum50_formed_only']}")
    res["half_year_summary"] = hy_sum

    # formation log
    fl = []
    for r in recs:
        m = r["metrics"]
        for c in r["universe"]:
            leg = "long" if c in r["long"] else ("short" if c in r["short"] else "")
            row = {"formation": str(r["formation"].date()), "security_id": c, "symbol": names.get(c, c), "leg": leg,
                   "weight": float(rows[r["formation"]][c])}
            if c in m.index:
                row.update({k: float(v) for k, v in m.loc[c].items()})
            fl.append(row)
    pd.DataFrame(fl).to_csv(os.path.join(OUT, f"{SLUG}_formations.csv"), index=False)

    # exposure and costs
    w = r_main.weights.loc[v_main.index]
    gross, net = w.abs().sum(axis=1), w.sum(axis=1)
    ann_to = float(r_main.turnover.loc[ret_main.index].mean() * 252 * 2)
    costs_paid = float(r_main.costs.loc[ret_main.index].sum())
    print(f"\nEXPOSURE: mean gross {gross.mean():.2f}, mean net {net.mean():.2f}, names long/short (mean) "
          f"{(w > 1e-12).sum(axis=1).mean():.1f}/{(w < -1e-12).sum(axis=1).mean():.1f}; two-way turnover "
          f"{ann_to:.0%} a year; costs and borrow paid {costs_paid:.2%} of NAV")
    res["exposure"] = {"mean_gross": float(gross.mean()), "mean_net": float(net.mean()), "annual_turnover_two_way": ann_to,
                       "costs_and_borrow_paid": costs_paid}

    # ---------------- step 06: research validation ----------------
    print("\nVALIDATION (code computes; nothing below is estimated by hand)")
    rf = pd.Series((1 + RF_ANNUAL) ** (1 / 252) - 1, index=px.index)
    boot = bootstrap_sharpe_ci(ret_main, block_size=BLOCK, n_resamples=2000, rf_daily=rf, seed=0)
    print(f"  MAIN Sharpe over 6%, 90% block-bootstrap CI (block {BLOCK}d): [{boot.ci_low:.2f}, {boot.ci_high:.2f}] "
          f"point {boot.point_estimate:.2f}, {boot.fraction_positive:.0%} positive")
    res["bootstrap_main"] = {"ci_low": boot.ci_low, "ci_high": boot.ci_high, "point": boot.point_estimate,
                             "frac_positive": boot.fraction_positive}
    paired = {}
    for other in ("NIFTY 500", "NIFTY500 MOMENTUM 50", "Equal-weight rebuilt Momentum 50", "Long leg only, 100%"):
        d = (ret_main - lv[other][1].reindex(ret_main.index).fillna(0.0)).fillna(0.0)
        b = bootstrap_sharpe_ci(d, block_size=BLOCK, n_resamples=2000, seed=0)
        paired[other] = {"ci_low": b.ci_low, "ci_high": b.ci_high, "point": b.point_estimate,
                         "p_not_positive": 1.0 - b.fraction_positive}
        print(f"  PAIRED MAIN minus {other}: Sharpe of the difference [{b.ci_low:.2f}, {b.ci_high:.2f}] point "
              f"{b.point_estimate:.2f}; P(<= 0) = {1 - b.fraction_positive:.3f}")
    res["paired"] = paired
    dsr = deflated_sharpe_from_returns(ret_main, n_trials=N_CONFIGS_TRIED, trial_sharpe_std=0.3, rf_daily=rf)
    n_wide = N_CONFIGS_TRIED + 9
    dsr_wide = deflated_sharpe_from_returns(ret_main, n_trials=n_wide, trial_sharpe_std=0.3, rf_daily=rf)
    print(f"  Deflated Sharpe over 6% (n_trials={N_CONFIGS_TRIED}, the card's count): {dsr:.3f}; "
          f"with the {n_wide - N_CONFIGS_TRIED} sensitivities counted ({n_wide}): {dsr_wide:.3f}")
    res["deflated_sharpe"] = float(dsr)
    res["deflated_sharpe_wide"] = {"n_trials": n_wide, "value": float(dsr_wide)}

    print("\n  OUT-OF-SAMPLE STABILITY (anchored walk-forward, Sharpe over 6%):")
    windows = walk_forward_windows(v_main.index, n_folds=4, min_train_years=1.0)
    oos = oos_stability_summary(v_main, ret_main, windows, rf_daily=rf, min_obs=60)
    print(oos.to_string(index=False) if not oos.empty else "    not enough history")
    oos.to_csv(os.path.join(OUT, f"{SLUG}_oos_stability.csv"), index=False)
    res["oos"] = oos.to_dict("records")

    print("\n  PARAMETER SENSITIVITY (screen fraction, base 0.40):")
    def rerun_frac(fr):
        if fr == FRAC:
            return live(r_main.value, f0)
        rr, *_ = build_books(px, adj, alive, ffmcap, adv, bench["NIFTY500 MOMENTUM 50"], bench["NIFTY 50"], fdates, frac=fr)
        return live(run_book(px, alive, rr, name=f"frac {fr}").value, f0)
    sweep = parameter_sensitivity_sweep(rerun_frac, "screen_fraction", [0.30, 0.40, 0.50])
    print(sweep.to_string(index=False))
    verdict = sensitivity_verdict(sweep, FRAC, "screen_fraction")
    print("  " + verdict)
    sweep.to_csv(os.path.join(OUT, f"{SLUG}_sensitivity_fraction.csv"), index=False)
    res["fraction_sweep"] = sweep.to_dict("records")
    res["fraction_verdict"] = verdict

    print("\n  CARD SENSITIVITIES:")
    sens = []
    rr_lag, _, _, recs_lag = build_books(px, adj, alive, ffmcap, adv, bench["NIFTY500 MOMENTUM 50"], bench["NIFTY 50"],
                                         fdates, lagged=True)
    rr_cash, *_ = build_books(px, adj, alive, ffmcap, adv, bench["NIFTY500 MOMENTUM 50"], bench["NIFTY 50"],
                              fdates, fallback="cash")
    rr_liq, _, _, recs_liq = build_books(px, adj, alive, ffmcap, adv, bench["NIFTY500 MOMENTUM 50"], bench["NIFTY 50"],
                                         fdates, liquid_shorts=True)
    for label, rr, kw, rc in (("base case", None, {}, recs),
                              ("list rebuilt one quarter earlier", rr_lag, {}, recs_lag),
                              ("cash at 6% in empty-leg half-years", rr_cash, {"rf": rf}, recs),
                              ("short leg: names traded every day of the window", rr_liq, {}, recs_liq),
                              ("top-30 mega-cap vs NIFTY 50 (paper's segment)", None, {}, recs_mega)):
        if label == "base case":
            v = r_main.value
        elif label.startswith("top-30"):
            v = r_mega.value
        else:
            v = run_book(px, alive, rr, name=label, **kw).value
        vv, rv = live(v, f0)
        s = stats(vv, rv, label)
        s["n_formed"] = int(sum(x["formed"] for x in rc))
        s["minus_momentum50_cagr"] = s["cagr"] - stats(*lv["NIFTY500 MOMENTUM 50"], "m")["cagr"]
        sens.append(s)
    sens = pd.DataFrame(sens)
    print(sens.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    sens.to_csv(os.path.join(OUT, f"{SLUG}_sensitivities.csv"), index=False)
    res["sensitivities"] = sens.to_dict("records")

    print("\n  COST AND BORROW SWEEP (MAIN book):")
    cs = []
    for sp, bb in ((30, 150), (60, 150), (90, 150), (30, 0), (30, 50), (30, 300), (30, 500), (60, 500)):
        v = r_main.value if (sp, bb) == (SPREAD_BPS, BORROW_BPS) else run_book(px, alive, rows, spread=sp, borrow=bb).value
        vv, rv = live(v, f0)
        s = stats(vv, rv, f"{sp}bp / {bb}bp")
        cs.append({"spread_bps": sp, "borrow_bps": bb, "cagr": s["cagr"], "vol": s["vol"],
                   "sharpe_vs_6pct": s["sharpe_vs_6pct"], "max_dd": s["max_dd"],
                   "minus_nifty500_cagr": s["cagr"] - stats(*lv["NIFTY 500"], "n")["cagr"],
                   "minus_momentum50_cagr": s["cagr"] - stats(*lv["NIFTY500 MOMENTUM 50"], "m")["cagr"]})
    cs = pd.DataFrame(cs)
    print(cs.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    cs.to_csv(os.path.join(OUT, f"{SLUG}_cost_borrow_sweep.csv"), index=False)
    res["cost_borrow_sweep"] = cs.to_dict("records")

    # ---------------- step 07: portfolio validation ----------------
    print("\n  FACTOR FINGERPRINT (excess of 6%) vs NIFTY 500 and the NIFTY500 factor sleeves (backfilled, price-return):")
    fnames = ["NIFTY 500", "NIFTY500 MOMENTUM 50", "NIFTY500 VALUE 50", "NIFTY500 QUALITY 50", "NIFTY500 LOW VOLATILITY 50"]
    fr = pd.DataFrame({n: bench[n].reindex(v_main.index).pct_change(fill_method=None) for n in fnames}).iloc[1:]
    fp = factor_fingerprint(ret_main, fr, rf_daily=rf)
    if "error" in fp:
        print(f"    unavailable: {fp['error']}")
    else:
        print(f"    alpha (ann.) {fp['alpha_ann']:.2%}   alpha t (HAC) {fp['alpha_t_hac']:.2f}   R^2 {fp['r_squared']:.2f}   n {fp['n_obs']}")
        print(f"    loadings: { {k: round(v, 3) for k, v in fp['loadings'].items()} }")
        res["factor_fingerprint"] = {k: fp[k] for k in ("alpha_ann", "alpha_t_hac", "r_squared", "n_obs", "loadings") if k in fp}

    if not a.no_charts:
        try:
            from universal_backtester.clean_charts import save_clean_charts
            charts = save_clean_charts(
                v_main, lv["NIFTY 500"][0], outdir=os.path.join(OUT, "charts"), tag=SLUG,
                strategy_name="130/30 four-screen book", benchmark_name="NIFTY 500",
                weights=r_main.weights.loc[v_main.index],
                sleeve=lv["NIFTY500 MOMENTUM 50"][0], sleeve_name="NIFTY500 Momentum 50 index",
                footnote="Price return. Rebuilt Momentum 50 lookalike; 30bp round trip and 150bp/yr borrow inside the book.")
            res["charts"] = [os.path.relpath(c, REPO) for c in charts]
            print("\n  charts:\n    " + "\n    ".join(charts))
        except Exception as e:  # charts are a convenience; never fail the run on them
            print(f"\n  charts skipped: {e!r}")

    # ---------------- Gate B inputs, judged by the repo's own gate_b() ----------------
    from ros.cards.schema import load_card
    from ros.governance.gates import gate_b
    research = {"deflated_sharpe": {"deflated_sharpe_prob": float(dsr),
                                    "interpretation": f"n_trials={N_CONFIGS_TRIED} (the card's own count), trial Sharpe std 0.3, over a flat 6%"},
                "oos_min_sharpe": float(oos["sharpe"].min()) if not oos.empty else None,
                "bootstrap_p_not_positive": float(paired["NIFTY 500"]["p_not_positive"])}
    portfolio = {"alpha_t_hac": (float(fp["alpha_t_hac"]) if "error" not in fp else None),
                 "annual_turnover": ann_to}
    gb = gate_b(load_card(CARD), research, portfolio)
    print("\n" + "=" * 110)
    print("GATE B CRITERIA, as the repo's own gate_b() computes them from this run (decision stays PENDING)")
    print("  'advantage over benchmark' = paired block bootstrap, MAIN minus NIFTY 500 (price-return)")
    print("=" * 110)
    print(gb.render())
    res["gate_b"] = gb.to_dict()
    res["gate_b_inputs"] = {"research": research, "portfolio": portfolio}

    nret = lv["NIFTY 500"][1].reindex(ret_main.index)
    mret = lv["NIFTY500 MOMENTUM 50"][1].reindex(ret_main.index)
    daily = pd.DataFrame({"strategy": ret_main, "benchmark": nret, "sleeve": mret})
    daily.index.name = "date"
    daily.to_csv(os.path.join(OUT, f"{SLUG}_daily_returns.csv"), float_format="%.10f")
    if a.handoff:
        os.makedirs(a.handoff, exist_ok=True)
        d2 = daily.copy()
        d2.index = d2.index.strftime("%Y-%m-%d")
        d2.to_csv(os.path.join(a.handoff, "daily_returns.csv"), float_format="%.10f")
    json.dump(res, open(os.path.join(OUT, f"{SLUG}_results.json"), "w", encoding="utf-8"), indent=1, default=str)
    print(f"\nResults written to {OUT} ({SLUG}_*). Gate B is a human decision and is NOT assigned by this script.")


if __name__ == "__main__":
    main()
