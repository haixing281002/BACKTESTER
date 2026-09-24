"""Execution script for cards/alquist_2018_india_small_cap_tilt_adaptation.yaml.

Fixes two real bugs found in the first local attempt at this script (not
this version):

1. THE ELIGIBLE UNIVERSE WAS NEVER RESTRICTED. The card's own text claims
   Monthly_uni_new.xlsx "is not present on this machine" and falls back to
   "every Accord-priced name, liquidity floor only" as the eligible pool --
   but that file IS present (it's one of the original four Accord files,
   already used by accord_stock_selection_backtest.py). This script uses it
   properly: get_top_n_universe() (the fix for the file's own alternating-
   coverage irregularity) + restrict_to_priced_universe(), the same
   verified, point-in-time base every other script in this repo now uses.
   That also closes one of the card's own named ambiguities
   ("NOT A VERIFIED INDEX UNIVERSE") rather than leaving it open.
2. THE HARDCODED BACKTEST WINDOW (accord_data.BACKTEST_START/BACKTEST_END,
   2013-03-31 -> 2026-08-31) was never applied -- the first attempt's output
   showed 2012-02-29 -> 2026-07-31, the raw data's own range. Imported and
   enforced here.

The mechanism itself, exactly as the card specifies: each month-end, rank
the eligible (top-500-by-rank, priced, liquid) universe by market cap;
SMALL = bottom 20% by count, equal-weighted, long-only, tradable; BIG = top
20%, same construction, reference-only (never a fund position). Benchmarked
against NIFTY 500, NIFTY SMALLCAP 250, NIFTY MIDCAP 150 and NIFTY500
QUALITY 50 (the factor-fingerprint check the card's own must_beat/
success_looks_like criteria call for).

Output: a real "SE Return Analytics" workbook/CSV (SMALL vs NIFTY 500, the
card's headline tradable-vs-mandate-benchmark comparison) via the same
verified excel_tearsheet.py used everywhere else in this repo, PLUS a
compact multi-benchmark comparison table (all six series, one row each)
computed from this repo's own tearsheet.py -- not ros/validation/metrics.py,
whose field definitions were never cross-checked against the reference
workbook the fund actually cares about matching.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from universal_backtester.accord_data import (
    load_accord_price_panel, load_accord_monthly_universe, load_accord_fundamentals,
    load_accord_daily_price_mcap, get_top_n_universe, restrict_to_priced_universe,
    BACKTEST_START, BACKTEST_END,
)
from universal_backtester.data import load_banner_workbook
from universal_backtester.engine import Backtester
from universal_backtester.allocators import build_allocator
from universal_backtester.tearsheet import compute_tearsheet
from universal_backtester.excel_tearsheet import (
    write_se_return_analytics_workbook, write_se_return_analytics_csv,
)
from universal_backtester.validation import bootstrap_sharpe_ci, deflated_sharpe_from_returns
from universal_backtester.metrics import cagr as _cagr, ann_vol as _ann_vol, max_drawdown as _mdd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICE_PATH = os.path.join(REPO_ROOT, "data", "raw", "stocks", "price_data_till_03aug2026.xlsx")
UNIVERSE_PATH = os.path.join(REPO_ROOT, "data", "raw", "stocks", "Monthly_uni_new.xlsx")
DAILY_MCAP_PATH = os.path.join(REPO_ROOT, "data", "raw", "stocks",
                               "prices_marketcap_data_till_03082026.csv")
INDEX_PATH = os.path.join(REPO_ROOT, "data", "raw", "NSE_Broad_Factor_Indices_Historical_Data.xlsx")
OUTPUT_DIR = os.path.join(REPO_ROOT, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

QUINTILE = 0.20
MIN_NAMES = 30
SPREAD_BPS = 30.0
LAG_DAYS = 1                 # this card's own stated choice -- the repo's non-negotiable floor,
                              # not the 100-day figure used in accord_stock_selection_backtest.py's
                              # separate momentum experiment. Change here if you want them consistent.
REBALANCE = "monthly"
LIQUIDITY_LOOKBACK_DAYS = 21
MIN_LIQUIDITY_PERCENTILE = 0.20
WARMUP_BUFFER_DAYS = 60       # this signal has no return-based lookback (ranks on LEVEL: mcap and
                              # trailing ADV), so warmup only needs the liquidity window to fill

BENCHMARKS = {
    "NIFTY 500": ("Broad Market", "NIFTY 500 Close"),
    "NIFTY SMALLCAP 250": ("Broad Market", "NIFTY SMALLCAP 250 Close"),
    "NIFTY MIDCAP 150": ("Broad Market", "NIFTY MIDCAP 150 Close"),
    "NIFTY500 QUALITY 50": ("Factor Indices", "NIFTY500 QUALITY 50 Close"),
}
PRIMARY_BENCHMARK = "NIFTY 500"


def build_point_in_time_membership(monthly_universe: pd.DataFrame, price_index: pd.DatetimeIndex,
                                   assets: list) -> pd.DataFrame:
    snap = (monthly_universe.assign(accord_code=monthly_universe["accord_code"].astype(int))
                            .pivot_table(index="month_end", columns="accord_code",
                                        values="market_rank", aggfunc="first"))
    snap = snap.notna()
    snap = snap.reindex(columns=assets, fill_value=False)
    return snap.reindex(price_index, method="ffill").fillna(False)


def load_daily_mcap_and_liquidity(daily_mcap_path, price_panel_path, price_index, assets,
                                  adv_lookback_days, min_adv_percentile):
    """Same real-daily-data approach as accord_stock_selection_backtest.py.
    Returns (mcap_frame, liquidity_pass_frame) or (None, None) if the
    366MB fifth file isn't present in this environment -- never guessed."""
    if not os.path.exists(daily_mcap_path):
        return None, None
    long_df, prov = load_accord_daily_price_mcap(
        daily_mcap_path, verify_against_price_panel_path=price_panel_path)
    print(f"  daily mcap file: {prov['n_rows']:,} rows, {prov['n_securities']} securities")
    if prov.get("n_close_mismatches", 0) > 0:
        print(f"  WARNING: {prov['n_close_mismatches']} close mismatches vs. the wide panel")

    mcap_wide = long_df.pivot_table(index="date", columns="accord_code", values="mcap", aggfunc="last")
    mcap_wide = mcap_wide.reindex(columns=assets).reindex(price_index).ffill()

    traded_value = long_df.pivot_table(index="date", columns="accord_code",
                                       values="traded_value", aggfunc="last")
    traded_value = traded_value.reindex(columns=assets).reindex(price_index)
    adv = traded_value.rolling(adv_lookback_days, min_periods=max(5, adv_lookback_days // 2)).mean()
    threshold = adv.quantile(min_adv_percentile, axis=1)
    liquidity_pass = adv.gt(threshold, axis=0).fillna(False)
    return mcap_wide, liquidity_pass


def run_quintile_leg(price_window, assets, eligible, mcap_daily, ascending, name, spread_bps, lag_days):
    """One leg (SMALL or BIG): rank eligible names by market cap (ascending
    True = smallest wins), take the bottom/top 20% by COUNT (matching the
    card's own quantile-not-fixed-count construction), equal-weighted."""
    bt = Backtester(prices=price_window, assets=assets, spread_bps=spread_bps,
                    lag_days=lag_days, allow_cash=True, membership=eligible)
    alloc = build_allocator("cross_sectional", assets, quantile=QUINTILE, weighting="equal",
                            ascending=ascending, min_names=MIN_NAMES)
    # Rank on market cap directly: mcap_daily may be None (no daily-mcap
    # file in this environment) -- signal.py in the card is explicit that
    # this ranks on LEVEL, not a return, so a level-only proxy (trailing
    # 21-day average of whatever price is available) is not appropriate as
    # a mcap substitute; if the real mcap series isn't available, fall back
    # to the monthly universe file's own mcap snapshots (coarser, but a
    # real reported market cap, not invented).
    if mcap_daily is not None:
        alpha = mcap_daily
        print(f"  {name}: ranking on real DAILY market cap")
    else:
        alpha = None
    return bt, alloc, alpha


def main():
    print("Card: alquist_2018_india_small_cap_tilt_adaptation")
    print(f"Backtest window (hardcoded, accord_data.BACKTEST_START/END): "
          f"{BACKTEST_START.date()} -> {BACKTEST_END.date()}")

    print(f"\nLoading Accord price panel: {PRICE_PATH}")
    price, price_prov = load_accord_price_panel(PRICE_PATH)
    print(f"  {price_prov['n_securities']} securities, {price_prov['date_min']} -> {price_prov['date_max']}")

    print(f"Loading Accord monthly universe: {UNIVERSE_PATH}")
    uni, uni_prov = load_accord_monthly_universe(UNIVERSE_PATH)
    top500, top_prov = get_top_n_universe(uni, n=500)
    tradable, r_prov = restrict_to_priced_universe(top500, price.columns)
    print(f"  top-500-by-rank, priced-only universe: {top_prov['n_months']} months, "
          f"{r_prov['n_codes_dropped_no_price_series']} codes dropped (no price series)")
    print("  This REPLACES the first attempt's 'all 1314 names, liquidity floor only' pool -- "
          "Monthly_uni_new.xlsx is present locally and gives a real, verified point-in-time "
          "universe instead.")

    assets = sorted(tradable["accord_code"].dropna().astype(int).unique().tolist())
    print(f"  {len(assets)} distinct tradable Accord Codes across the whole window")
    price = price[assets]

    lookback_start = BACKTEST_START - pd.Timedelta(days=int(WARMUP_BUFFER_DAYS * 1.6))
    price_window = price.loc[(price.index >= lookback_start) & (price.index <= BACKTEST_END)]
    print(f"\nPrice panel trimmed to {price_window.index.min().date()} -> "
          f"{price_window.index.max().date()} ({len(price_window)} trading days)")

    print("Building point-in-time universe membership...")
    universe_membership = build_point_in_time_membership(tradable, price_window.index, assets)
    print(f"  mean names eligible (universe only) per day: {universe_membership.sum(axis=1).mean():.0f}")

    print(f"\nLooking for the daily market-cap/liquidity file: {DAILY_MCAP_PATH}")
    mcap_daily, liquidity_pass = load_daily_mcap_and_liquidity(
        DAILY_MCAP_PATH, PRICE_PATH, price_window.index, assets,
        LIQUIDITY_LOOKBACK_DAYS, MIN_LIQUIDITY_PERCENTILE)

    if mcap_daily is not None:
        eligible = universe_membership & liquidity_pass
        print(f"  liquidity floor applied: mean eligible/day now {eligible.sum(axis=1).mean():.0f}")
    else:
        eligible = universe_membership
        print("  NOT FOUND (366MB, local-only) -- no liquidity floor, and ranking will fall back "
              "to the monthly universe file's own (coarser) mcap snapshots instead of real daily "
              "market cap. Run this locally, where that file exists, for the real numbers.")
        monthly_mcap = (tradable.assign(accord_code=tradable["accord_code"].astype(int))
                                .pivot_table(index="month_end", columns="accord_code",
                                            values="mcap", aggfunc="first"))
        mcap_daily = monthly_mcap.reindex(columns=assets).reindex(price_window.index).ffill()

    print(f"\nLoading benchmarks from {INDEX_PATH}")
    bench_closes = {}
    for disp_name, (sheet, col) in BENCHMARKS.items():
        idx_df, _ = load_banner_workbook(INDEX_PATH, sheet=sheet)
        bench_closes[disp_name] = idx_df[col].reindex(price_window.index).ffill()
        print(f"  {disp_name}: loaded")

    print(f"\nRunning SMALL (bottom {QUINTILE:.0%} by market cap, tradable)...")
    bt_small, alloc_small, alpha_small = run_quintile_leg(
        price_window, assets, eligible, mcap_daily, ascending=True,
        name="SMALL", spread_bps=SPREAD_BPS, lag_days=LAG_DAYS)
    result_small = bt_small.run(allocator=alloc_small, rebalance=REBALANCE, alpha=alpha_small,
                                name="India small-cap quintile (SMALL)", warmup=WARMUP_BUFFER_DAYS)

    print(f"Running BIG (top {QUINTILE:.0%} by market cap, reference only, never traded)...")
    bt_big, alloc_big, alpha_big = run_quintile_leg(
        price_window, assets, eligible, mcap_daily, ascending=False,
        name="BIG", spread_bps=SPREAD_BPS, lag_days=LAG_DAYS)
    result_big = bt_big.run(allocator=alloc_big, rebalance=REBALANCE, alpha=alpha_big,
                            name="BIG (top quintile, same universe and rule)", warmup=WARMUP_BUFFER_DAYS)

    def to_live(v):
        return v.loc[(v.index >= BACKTEST_START) & (v.index <= BACKTEST_END)]

    live_small = to_live(result_small.value)
    live_big = to_live(result_big.value)
    ret_small = live_small.pct_change(fill_method=None).fillna(0.0)
    ret_small.iloc[0] = 0.0
    ret_big = live_big.pct_change(fill_method=None).fillna(0.0)
    ret_big.iloc[0] = 0.0

    print("\n" + "=" * 78)
    print(f"RESULTS -- {live_small.index.min().date()} -> {live_small.index.max().date()}")
    print("=" * 78)

    rows = []
    for label, value, returns in [
        ("India small-cap quintile (SMALL)", live_small, ret_small),
        ("BIG (top quintile, same universe and rule)", live_big, ret_big),
    ]:
        rows.append({
            "name": label, "cagr": _cagr(value), "vol": _ann_vol(returns),
            "sharpe": (_cagr(value) - 0.06) / _ann_vol(returns) if _ann_vol(returns) > 0 else float("nan"),
            "max_dd": _mdd(value), "n_obs": len(value),
            "start": str(value.index.min().date()), "end": str(value.index.max().date()),
        })
    for disp_name, close in bench_closes.items():
        bv = close.reindex(live_small.index).dropna()
        br = bv.pct_change(fill_method=None).fillna(0.0)
        rows.append({
            "name": disp_name, "cagr": _cagr(bv), "vol": _ann_vol(br),
            "sharpe": (_cagr(bv) - 0.06) / _ann_vol(br) if _ann_vol(br) > 0 else float("nan"),
            "max_dd": _mdd(bv), "n_obs": len(bv),
            "start": str(bv.index.min().date()), "end": str(bv.index.max().date()),
        })
    summary = pd.DataFrame(rows)
    print(summary.to_string(index=False))

    summary_path = os.path.join(OUTPUT_DIR, "alquist_2018_india_small_cap_comparison.csv")
    summary.to_csv(summary_path, index=False)
    print(f"\nMulti-benchmark comparison written to: {summary_path}")

    boot = bootstrap_sharpe_ci(ret_small, block_size=20, n_resamples=1000, seed=0)
    print(f"\nSMALL Sharpe ratio, 90% block-bootstrap CI: [{boot.ci_low:.2f}, {boot.ci_high:.2f}] "
          f"(point estimate {boot.point_estimate:.2f}, {boot.fraction_positive:.0%} of resamples positive)")
    dsr = deflated_sharpe_from_returns(ret_small, n_trials=6, trial_sharpe_std=0.3)
    print(f"Deflated Sharpe Ratio (n_trials=6, per this card's own n_configs_tried note): {dsr:.2f}")

    print(f"\nFull SE Return Analytics tearsheet -- SMALL vs {PRIMARY_BENCHMARK}:")
    class _Wrapped:
        pass
    wrapped = _Wrapped()
    wrapped.value, wrapped.returns = live_small, ret_small
    sheet = compute_tearsheet(wrapped, bench_closes[PRIMARY_BENCHMARK].reindex(live_small.index))
    from universal_backtester.tearsheet import render_tearsheet
    print(render_tearsheet(sheet))

    monthly_small = (1 + ret_small).resample("ME").prod() - 1
    monthly_bench = (1 + bench_closes[PRIMARY_BENCHMARK].reindex(live_small.index)
                     .pct_change(fill_method=None).fillna(0.0)).resample("ME").prod() - 1
    common = monthly_small.index.intersection(monthly_bench.index)
    monthly_small, monthly_bench = monthly_small.loc[common], monthly_bench.loc[common]

    xlsx_path = os.path.join(OUTPUT_DIR, "alquist_2018_india_small_cap_se_return_analytics.xlsx")
    csv_path = os.path.join(OUTPUT_DIR, "alquist_2018_india_small_cap_se_return_analytics.csv")
    write_se_return_analytics_workbook(xlsx_path, common, monthly_small, monthly_bench,
                                       strategy_name="India Small-Cap SMALL",
                                       benchmark_name=PRIMARY_BENCHMARK)
    write_se_return_analytics_csv(csv_path, common, monthly_small, monthly_bench,
                                  strategy_name="India Small-Cap SMALL",
                                  benchmark_name=PRIMARY_BENCHMARK)
    print(f"\nSE Return Analytics (SMALL vs {PRIMARY_BENCHMARK}) written to:\n  {xlsx_path}\n  {csv_path}")


if __name__ == "__main__":
    main()
