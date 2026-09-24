"""Individual-stock selection backtest on the Accord Fintech dataset.

THIS is the script that answers the fund's instruction: pick the AI's own
universe of individual stocks (NOT an index), rank and select from them,
and benchmark the result against the fund's existing index sleeves.

Mechanism (the model's own choice, executed entirely by deterministic
code -- no number below is estimated in conversation):
  - Universe: the Accord monthly universe file, filtered to the top 500
    names by market rank EVERY month (get_top_n_universe -- this is the
    fix for the file's own alternating-coverage irregularity, see
    data/raw/stocks/README.md), further restricted to the ~1314 names
    that actually have a price series (restrict_to_priced_universe) --
    i.e. a real, point-in-time, priceable NIFTY-500-sized universe.
  - Signal: 12-month price momentum, skipping the most recent month (the
    standard 12-1 momentum convention -- avoids the well-documented
    short-term reversal effect in the skipped month).
  - Selection: top 40 names by that signal each month, equal-weighted,
    monthly rebalance. 40 is a starting point, not a magic number --
    change N_HOLD below to re-run with a different count.
  - Benchmark: NIFTY 500 (price-return proxy) from the fund's existing
    index workbook -- a comparison point, never traded.

Backtest window is HARDCODED (fund decision, 2026-09-24):
  BACKTEST_START .. BACKTEST_END, imported from accord_data.py, not a
  script argument -- every run of this script covers the same window.

India non-negotiables applied: lag_days >= 1, 30bp round-trip cost floor.
Point-in-time discipline: membership is a changing cross-section (names
enter/exit the top-500 each month); a name that falls out is SOLD at
cost on the day it's learned, never quietly dropped (see Backtester's
own membership= mechanism / engine.py's module docstring).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from universal_backtester.accord_data import (
    load_accord_price_panel, load_accord_monthly_universe,
    get_top_n_universe, restrict_to_priced_universe,
    BACKTEST_START, BACKTEST_END,
)
from universal_backtester.data import load_banner_workbook
from universal_backtester.engine import Backtester
from universal_backtester.allocators import build_allocator
from universal_backtester.tearsheet import compute_tearsheet, render_tearsheet
from universal_backtester.excel_tearsheet import (
    write_se_return_analytics_workbook, write_se_return_analytics_csv,
)
from universal_backtester.validation import bootstrap_sharpe_ci, deflated_sharpe_from_returns

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICE_PATH = os.path.join(REPO_ROOT, "data", "raw", "stocks", "price_data_till_03aug2026.xlsx")
UNIVERSE_PATH = os.path.join(REPO_ROOT, "data", "raw", "stocks", "Monthly_uni_new.xlsx")
INDEX_PATH = os.path.join(REPO_ROOT, "data", "raw", "NSE_Broad_Factor_Indices_Historical_Data.xlsx")
OUTPUT_DIR = os.path.join(REPO_ROOT, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

N_HOLD = 40                 # names held, equal-weighted -- change and re-run to test another count
MOM_LOOKBACK_DAYS = 252     # ~12 months of trading days
MOM_SKIP_DAYS = 21          # ~1 month, skipped (12-1 momentum, avoids short-term reversal)
SPREAD_BPS = 30.0           # this repo's non-negotiable factor-sleeve cost floor
LAG_DAYS = 1                # this repo's non-negotiable minimum
REBALANCE = "monthly"
BENCHMARK_COL = "NIFTY 500 Close"
BENCHMARK_DISPLAY_NAME = "NIFTY 500"
WARMUP_BUFFER_DAYS = 400    # trading days of history BEFORE BACKTEST_START, for the momentum lookback


def build_point_in_time_membership(monthly_universe: pd.DataFrame, price_index: pd.DatetimeIndex,
                                   assets: list) -> pd.DataFrame:
    """Daily boolean membership frame: True on every day between one
    month-end snapshot and the next if that Accord Code was in that
    month's (top-500, priced) universe. Forward-filled -- a name's
    membership from the 31-Jan snapshot governs until the 28-Feb snapshot
    replaces it, which is what "point-in-time as of the last known
    snapshot" means for a monthly-frequency universe file."""
    snap = (monthly_universe.assign(accord_code=monthly_universe["accord_code"].astype(int))
                            .pivot_table(index="month_end", columns="accord_code",
                                        values="market_rank", aggfunc="first"))
    snap = snap.notna()
    snap = snap.reindex(columns=assets, fill_value=False)
    daily = snap.reindex(price_index, method="ffill").fillna(False)
    return daily


