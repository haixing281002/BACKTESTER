# Quant AI Researcher
"""Phase 4, part 2: reference strategies on real data. None of these should pass the hard blocks and a green scorecard.

The benchmark itself, the equal-weight universe, random 30-stock books rebalanced monthly, and NSE's Momentum 50 index.
Writes statistics only, into docs/gate_b/calibration/reference.csv: thresholds are applied in analyse.py. Prices are the
Ace file, membership is point-in-time and keeps delisted names, and everything is price return. No strategy from a paper
is used here.

    python scripts/gate_v2/reference.py --random 200
"""
from __future__ import annotations

import argparse
import itertools
import os
import sys

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
from ros import config
from ros.data import ace, nifty500
from ros.data.loaders import load_nse_workbook_combined
from ros.data.sources import NSE_INDEX_WORKBOOK
from ros.metrics import core
from ros.validation import gate_evidence as ev

OUT = os.path.join(REPO, "docs", "gate_b", "calibration", "reference.csv")
START, END = "2014-01-01", "2026-09-18"     # 12.7 years to the benchmark's last close
CASH_ANNUAL = float(config.calibration()["cash_annual"])     # these books have no card, so the calibration file states it
CASH = core.daily_cash(CASH_ANNUAL)
FACTORS = {"market": "NIFTY 500", "midcap150": "NIFTY MIDCAP 150", "smallcap250": "NIFTY SMALLCAP 250", "momentum": "NIFTY500 MOMENTUM 50",
           "value": "NIFTY500 VALUE 50", "quality": "NIFTY500 QUALITY 50", "low_vol": "NIFTY500 LOW VOLATILITY 50"}
_S: dict = {}


def load():
    """Daily returns for every ever-member, membership on the same dates, and index returns on the Ace calendar."""
    idx_levels, _ = load_nse_workbook_combined(NSE_INDEX_WORKBOOK)
    close = ace.wide("close").loc[pd.Timestamp(START) - pd.Timedelta(days=10):END]
    m = nifty500.load_membership(source="nifty500_members_v2")
    cols = [c for c in close.columns if c in set(m["isin"])]
    close = close[cols]
    # the last price carries forward, so a suspended name's return lands on the day it resumes; a name that stops trading stays held until it leaves the list
    rets = close.ffill().pct_change(fill_method=None).fillna(0.0).loc[START:END]
    members = nifty500.membership_panel(close.index, columns=cols, m=m)
    priced = close.notna()
    levels = idx_levels.reindex(close.index).ffill()
    idx_rets = levels.pct_change(fill_method=None).loc[rets.index]
    return rets, members & priced, idx_rets


def book_returns(rets: pd.DataFrame, eligible: pd.DataFrame, cost_bp: float, pick) -> pd.Series:
    """Monthly rebalanced equal-weight book. The signal is each month's last session, the fill the next session's close, so
    a holding earns returns from the day after its fill. `pick(names)` chooses from the names eligible at the signal."""
    cal = rets.index
    month_end = pd.Series(cal, index=cal).groupby([cal.year, cal.month]).last().to_numpy()
    arr = rets.to_numpy()
    pos = {d: i for i, d in enumerate(cal)}
    out = np.zeros(len(cal))
    columns = np.array(rets.columns)
    col_at = {c: i for i, c in enumerate(columns)}
    prev: dict[str, float] = {}
    # the first book is chosen at the last session before the window and filled on its first day, so no month is out of the market
    before = eligible.index[eligible.index < cal[0]][-1]
    schedule = [(before, 0, pos[month_end[0]] + 1)] + [(s, pos[s] + 1, pos[e] + 1) for s, e in itertools.pairwise(month_end)]
    for sig, i_fill, i_end in schedule:
        names = columns[eligible.loc[sig].to_numpy()]
        chosen = pick(names)
        if not len(chosen):
            continue
        ids = [col_at[c] for c in chosen]
        w0 = 1.0 / len(ids)
        turnover = sum(abs(w0 - prev.get(c, 0.0)) for c in chosen) + sum(v for c, v in prev.items() if c not in set(chosen))
        out[i_fill] -= turnover * cost_bp / 2.0 / 1e4     # charged on the fill day, whose close is the entry price
        hold = arr[i_fill + 1:i_end + 1][:, ids]
        if not len(hold):
            continue
        nav = np.cumprod(1.0 + hold, axis=0).mean(axis=1)
        out[i_fill + 1:i_end + 1] += np.diff(np.r_[1.0, nav]) / np.r_[1.0, nav[:-1]]
        prev = dict(zip(chosen, np.cumprod(1.0 + hold, axis=0)[-1] * w0 / nav[-1]))
    return pd.Series(out, index=cal)


