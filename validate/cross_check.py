#!/usr/bin/env python3
"""Run the engine and the independent implementation side by side.

    python validate/cross_check.py
    python validate/cross_check.py --card cards/<card>.yaml --excel

Prints, for every quantity both implementations compute, the two values and the
absolute difference. Exits non-zero if anything exceeds tolerance, so it can be
wired into CI.

WHAT AGREEMENT PROVES, AND WHAT IT DOES NOT

Proves: the engine's arithmetic is right. NAV compounding, cost timing, turnover
definition, the causal lag, month-end rebalance selection, and every headline
metric are confirmed by a second implementation that shares no code, uses unit-
and-cash accounting instead of weights, and parses the workbook with a different
library.

Does NOT prove: that the assumptions are right. Both implementations charge 30bp
because the card says 30bp. Both use a flat 6% cash proxy because there is no
Indian risk-free series. Both inherit the backfill bias in the indices. Two
implementations agreeing on a wrong assumption agree precisely and are precisely
wrong. Those questions belong to Gate A and Gate B, and no cross-check retires
them.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from validate import independent as ind          # the clean-room side

# The engine under test.
from ros.cards.schema import load_card
from ros.data.loaders import load_nse_factor_workbook, synthetic_cash_series
from ros.engine.backtest import Backtester, rebalance_dates
from ros.engine.prepare import build_signal_inputs
from ros.engine.templates import build_allocator
from ros.validation import metrics as M

XLSX = "data/raw/Factor_Indices_Historical_Price_Data.xlsx"
CARD = "cards/devanathan_2026_india_factor_adaptation.yaml"

# Quantities that are equal by construction get an exact-arithmetic tolerance.
# Nothing here is a fitted number, so a "close enough" tolerance would only hide
# the kind of bug this file exists to find.
TOL = 1e-10
ROWS: list[tuple[str, float, float, float, bool]] = []


def check(label: str, a: float, b: float, tol: float = TOL) -> bool:
    if (isinstance(a, float) and np.isnan(a)) and (isinstance(b, float) and np.isnan(b)):
        diff, ok = 0.0, True
    else:
        diff = abs(float(a) - float(b))
        ok = diff <= tol
    ROWS.append((label, float(a), float(b), diff, ok))
    return ok


def hr(ch="-"):
    print(ch * 92)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", default=CARD)
    ap.add_argument("--xlsx", default=XLSX)
    ap.add_argument("--cash-rate", type=float, default=0.06)
    ap.add_argument("--excel", action="store_true",
                    help="also write an Excel workbook with live formulas")
    args = ap.parse_args()

    print("=" * 92)
    print("  INDEPENDENT CROSS-CHECK -- engine vs a clean-room reimplementation")
    print("=" * 92)

    card = load_card(args.card)
    assets = list(card.universe.assets)

    # ---- 1. the data itself -------------------------------------------
    print("\n[1] DATA  (pandas.read_excel  vs  raw openpyxl)")
    hr()
    eng_frame, prov = load_nse_factor_workbook(args.xlsx)
    ind_frame = ind.read_workbook(args.xlsx)

    shared = [c for c in eng_frame.columns if c in ind_frame.columns]
    print(f"    engine parsed : {eng_frame.shape[1]} series x {eng_frame.shape[0]} rows")
    print(f"    independent   : {ind_frame.shape[1]} series x {ind_frame.shape[0]} rows")
    print(f"    shared series : {len(shared)}")
    common_idx = eng_frame.index.intersection(ind_frame.index)
    check("data: rows in common", len(common_idx), len(eng_frame.index), tol=0)
    worst = 0.0
    for c in shared:
        a = eng_frame.loc[common_idx, c].astype(float)
        b = ind_frame.loc[common_idx, c].astype(float)
        both = a.notna() & b.notna()
        if both.any():
            worst = max(worst, float((a[both] - b[both]).abs().max()))
    check("data: worst price difference", worst, 0.0)

    # ---- 2. shared inputs ---------------------------------------------
    prices = eng_frame[assets].dropna()
    idx = prices.index
    rf_eng = synthetic_cash_series(idx, args.cash_rate)
    rf_ind = ind.cash_series(idx, args.cash_rate)
    check("cash proxy: daily rate", float(rf_eng.iloc[0]), float(rf_ind.iloc[0]))

    lookback = card.signal.lookback_days or 21
    lag = card.signal.lag_days
    spread = card.costs.spread_bps
    warm = lookback + 5
    w_eq = np.ones(len(assets)) / len(assets)

    rets_eng = prices.pct_change()
    sig_eng = build_signal_inputs(
        prices=prices, assets=assets, lookback=lookback,
        strategic_weights="equal", alpha_halflife=None, alpha_source="none",
    )["sigma_bench"]
    sig_ind = ind.trailing_portfolio_vol(rets_eng, w_eq, lookback)
    both = sig_eng.notna() & sig_ind.notna()
    check("sigma_bench: worst difference",
          float((sig_eng[both] - sig_ind[both]).abs().max()), 0.0, tol=1e-12)
    check("sigma_bench: non-null count", int(sig_eng.notna().sum()),
          int(sig_ind.notna().sum()), tol=0)

    reb_eng = rebalance_dates(idx, "monthly")
    reb_ind = ind.month_end_dates(idx)
    check("rebalance dates: count", len(reb_eng), len(reb_ind), tol=0)
    check("rebalance dates: mismatches",
          int((pd.DatetimeIndex(reb_eng) != pd.DatetimeIndex(reb_ind)).sum()), 0, tol=0)

    # ---- 3. the backtests ---------------------------------------------
    scenarios = [
        ("equal-weight, fully invested", "fixed_weight",
         {"weights": "equal"}, False, None),
        ("equal-weight, cash allowed", "fixed_weight",
         {"weights": "equal"}, True, None),
        ("vol-target 18%, cash allowed", "vol_target",
         {"weights": "equal", "target_vol": 0.18}, True, 0.18),
    ]

    results = {}
    for label, template, params, allow_cash, tvol in scenarios:
        print(f"\n[3] BACKTEST  {label}")
        hr()

        eng_bt = Backtester(prices=prices, assets=assets, rf_daily=rf_eng,
                            spread_bps=spread, lag_days=lag, allow_cash=allow_cash)
        p = dict(params)
        if p.get("weights") == "equal":
            p["weights"] = {a: 1.0 / len(assets) for a in assets}
        eng_res = eng_bt.run(allocator=build_allocator(template, assets, **p),
                             rebalance="monthly", sigma_bench=sig_eng,
                             name=label, warmup=warm)

        ind_bt = ind.UnitsBacktest(prices=prices, assets=assets, rf_daily=rf_ind,
                                   spread_bps=spread, lag_days=lag,
                                   allow_cash=allow_cash)
        if tvol is None:
            fn = ind.fixed_weight_fn(w_eq)
        else:
            fn = ind.vol_target_fn(w_eq, tvol, ind.shift_causal(sig_ind, lag))
        ind_res = ind_bt.run(fn, reb_ind, warmup=warm, name=label)

        ev, iv = eng_res.value, ind_res["value"]
        check(f"{label}: final NAV", float(ev.iloc[-1]), float(iv.iloc[-1]))
        check(f"{label}: worst NAV difference over {len(ev):,} days",
              float((ev - iv).abs().max()), 0.0)
        check(f"{label}: rebalance count",
              int(eng_res.meta["n_rebalances"]), int(ind_res["n_rebalances"]), tol=0)
        check(f"{label}: total cost paid",
              float(eng_res.costs.sum()), float(ind_res["costs"].sum()))
        check(f"{label}: total turnover",
              float(eng_res.turnover.sum()), float(ind_res["turnover"].sum()))

        check(f"{label}: CAGR", M.cagr(ev), ind.cagr(iv))
        check(f"{label}: annualised vol",
              M.ann_vol(eng_res.returns), ind.ann_vol(ind_res["returns"].to_numpy()))
        check(f"{label}: max drawdown", M.max_drawdown(ev), ind.max_drawdown(iv))
        check(f"{label}: Sharpe (geometric)",
              M.sharpe_geometric(ev, eng_res.returns, rf_eng),
              ind.sharpe_geometric(iv, ind_res["returns"].to_numpy(), rf_ind.to_numpy()))
        check(f"{label}: Sharpe (conventional)",
              M.sharpe_conventional(eng_res.returns, rf_eng),
              ind.sharpe_conventional(ind_res["returns"].to_numpy(), rf_ind.to_numpy()))
        results[label] = (eng_res, ind_res)

    if args.excel:
        from validate import check_excel
        from validate.to_excel import write_workbook
        eng_res, _ = results["equal-weight, fully invested"]
        out = write_workbook(prices, assets, rf_eng, eng_res, spread, warm, reb_eng)
        print(f"\n[4] EXCEL AUDIT WORKBOOK -> {out}")
        hr()
        print("    Every cell is a live formula. Change a price, watch the NAV move.")

        # openpyxl writes formulas without evaluating them, so the workbook is
        # not verified until something actually calculates it.
        why = check_excel.available()
        if why:
            print(f"\n    NOT VERIFIED: the `formulas` evaluator is not installed ({why}).")
            print("    The formulas above have been WRITTEN but never CALCULATED.")
            print("    Install it and re-run to check them:  python -m pip install formulas")
        else:
            eng_metrics = {
                "final_nav": float(eng_res.value.iloc[-1]),
                "cagr": M.cagr(eng_res.value),
                "ann_vol": M.ann_vol(eng_res.returns),
                "max_dd": M.max_drawdown(eng_res.value),
                "cash_cagr": M.compounded_cash_cagr(rf_eng, eng_res.value.index),
                "sharpe_geometric": M.sharpe_geometric(eng_res.value, eng_res.returns, rf_eng),
                "sharpe_conventional": M.sharpe_conventional(eng_res.returns, rf_eng),
                "total_cost": float(eng_res.costs.sum()),
                "turnover": float(eng_res.turnover.sum()),
                "n_rebalances": float(eng_res.meta["n_rebalances"]),
            }
            print("    evaluating every formula in the workbook...")
            ok, xrows = check_excel.compare(out, eng_metrics)
            print(f"\n    {'formula':<28}{'Excel':>16}{'engine':>16}{'|diff|':>11}")
            hr()
            for label, xv, ev, diff, row_ok in xrows:
                print(f"  {'  ' if row_ok else 'XX'}{label:<26}{xv:>16.8g}"
                      f"{ev:>16.8g}{diff:>11.2g}")
            hr()
            ROWS.extend([(f"excel: {l}", x, e, d, o) for l, x, e, d, o in xrows])

    # ---- 5. report -----------------------------------------------------
    print("\n" + "=" * 92)
    print("  RESULTS")
    print("=" * 92)
    print(f"  {'quantity':<52}{'engine':>13}{'independent':>14}{'|diff|':>11}")
    hr()
    for label, a, b, diff, ok in ROWS:
        mark = "  " if ok else "XX"
        print(f"{mark}{label:<52}{a:>13.6g}{b:>14.6g}{diff:>11.2g}")
    hr()

    failed = [r for r in ROWS if not r[4]]
    print(f"  {len(ROWS) - len(failed)} of {len(ROWS)} agree to within {TOL:g}")

    print()
    if failed:
        print("  DISAGREEMENT. Each row marked XX is a number two independent")
        print("  implementations do not agree on. Do not use any report from this")
        print("  engine until it is explained.")
        return 1

    print("  Every quantity matches to floating-point exactness.")
    print()
    print("  What this establishes: the engine's ARITHMETIC is sound -- NAV")
    print("  compounding, cost timing, turnover, the causal lag, month-end")
    print("  rebalancing and all five headline metrics are confirmed by an")
    print("  implementation that shares no code with it.")
    print()
    print("  What it leaves open: the ASSUMPTIONS. Both sides charge 30bp because")
    print("  the card says so, both use a flat 6% cash proxy, both inherit the")
    print("  backfill bias in these indices. Agreeing on a wrong assumption is")
    print("  still wrong. That is Gate A and Gate B's job, and it stays theirs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