def momentum_signal(prices: pd.DataFrame, lookback: int, skip: int) -> pd.DataFrame:
    """12-1 momentum: (price[t-skip] / price[t-lookback]) - 1."""
    return prices.shift(skip) / prices.shift(lookback) - 1.0


def main():
    print(f"Backtest window (hardcoded): {BACKTEST_START.date()} -> {BACKTEST_END.date()}")

    print(f"\nLoading Accord price panel: {PRICE_PATH}")
    price, price_prov = load_accord_price_panel(PRICE_PATH)
    print(f"  {price_prov['n_securities']} securities, "
          f"{price_prov['date_min']} -> {price_prov['date_max']}")

    print(f"Loading Accord monthly universe: {UNIVERSE_PATH}")
    uni, uni_prov = load_accord_monthly_universe(UNIVERSE_PATH)
    top500, top_prov = get_top_n_universe(uni, n=500)
    tradable, r_prov = restrict_to_priced_universe(top500, price.columns)
    print(f"  top-500-by-rank, priced-only universe: {top_prov['n_months']} months, "
          f"{r_prov['n_codes_dropped_no_price_series']} codes dropped (no price series)")

    assets = sorted(tradable["accord_code"].dropna().astype(int).unique().tolist())
    print(f"  {len(assets)} distinct tradable Accord Codes across the whole window")

    price = price[assets]

    lookback_start = BACKTEST_START - pd.Timedelta(days=int(WARMUP_BUFFER_DAYS * 1.6))
    price_window = price.loc[(price.index >= lookback_start) & (price.index <= BACKTEST_END)]
    print(f"\nPrice panel trimmed to {price_window.index.min().date()} -> "
          f"{price_window.index.max().date()} ({len(price_window)} trading days, "
          f"incl. warmup before {BACKTEST_START.date()})")

    print("Building point-in-time membership (daily, forward-filled from monthly snapshots)...")
    membership = build_point_in_time_membership(tradable, price_window.index, assets)
    print(f"  mean names eligible per day: {membership.sum(axis=1).mean():.0f}")

    print(f"Building 12-1 momentum signal ({MOM_LOOKBACK_DAYS}d lookback, "
          f"{MOM_SKIP_DAYS}d skip)...")
    alpha = momentum_signal(price_window, MOM_LOOKBACK_DAYS, MOM_SKIP_DAYS)

    print(f"\nLoading benchmark: {BENCHMARK_COL} from {INDEX_PATH}")
    idx_df, _ = load_banner_workbook(INDEX_PATH, sheet="Broad Market")
    bench_close = idx_df[BENCHMARK_COL].reindex(price_window.index).ffill()

    print(f"\nRunning cross-sectional backtest: top {N_HOLD} names by 12-1 momentum, "
          f"equal-weighted, {REBALANCE} rebalance, {SPREAD_BPS:.0f}bp cost, {LAG_DAYS}d lag...")
    bt = Backtester(prices=price_window, assets=assets, spread_bps=SPREAD_BPS,
                    lag_days=LAG_DAYS, allow_cash=True, membership=membership)
    alloc = build_allocator("cross_sectional", assets, n_hold=N_HOLD, weighting="equal",
                            min_names=N_HOLD, ascending=False)
    result = bt.run(allocator=alloc, rebalance=REBALANCE, alpha=alpha,
                    name="accord_stock_selection", warmup=MOM_LOOKBACK_DAYS + MOM_SKIP_DAYS + 5)

    live = result.value.loc[(result.value.index >= BACKTEST_START) & (result.value.index <= BACKTEST_END)]
    live_returns = live.pct_change(fill_method=None).fillna(0.0)
    live_returns.iloc[0] = 0.0
    bench_live = bench_close.reindex(live.index)

    print("\n" + "=" * 70)
    print(f"RESULTS -- {live.index.min().date()} -> {live.index.max().date()}")
    print("=" * 70)
    total_ret = live.iloc[-1] / live.iloc[0] - 1.0
    years = (live.index[-1] - live.index[0]).days / 365.25
    cagr = (1 + total_ret) ** (1 / years) - 1.0
    print(f"Total return: {total_ret:.1%}  |  CAGR: {cagr:.2%}  |  years: {years:.2f}")
    print(f"mean cash weight: {result.cash_weight.reindex(live.index).mean():.1%}")

    class _Wrapped:
        pass
    wrapped = _Wrapped()
    wrapped.value = live
    wrapped.returns = live_returns
    sheet = compute_tearsheet(wrapped, bench_close.reindex(live.index))
    print("\nFull tearsheet (strategy vs. " + BENCHMARK_DISPLAY_NAME + "):")
    print(render_tearsheet(sheet))

    boot = bootstrap_sharpe_ci(live_returns, block_size=20, n_resamples=1000, seed=0)
    print(f"\nSharpe ratio, 90% block-bootstrap CI: [{boot.ci_low:.2f}, {boot.ci_high:.2f}] "
          f"(point estimate {boot.point_estimate:.2f}, {boot.fraction_positive:.0%} of "
          f"resamples positive)")
    N_TRIALS_ROUGH_ESTIMATE = 3   # N_HOLD, lookback, skip -- a rough tally, not a logged trial count
    dsr = deflated_sharpe_from_returns(live_returns, n_trials=N_TRIALS_ROUGH_ESTIMATE, trial_sharpe_std=0.3)
    print(f"Deflated Sharpe Ratio (rough, n_trials={N_TRIALS_ROUGH_ESTIMATE}): {dsr:.2f}")

    monthly_strategy = (1 + live_returns).resample("ME").prod() - 1
    monthly_bench = (1 + bench_live.pct_change(fill_method=None).fillna(0.0)).resample("ME").prod() - 1
    common = monthly_strategy.index.intersection(monthly_bench.index)
    monthly_strategy, monthly_bench = monthly_strategy.loc[common], monthly_bench.loc[common]

    xlsx_path = os.path.join(OUTPUT_DIR, "accord_stock_selection_se_return_analytics.xlsx")
    csv_path = os.path.join(OUTPUT_DIR, "accord_stock_selection_se_return_analytics.csv")
    write_se_return_analytics_workbook(xlsx_path, common, monthly_strategy, monthly_bench,
                                       strategy_name="Accord Stock Selection", benchmark_name=BENCHMARK_DISPLAY_NAME)
    write_se_return_analytics_csv(csv_path, common, monthly_strategy, monthly_bench,
                                  strategy_name="Accord Stock Selection", benchmark_name=BENCHMARK_DISPLAY_NAME)
    print(f"\nSE Return Analytics written to:\n  {xlsx_path}\n  {csv_path}")

    trade_log_path = os.path.join(OUTPUT_DIR, "accord_stock_selection_trade_log.csv")
    pd.DataFrame({
        "date": live.index, "nav": live.values,
        "turnover": result.turnover.reindex(live.index).values,
        "cost": result.costs.reindex(live.index).values,
        "cash_weight": result.cash_weight.reindex(live.index).values,
    }).to_csv(trade_log_path, index=False)
    print(f"Trade log written to: {trade_log_path}")


if __name__ == "__main__":
    main()