def stats_row(name: str, r: pd.Series, b: pd.Series, factors: pd.DataFrame, floors: dict[str, float]) -> dict:
    v, vb = core.value_from_returns(r), core.value_from_returns(b)
    row = {"name": name, "cagr": core.cagr(v), "bench_cagr": core.cagr(vb), "edge": core.cagr(v) - core.cagr(vb), "sharpe": core.sharpe(r, CASH),
           "bench_sharpe": core.sharpe(b, CASH), "max_dd": core.max_drawdown(v), "ir": core.information_ratio(r, b) if (r - b).std() > 0 else float("nan"),
           "boot_p": ev.paired_bootstrap(r, b, CASH)["p"]}
    d = ev.deflated_sharpe(r, b, CASH, 1.0, floors["1overT"], null="benchmark")
    row["dsr_bench_n1"] = d["dsr"]
    row["dsr_zero_n1"] = ev.deflated_sharpe(r, b, CASH, 1.0, floors["1overT"], null="zero")["dsr"]
    sp = ev.sub_period(r, b, CASH)
    row.update(sp_n=sp["n"], sp_pos=sp["positive"], sp_worst=sp["worst"])
    if (r - b).std() > 0:
        fa = ev.factor_alpha(r, factors, CASH, leave_one_out=False)
        row.update(alpha=fa.get("alpha_ann"), alpha_t=fa.get("alpha_t_hac"), r2=fa.get("r_squared"))
    return row


def _init(cost_bp):
    rets, elig, idx = load()
    _S.update(rets=rets, elig=elig, idx=idx, cost_bp=cost_bp, factors=idx[list(FACTORS.values())].rename(columns={v: k for k, v in FACTORS.items()}))


def _one_random(seed: int) -> dict:
    rng = np.random.default_rng([20261105, seed])
    r = book_returns(_S["rets"], _S["elig"], _S["cost_bp"], lambda names: rng.choice(names, size=min(30, len(names)), replace=False))
    return stats_row(f"Random 30 #{seed}", r, _S["factors"]["market"], _S["factors"], {"1overT": 1 / 12.7})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--random", type=int, default=200)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    cost_bp = float(config.calibration()["reference_cost_bp"])
    _init(cost_bp)
    b = _S["factors"]["market"]
    fl = {"1overT": 1 / 12.7}
    rows = [stats_row("Benchmark (NIFTY 500)", b, b, _S["factors"], fl),
            stats_row("Equal-weight NIFTY 500 members, monthly, net", book_returns(_S["rets"], _S["elig"], cost_bp, lambda names: names), b, _S["factors"], fl),
            stats_row("NSE NIFTY500 Momentum 50 index", _S["factors"]["momentum"], b, _S["factors"], fl)]
    if a.random:
        from multiprocessing import Pool
        with Pool(a.workers, initializer=_init, initargs=(cost_bp,)) as p:
            rows += p.map(_one_random, range(a.random), chunksize=4)
    pd.DataFrame(rows).to_csv(OUT, index=False, float_format="%.6g")
    print(pd.DataFrame(rows).head(6).T.round(3).to_string())
    print("->", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
