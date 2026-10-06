"""Step 05 to 07 for cards/lee_swaminathan_1998_price_momentum_trading_volume.yaml, run AS DRAFTED.

Two data sources only, NSE bhavcopy and Screener.in, through the panel that
scripts/bhavcopy_screener_build.py writes. Nothing else enters except the NIFTY 500 / factor
sleeve closes used as benchmarks, which the card names.

What it runs (all from the same independent decile-by-tercile grid, J = 6 months):
  MAIN       buy R10V1 (top return decile, lowest turnover third), sell R1V3 (bottom return
             decile, highest turnover third); K = 6 overlapping tranches; 30bp round trip,
             100bp a year borrow on short notional; one-week (5 day) gap + the engine's 1 day.
  comparators plain momentum R10-R1, high-volume momentum R10V3-R1V3, the long leg alone R10V1,
             and the equal-weight eligible universe (no sort).
The card's rule is applied literally: a month where a needed cell has fewer than 15 names is
SKIPPED and the book carried forward. The count of skipped months is reported, not hidden.

The sort lives in build_cells() below (plain, testable code); the allocator
universal_backtester.allocators.TwoWayCellTranches only turns a +1/-1 cell indicator into
overlapping-tranche weights. The engine does all accounting, causal shifting and costs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from universal_backtester.allocators import build_allocator
from universal_backtester.data import load_banner_workbook, write_holdings_log
from universal_backtester.engine import Backtester, LookaheadError, assert_causal
from universal_backtester.metrics import ann_vol as _ann_vol
from universal_backtester.metrics import cagr as _cagr
from universal_backtester.metrics import max_drawdown as _mdd
from universal_backtester.tearsheet import compute_tearsheet, render_tearsheet
from universal_backtester.validation import (
    bootstrap_sharpe_ci, deflated_sharpe_from_returns, oos_stability_summary,
    parameter_sensitivity_sweep, sensitivity_verdict, walk_forward_windows,
)
from ros.validation.portfolio import factor_fingerprint

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL = os.path.join(REPO, "data", "raw", "master", "bhavcopy_screener_panel.csv")
INDEX_PATH = os.path.join(REPO, "data", "raw", "NSE_Broad_Factor_Indices_Historical_Data.xlsx")
OUT = os.path.join(REPO, "outputs")
SLUG = "lee_swaminathan_1998"

J_DAYS, K_TRANCHES, MIN_CELL = 126, 6, 15
SPREAD_BPS, BORROW_BPS, LAG_DAYS = 30.0, 100.0, 5
N_CONFIGS_TRIED = 48          # the card's own number (3 strategies x 16 J,K pairs)
HURDLE = 0.06                 # flat 6% proxy, the repo's convention for Sharpe

BENCHMARKS = {
    "NIFTY 500": ("Broad Market", "NIFTY 500 Close"),
    "NIFTY500 VALUE 50": ("Factor Indices", "NIFTY500 VALUE 50 Close"),
    "NIFTY500 MOMENTUM 50": ("Factor Indices", "NIFTY500 MOMENTUM 50 Close"),
}


def build_cells(adjp, daily_turn, inu, j_days):
    """The paper's independent sort. Deciles on the past j_days return, terciles on the past
    j_days average daily turnover, both ranked ONLY among eligible stocks that day. Returns
    boolean frames; no future data is read (every window ends on its own date)."""
    turn_j = daily_turn.rolling(j_days, min_periods=int(j_days * 0.8)).mean()
    ret_j = adjp / adjp.shift(j_days) - 1.0
    el = inu & ret_j.notna() & turn_j.notna()
    r_pct = ret_j.where(el).rank(axis=1, pct=True)
    t_pct = turn_j.where(el).rank(axis=1, pct=True)
    return {"el": el, "R10": r_pct > 0.9, "R1": r_pct <= 0.1, "V1": t_pct <= 1 / 3, "V3": t_pct > 2 / 3}


def indicator(long_mask, short_mask, el):
    """+1 long cell, -1 short cell, 0 neither, NaN not rankable."""
    ind = pd.DataFrame(0.0, index=el.index, columns=el.columns)
    ind = ind.mask(long_mask, 1.0).mask(short_mask, -1.0)
    return ind.where(el)


def run_book(prices, assets, member, ind, k, long_w, short_w, spread, borrow, name, min_cell=MIN_CELL):
    bt = Backtester(prices=prices, assets=assets, spread_bps=spread, lag_days=LAG_DAYS, allow_cash=True,
                    membership=member, allow_short=True, max_gross_exposure=1.0, short_borrow_bps=borrow)
    alloc = build_allocator("two_way_cell_tranches", assets, k_tranches=k, long_weight=long_w,
                            short_weight=short_w, min_cell=min_cell)
    return bt.run(allocator=alloc, rebalance="monthly", alpha=ind, name=name)


def stats(value, returns, label):
    c, v = _cagr(value), _ann_vol(returns)
    return {"name": label, "cagr": c, "vol": v, "sharpe_vs_6pct": (c - HURDLE) / v if v > 0 else float("nan"),
            "max_dd": _mdd(value), "n_obs": len(value),
            "start": str(value.index.min().date()), "end": str(value.index.max().date())}


def live_slice(value, start):
    v = value.loc[value.index >= start]
    r = v.pct_change(fill_method=None).fillna(0.0)
    if len(r):
        r.iloc[0] = 0.0
    return v, r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--panel", default=PANEL)
    ap.add_argument("--no-charts", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    res_json = {}

    print(f"Card: lee_swaminathan_1998_price_momentum_trading_volume  (AS DRAFTED, nothing changed)")
    p = pd.read_csv(a.panel, parse_dates=["date"])
    ever = sorted(p.loc[p["in_universe"] == 1, "security_id"].unique())
    p = p[p["security_id"].isin(ever)]
    adjp = p.pivot(index="date", columns="security_id", values="adj_close_now_basis")[ever]
    tv = p.pivot(index="date", columns="security_id", values="traded_value_cr")[ever]
    mc = p.pivot(index="date", columns="security_id", values="mcap_cr_est")[ever]
    inu = p.pivot(index="date", columns="security_id", values="in_universe")[ever].fillna(0).astype(bool)
    names = p.drop_duplicates("security_id").set_index("security_id")["symbol"].to_dict()
    daily_turn = tv / mc
    member = inu & adjp.notna()
    print(f"Panel: {len(ever)} entities ever in the top-1,000, {adjp.index.min().date()} -> {adjp.index.max().date()}, "
          f"{int(inu.sum(axis=1).mean())} names/day in universe")

    cells = build_cells(adjp, daily_turn, inu, J_DAYS)
    el = cells["el"]
    ind_main = indicator(cells["R10"] & cells["V1"], cells["R1"] & cells["V3"], el)
    ind_plain = indicator(cells["R10"], cells["R1"], el)
    ind_hv = indicator(cells["R10"] & cells["V3"], cells["R1"] & cells["V3"], el)
    ind_long = indicator(cells["R10"] & cells["V1"], cells["R1"] & False, el)

    print("\nLook-ahead tripwires (cell indicator vs return[t], return[t+1], after the engine's shift):")
    rets_check = adjp.pct_change(fill_method=None)
    for label, sig in (("main cell indicator", ind_main), ("plain momentum indicator", ind_plain)):
        sh = sig.shift(1 + LAG_DAYS)
        try:
            assert_causal(sh, rets_check, label=label)
            print(f"  PASS  {label}")
        except LookaheadError as e:
            print(f"  FAIL  {e}")
        cors = []
        for c in sh.columns:
            m = sh[c].notna() & rets_check[c].notna()
            if m.sum() >= 60 and sh[c][m].std() > 0 and rets_check[c][m].std() > 0:
                cors.append(abs(float(np.corrcoef(sh[c][m], rets_check[c][m])[0, 1])))
        if cors:
            cors = np.array(cors)
            print(f"        per-name |corr(indicator[t], return[t])|: {len(cors)} names, median {np.median(cors):.3f}, "
                  f"90th pct {np.quantile(cors, 0.9):.3f}, share above 0.35: {np.mean(cors > 0.35):.1%}")
            res_json["tripwire_" + label.replace(" ", "_")] = {"names": len(cors), "median_abs_corr": float(np.median(cors)),
                                                              "share_above_0.35": float(np.mean(cors > 0.35))}
    for label, planted in (("planted same-bar leak", rets_check), ("planted next-bar leak", rets_check.shift(-1))):
        try:
            assert_causal(planted, rets_check, label=label)
            print(f"  BROKEN  negative control '{label}' was NOT caught")
        except LookaheadError:
            print(f"  PASS  negative control '{label}' correctly caught")

    print("\nRunning the books (30bp round trip, 100bp borrow on short notional, K=6 overlapping tranches)...")
    r_main = run_book(adjp, ever, member, ind_main, K_TRANCHES, 0.5, 0.5, SPREAD_BPS, BORROW_BPS, "MAIN R10V1-R1V3")
    r_plain = run_book(adjp, ever, member, ind_plain, K_TRANCHES, 0.5, 0.5, SPREAD_BPS, BORROW_BPS, "plain momentum R10-R1")
    r_hv = run_book(adjp, ever, member, ind_hv, K_TRANCHES, 0.5, 0.5, SPREAD_BPS, BORROW_BPS, "high-volume momentum R10V3-R1V3")
    r_long = run_book(adjp, ever, member, ind_long, K_TRANCHES, 1.0, 0.0, SPREAD_BPS, 0.0, "long leg only R10V1")
    bt_ew = Backtester(prices=adjp, assets=ever, spread_bps=SPREAD_BPS, lag_days=LAG_DAYS, allow_cash=True, membership=member)
    r_ew = bt_ew.run(allocator=build_allocator("equal_weight", ever), rebalance="monthly", name="equal-weight eligible universe")

    diag = r_main.meta["allocator_diagnostics"]
    first_alpha = ind_main.shift(1 + LAG_DAYS).dropna(how="all").index.min()
    warm = [d for d in diag["skipped_dates"] if pd.Timestamp(d) < first_alpha]
    thin = [d for d in diag["skipped_dates"] if pd.Timestamp(d) >= first_alpha]
    wgross = r_main.weights.abs().sum(axis=1)
    if not (wgross > 1e-9).any():
        print("\nThe MAIN book never held a position: every month had a cell under 15 names.")
        json.dump(res_json, open(os.path.join(OUT, f"{SLUG}_results.json"), "w", encoding="utf-8"), indent=1, default=str)
        return
    start = wgross[wgross > 1e-9].index[0]
    print("\nMAIN book allocator diagnostics (the card's 15-name rule, applied literally):")
    print(f"  tranches formed: {diag['tranches_formed']}")
    print(f"  months skipped for warmup (no 126-day window yet): {len(warm)}")
    print(f"  months skipped because a needed cell had fewer than {MIN_CELL} names: {len(thin)}")
    print(f"  names in the long cell when formed: mean {diag['mean_long_names_formed']:.1f}, min {diag['min_long_names_formed']}")
    print(f"  names in the short cell when formed: mean {diag['mean_short_names_formed']:.1f}, min {diag['min_short_names_formed']}")
    print(f"  thin-cell skipped months: {thin}")
    print("  A skipped month carries the book forward unchanged, so old tranches do not expire while months are skipped.")
    res_json["main_diagnostics"] = {**{k: v for k, v in diag.items() if k != "skipped_dates"},
                                    "months_skipped_warmup": len(warm), "months_skipped_thin": len(thin),
                                    "thin_skipped_dates": thin}
    res_json["forced_exits"] = r_main.meta.get("forced_exits")
    print(f"\nFirst day the MAIN book holds a position (live start for every row below): {start.date()}")

    bench = {}
    for disp, (sheet, col) in BENCHMARKS.items():
        idx_df, _ = load_banner_workbook(INDEX_PATH, sheet=sheet)
        bench[disp] = idx_df[col].reindex(adjp.index).ffill()

    books = {"MAIN R10V1-R1V3 (long-short)": r_main, "plain momentum R10-R1": r_plain,
             "high-volume momentum R10V3-R1V3": r_hv, "long leg only R10V1": r_long,
             "equal-weight eligible universe": r_ew}
    live = {k: live_slice(v.value, start) for k, v in books.items()}
    rows = [stats(v, r, k) for k, (v, r) in live.items()]
    for disp, close in bench.items():
        bv, br = live_slice(close.dropna(), start)
        rows.append(stats(bv, br, disp))
    summary = pd.DataFrame(rows)
    headline = summary[summary["name"].isin(["MAIN R10V1-R1V3 (long-short)", "NIFTY 500"])]
    appendix = summary[~summary["name"].isin(["MAIN R10V1-R1V3 (long-short)", "NIFTY 500"])]
    print("\n" + "=" * 100)
    print(f"RESULTS, {start.date()} -> {live['MAIN R10V1-R1V3 (long-short)'][0].index.max().date()}  "
          "(costs and borrow are inside the strategy)")
    print("=" * 100)
    pd.set_option("display.width", 200)
    print(headline.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    headline.to_csv(os.path.join(OUT, f"{SLUG}_comparison.csv"), index=False)
    appendix.to_csv(os.path.join(OUT, f"{SLUG}_comparators_appendix.csv"), index=False)
    print("\nAPPENDIX, comparators used only for the card's must-beat tests (not part of the headline):")
    print(appendix.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    res_json["comparison"] = headline.to_dict("records")
    res_json["comparators_appendix"] = appendix.to_dict("records")

    v_main, ret_main = live["MAIN R10V1-R1V3 (long-short)"]
    _, ret_plain = live["plain momentum R10-R1"]
    _, ret_ew = live["equal-weight eligible universe"]

    print("\nHOLDINGS / EXPOSURE of the MAIN book")
    w = r_main.weights.loc[v_main.index]
    gross, net = w.abs().sum(axis=1), w.sum(axis=1)
    longn, shortn = (w > 1e-12).sum(axis=1), (w < -1e-12).sum(axis=1)
    print(f"  days with any position: {(gross > 1e-9).sum()} of {len(w)}; mean gross {gross.mean():.2f}, mean net {net.mean():.2f}")
    print(f"  names long / short (mean): {longn.mean():.0f} / {shortn.mean():.0f}")
    print(f"  turnover (mean daily, one-way): {r_main.turnover.loc[v_main.index].mean():.4f}; "
          f"total costs paid: {r_main.costs.loc[v_main.index].sum():.3%} of NAV")
    holdings_path = os.path.join(OUT, f"{SLUG}_holdings_main.csv")
    write_holdings_log(holdings_path, r_main, name_lookup=names, start=start, end=v_main.index.max())
    print(f"  holdings log: {holdings_path}")

    print("\nFULL TEARSHEET, MAIN book vs NIFTY 500")
    class _W:
        pass
    wr = _W()
    wr.value, wr.returns = v_main, ret_main
    print(render_tearsheet(compute_tearsheet(wr, bench["NIFTY 500"].reindex(v_main.index))))

    print("\nVALIDATION (code computes; nothing below is estimated by hand)")
    boot = bootstrap_sharpe_ci(ret_main, block_size=K_TRANCHES * 21, n_resamples=1000, seed=0)
    print(f"  MAIN Sharpe, 90% block-bootstrap CI (block {K_TRANCHES * 21} days = K months): "
          f"[{boot.ci_low:.2f}, {boot.ci_high:.2f}]  point {boot.point_estimate:.2f}, {boot.fraction_positive:.0%} of resamples positive")
    diff = (ret_main - ret_plain).fillna(0.0)
    bd = bootstrap_sharpe_ci(diff, block_size=K_TRANCHES * 21, n_resamples=1000, seed=0)
    print(f"  PAIRED, MAIN minus plain momentum (daily return difference), 90% CI on its Sharpe: "
          f"[{bd.ci_low:.2f}, {bd.ci_high:.2f}]  point {bd.point_estimate:.2f}, {bd.fraction_positive:.0%} positive")
    be = bootstrap_sharpe_ci((ret_main - ret_ew).fillna(0.0), block_size=K_TRANCHES * 21, n_resamples=1000, seed=0)
    print(f"  PAIRED, MAIN minus equal-weight universe, 90% CI on its Sharpe: "
          f"[{be.ci_low:.2f}, {be.ci_high:.2f}]  point {be.point_estimate:.2f}, {be.fraction_positive:.0%} positive")
    print("  COMPARATORS, 90% block-bootstrap CI on each book's own Sharpe (zero hurdle), and HV minus plain:")
    comp_ci = {}
    for label, (_, rr) in live.items():
        b = bootstrap_sharpe_ci(rr, block_size=K_TRANCHES * 21, n_resamples=1000, seed=0)
        comp_ci[label] = {"ci_low": b.ci_low, "ci_high": b.ci_high, "point": b.point_estimate, "frac_positive": b.fraction_positive}
        print(f"    {label}: [{b.ci_low:.2f}, {b.ci_high:.2f}] point {b.point_estimate:.2f}, {b.fraction_positive:.0%} positive")
    hv_minus_plain = bootstrap_sharpe_ci((live["high-volume momentum R10V3-R1V3"][1] - ret_plain).fillna(0.0),
                                         block_size=K_TRANCHES * 21, n_resamples=1000, seed=0)
    print(f"    PAIRED, high-volume momentum minus plain momentum: [{hv_minus_plain.ci_low:.2f}, {hv_minus_plain.ci_high:.2f}] "
          f"point {hv_minus_plain.point_estimate:.2f}, {hv_minus_plain.fraction_positive:.0%} positive")
    res_json["comparator_bootstrap"] = comp_ci
    res_json["paired_hv_vs_plain"] = {"ci_low": hv_minus_plain.ci_low, "ci_high": hv_minus_plain.ci_high,
                                      "point": hv_minus_plain.point_estimate}
    dsr = deflated_sharpe_from_returns(ret_main, n_trials=N_CONFIGS_TRIED, trial_sharpe_std=0.3)
    print(f"  Deflated Sharpe (n_trials={N_CONFIGS_TRIED}, the card's own count): {dsr:.2f}")
    res_json["bootstrap_main"] = {"ci_low": boot.ci_low, "ci_high": boot.ci_high, "point": boot.point_estimate}
    res_json["paired_vs_plain"] = {"ci_low": bd.ci_low, "ci_high": bd.ci_high, "point": bd.point_estimate}
    res_json["paired_vs_equal_weight"] = {"ci_low": be.ci_low, "ci_high": be.ci_high, "point": be.point_estimate}
    res_json["deflated_sharpe"] = float(dsr)

    print("\n  OUT-OF-SAMPLE STABILITY (anchored walk-forward):")
    windows = walk_forward_windows(v_main.index, n_folds=4, min_train_years=1.0)
    oos = oos_stability_summary(v_main, ret_main, windows, min_obs=60)
    print(oos.to_string(index=False) if not oos.empty else "    not enough history for walk-forward folds")
    oos.to_csv(os.path.join(OUT, f"{SLUG}_oos_stability.csv"), index=False)

    def rerun_jk(jk):
        jd = int(jk * 21)
        c = build_cells(adjp, daily_turn, inu, jd)
        ind = indicator(c["R10"] & c["V1"], c["R1"] & c["V3"], c["el"])
        r = run_book(adjp, ever, member, ind, int(jk), 0.5, 0.5, SPREAD_BPS, BORROW_BPS, f"JK={jk}")
        if not len(r.rebalances):
            return pd.Series([1.0, 1.0], index=adjp.index[:2]), pd.Series([0.0, 0.0], index=adjp.index[:2])
        return live_slice(r.value, start)
    print("\n  PARAMETER SENSITIVITY (J = K months, base case 6):")
    sweep = parameter_sensitivity_sweep(rerun_jk, "J_equals_K_months", [3, 6, 12])
    print(sweep.to_string(index=False))
    print("  " + sensitivity_verdict(sweep, 6, "J_equals_K_months"))
    sweep.to_csv(os.path.join(OUT, f"{SLUG}_sensitivity_jk.csv"), index=False)

    print("\n  COST AND BORROW SWEEPS (MAIN book):")
    rows = []
    for sp, bb in ((30, 100), (60, 100), (90, 100), (30, 0), (30, 50), (30, 200), (30, 400)):
        r = run_book(adjp, ever, member, ind_main, K_TRANCHES, 0.5, 0.5, sp, bb, f"sp{sp}_b{bb}")
        v, rr = live_slice(r.value, start)
        s = stats(v, rr, f"spread {sp}bp, borrow {bb}bp")
        rows.append({"spread_bps": sp, "borrow_bps": bb, "cagr": s["cagr"], "vol": s["vol"],
                     "sharpe_vs_6pct": s["sharpe_vs_6pct"], "max_dd": s["max_dd"]})
    sw = pd.DataFrame(rows)
    print(sw.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    sw.to_csv(os.path.join(OUT, f"{SLUG}_cost_borrow_sweep.csv"), index=False)
    res_json["cost_borrow_sweep"] = sw.to_dict("records")

    print("\n  FACTOR FINGERPRINT, MAIN book vs NIFTY500 VALUE 50 and MOMENTUM 50 (held, backfilled sleeves):")
    fr = pd.DataFrame({n: bench[n].reindex(v_main.index).pct_change(fill_method=None).fillna(0.0)
                       for n in ("NIFTY500 VALUE 50", "NIFTY500 MOMENTUM 50")})
    fp = factor_fingerprint(ret_main, fr, rf_daily=None)
    if "error" in fp:
        print(f"    unavailable: {fp['error']}")
    else:
        print(f"    alpha (ann.) {fp['alpha_ann']:.2%}   alpha t (HAC) {fp['alpha_t_hac']:.2f}   R^2 {fp['r_squared']:.2f}   n {fp['n_obs']}")
        print(f"    loadings: {fp['loadings']}")
        print(f"    {fp['interpretation']}")
        res_json["factor_fingerprint"] = {k: fp[k] for k in ("alpha_ann", "alpha_t_hac", "r_squared", "n_obs", "loadings") if k in fp}

    print("\n  SUB-CUT: NIFTY 500-style cut (hold only cell members in the top 500 by traded value that day)")
    top500 = tv.rank(axis=1, ascending=False) <= 500
    ind_cut = ind_main.where(top500 | ind_main.isna(), 0.0)
    r_cut = run_book(adjp, ever, member, ind_cut, K_TRANCHES, 0.5, 0.5, SPREAD_BPS, BORROW_BPS, "main top-500 cut", min_cell=1)
    if len(r_cut.rebalances):
        vc, rc = live_slice(r_cut.value, max(start, r_cut.rebalances[0]))
        print("   " + "  ".join(f"{k} {v:.3f}" if isinstance(v, float) else f"{k} {v}" for k, v in stats(vc, rc, "top-500 cut").items() if k != "name"))
        res_json["top500_cut"] = stats(vc, rc, "top-500 cut")
    print(f"   cell sizes in that cut (min_cell=1): mean long {np.mean(r_cut.meta['allocator_diagnostics']['mean_long_names_formed']):.1f}, "
          f"mean short {np.mean(r_cut.meta['allocator_diagnostics']['mean_short_names_formed']):.1f}  (reported, not a pass-or-fail test)")

    if not a.no_charts:
        try:
            from universal_backtester.clean_charts import save_clean_charts
            charts = save_clean_charts(
                v_main, live_slice(bench["NIFTY 500"].dropna(), start)[0], outdir=os.path.join(OUT, "charts"), tag=SLUG,
                strategy_name="R10V1 - R1V3 (long-short)", benchmark_name="NIFTY 500",
                weights=r_main.weights.loc[v_main.index],
                sleeve=live["high-volume momentum R10V3-R1V3"][0], sleeve_name="High-volume momentum R10V3 - R1V3",
                footnote="NIFTY 500 is price-return. The index data ends 2026-09-18; later days are carried forward.")
            print()
            print("  charts (strategy vs NIFTY 500 only, one comparator on its own chart):")
            for c in charts:
                print(f"    {c}")
        except Exception as e:  # charts are a convenience; never fail the run on them
            print()
            print(f"  charts skipped: {e!r}")

    # ---- GATE B inputs, computed here, judged by the repo's own gate_b() ------------------
    from ros.cards.schema import load_card
    from ros.governance.gates import gate_b
    nret = live_slice(bench["NIFTY 500"].dropna(), start)[1].reindex(ret_main.index).fillna(0.0)
    bn = bootstrap_sharpe_ci((ret_main - nret).fillna(0.0), block_size=K_TRANCHES * 21, n_resamples=1000, seed=0)
    ann_to = float(r_main.turnover.loc[v_main.index].mean() * 252 * 2)
    research = {"deflated_sharpe": {"deflated_sharpe_prob": float(dsr),
                                    "interpretation": f"n_trials={N_CONFIGS_TRIED} (the card's own count), trial Sharpe std 0.3"},
                "oos_min_sharpe": float(oos["sharpe"].min()) if not oos.empty else None,
                "bootstrap_p_not_positive": float(1.0 - bn.fraction_positive)}
    portfolio = {"alpha_t_hac": (float(fp["alpha_t_hac"]) if "error" not in fp else None),
                 "annual_turnover": ann_to}
    gb = gate_b(load_card(os.path.join(REPO, "cards", "lee_swaminathan_1998_price_momentum_trading_volume.yaml")),
                research, portfolio)
    print("\n" + "=" * 100)
    print("GATE B CRITERIA, as the repo's own gate_b() computes them from this run (decision stays PENDING)")
    print("  paired test used for 'advantage over benchmark': MAIN minus NIFTY 500 (price-return), "
          f"P(Sharpe difference <= 0) = {1.0 - bn.fraction_positive:.3f}; two-way annual turnover {ann_to:.0%}")
    print("=" * 100)
    print(gb.render())
    res_json["gate_b"] = gb.to_dict()
    res_json["gate_b_inputs"] = {"research": research, "portfolio": portfolio}
    pd.DataFrame({**{k: r for k, (_, r) in live.items()}, **{"NIFTY 500": nret}}).to_csv(
        os.path.join(OUT, f"{SLUG}_daily_returns.csv"))

    out_json = os.path.join(OUT, f"{SLUG}_results.json")
    json.dump(res_json, open(out_json, "w", encoding="utf-8"), indent=1, default=str)
    print(f"\nResults written to {OUT} ({SLUG}_*). Gate B is a human decision and is NOT assigned by this script.")


if __name__ == "__main__":
    main()
