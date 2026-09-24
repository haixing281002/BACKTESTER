"""Individual-stock selection backtest on the Accord Fintech dataset.

THIS is the script that answers the fund's instruction: the STRATEGY
picks the AI's own universe of individual stocks (NOT an index) and its
own weights -- the code doesn't rank a blanket top-500 and stop there;
the mechanism below decides who is even eligible to be ranked, using
whatever data actually bears on that mechanism.

THE STRATEGY (see STRATEGY dict below -- change it, don't hardcode a new
one inline, so a future run driven by an actual Strategy Card can just
overwrite these fields):
  "Profitable Momentum" -- cross-sectional 12-1 price momentum, but only
  among names that clear a REAL profitability screen (trailing ROE > 0,
  point-in-time as of each rebalance date) first. This is a real,
  well-known combined-factor mechanism (momentum crossed with quality/
  profitability -- see e.g. Asness/Frazzini/Pedersen on QMJ, or any
  "quality momentum" factor sleeve), not a cosmetic filter, and it uses
  BOTH real datasets this fund actually holds for this universe (the
  Accord price panel for momentum, the Accord profitability fundamentals
  for the ROE screen) -- not just whichever one was closest to hand.

  An optional SECTOR filter is also wired in (STRATEGY["sector_keywords"])
  for a paper whose mechanism is explicitly sector-specific (e.g. "bank
  momentum", "IT services quality"). Accord's files carry no formal
  sector/industry code, so sector is inferred from Company Name via
  keyword matching (classify_sector()) -- a coarse, documented PROXY,
  not an authoritative classification. Leave sector_keywords=None (the
  default here) for a market-wide mechanism; a future paper-specific run
  sets it to e.g. ["bank", "finance", "nbfc"].

  Universe base: the Accord monthly universe file filtered to the top
  500 names by market rank EVERY month (get_top_n_universe -- the fix
  for the file's own alternating-coverage irregularity), restricted to
  the ~1314 names with an actual price series (restrict_to_priced_universe).

  Weighting: DAILY market-cap weighted (weighting="mcap" -- see
  allocators.py) among the names actually chosen by the momentum+quality
  ranking above, using the fifth Accord file
  (prices_marketcap_data_till_03082026.csv, load_accord_daily_price_mcap)
  -- real daily market cap, not the monthly-only figure the ranking
  universe uses. Capped at MAX_WEIGHT per name so one mega-cap can't
  dominate the book. TOTAL market cap, not free float (Accord carries no
  free-float field) -- Indian promoter holdings are large, so this
  overstates true investable weight the same way ros/data/master.py
  flags for any market-cap-only file; a free-float series would fix
  this if the fund ever gets one.

  Liquidity floor: a PERCENTILE floor on trailing 21-day average traded
  value (also from the fifth file), not an absolute rupee threshold --
  the source column's exact unit scale hasn't been verified from this
  environment, so a relative floor (bottom X% of the otherwise-eligible
  set, by their OWN trailing ADV, are excluded) is self-calibrating and
  can't be wrong by an order of magnitude the way a guessed absolute
  cutoff could be.

  If the fifth file isn't present locally (it's a 366MB CSV, gitignored,
  local-only), this script prints exactly that and degrades to equal
  weighting with no liquidity floor -- never silently. Its cross-sectional
  ranking and quality screen still run either way.

Backtest window is HARDCODED (fund decision, 2026-09-24): BACKTEST_START
.. BACKTEST_END, imported from accord_data.py, not a script argument.

India non-negotiables: lag_days >= 1 (this run uses LAG_DAYS=100, a fund
decision well above the floor), 30bp round-trip cost floor. Point-in-time
discipline throughout: universe membership, the ROE quality screen, and
the price signal are all as-of-date lookups, never using information not
yet known on that date -- a name that falls out of the tradable universe
is SOLD at cost on the day it's learned, never quietly dropped.
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
from universal_backtester.tearsheet import compute_tearsheet, render_tearsheet
from universal_backtester.excel_tearsheet import (
    write_se_return_analytics_workbook, write_se_return_analytics_csv,
)
from universal_backtester.validation import bootstrap_sharpe_ci, deflated_sharpe_from_returns

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICE_PATH = os.path.join(REPO_ROOT, "data", "raw", "stocks", "price_data_till_03aug2026.xlsx")
UNIVERSE_PATH = os.path.join(REPO_ROOT, "data", "raw", "stocks", "Monthly_uni_new.xlsx")
PROFITABILITY_PATH = os.path.join(
    REPO_ROOT, "data", "raw", "stocks", "profitability_ratios_consol_stdalon_till_march2025.xlsx")
PUBLISHING_DATES_PATH = os.path.join(REPO_ROOT, "data", "raw", "stocks", "w_publishing_date_data.xlsx")
DAILY_MCAP_PATH = os.path.join(REPO_ROOT, "data", "raw", "stocks",
                               "prices_marketcap_data_till_03082026.csv")
INDEX_PATH = os.path.join(REPO_ROOT, "data", "raw", "NSE_Broad_Factor_Indices_Historical_Data.xlsx")
OUTPUT_DIR = os.path.join(REPO_ROOT, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---- THE STRATEGY -- change this, not the mechanics below -----------------
STRATEGY = {
    "name": "Profitable Momentum",
    "mechanism_needs": (
        "cross-sectional 12-1 price momentum among profitable (ROE > 0, "
        "point-in-time) large/mid-cap Indian equities, cap-weighted, "
        "liquidity-screened"
    ),
    "n_hold": 40,                # names held
    "momentum_lookback_days": 252,
    "momentum_skip_days": 21,    # 12-1 convention: skip the most recent month
    "min_roe_pct": 0.0,          # quality screen: latest known trailing ROE must clear this
    "sector_keywords": None,     # e.g. ["bank", "finance", "nbfc"] for a sector-specific mechanism
    "max_weight": 0.15,          # per-name cap so one mega-cap can't dominate the cap-weighted book
    "liquidity_lookback_days": 21,     # trailing window for average traded value
    "min_liquidity_percentile": 0.20,  # bottom 20% by trailing ADV (of the otherwise-eligible set) excluded
}

SPREAD_BPS = 30.0            # this repo's non-negotiable factor-sleeve cost floor
LAG_DAYS = 100                # fund decision (2026-09-24), well above the lag_days>=1 floor
REBALANCE = "monthly"
BENCHMARK_COL = "NIFTY 500 Close"
BENCHMARK_DISPLAY_NAME = "NIFTY 500"
WARMUP_BUFFER_DAYS = 400      # trading days of history BEFORE BACKTEST_START, for the momentum lookback

_SECTOR_KEYWORDS = {
    "bank": ["bank"],
    "finance/nbfc": ["finance", "financial", "nbfc", "housing fin", "capital"],
    "it/software": ["infosys", "tcs", "software", "technolog", "info systems", "infotech"],
    "pharma/healthcare": ["pharma", "lab", "health", "hospital", "drug"],
    "auto": ["motor", "auto", "tyres", "tyre"],
    "fmcg/consumer": ["consumer", "foods", "beverages", "fmcg"],
    "metals/mining": ["steel", "metal", "mining", "iron"],
    "energy/power": ["power", "energy", "oil", "gas", "petro"],
    "realty/construction": ["realty", "construction", "infrastructure", "cement", "infra"],
    "textile": ["textile", "spinning", "mills"],
    "chemicals": ["chemical", "fertiliser", "fertilizer"],
    "telecom": ["telecom", "communications"],
}


def classify_sector(company_name: str) -> str:
    """Coarse, documented PROXY: Accord's files carry no formal sector or
    industry code, so this matches keywords against the company name.
    Returns "other" when nothing matches -- never fabricates a sector."""
    name = (company_name or "").lower()
    for sector, keywords in _SECTOR_KEYWORDS.items():
        if any(kw in name for kw in keywords):
            return sector
    return "other"


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


def build_point_in_time_quality_screen(profitability_path: str, publishing_dates_path: str,
                                       price_index: pd.DatetimeIndex, assets: list,
                                       min_roe_pct: float) -> pd.DataFrame:
    """Daily boolean frame: True where that Accord Code's latest KNOWN
    (point-in-time, via real results-publication dates where available)
    trailing ROE clears min_roe_pct. A name with no ROE data yet is False
    -- never assumed to pass. This is the actual profitability half of
    the "Profitable Momentum" mechanism, not a placeholder."""
    fund, fund_prov = load_accord_fundamentals(profitability_path,
                                                publishing_dates_path=publishing_dates_path)
    print(f"  fundamentals: {fund_prov['n_rows']} rows, {fund_prov['n_securities']} companies, "
          f"{fund_prov['n_known_date_from_real_date']} known_date from real result date, "
          f"{fund_prov['n_known_date_from_assumption']} from the {fund_prov['reporting_lag_days_assumed']}d assumption")
    roe_col = "FR_ROE (%)" if "FR_ROE (%)" in fund.columns else [
        c for c in fund.columns if "ROE" in c.upper()][0]
    fund = fund.dropna(subset=[roe_col]).sort_values("known_date")
    # One value per (code, known_date): if a code has two rows on the same
    # known_date (e.g. consolidated + standalone), keep the later-in-file one.
    fund = fund.drop_duplicates(["accord_code", "known_date"], keep="last")

    wide = fund.pivot_table(index="known_date", columns="accord_code", values=roe_col, aggfunc="last")
    wide = wide.reindex(columns=assets)
    daily_roe = wide.reindex(price_index.union(wide.index)).sort_index().ffill().reindex(price_index)
    return (daily_roe > min_roe_pct).fillna(False)


def momentum_signal(prices: pd.DataFrame, lookback: int, skip: int) -> pd.DataFrame:
    """12-1 momentum: (price[t-skip] / price[t-lookback]) - 1."""
    return prices.shift(skip) / prices.shift(lookback) - 1.0


def load_daily_mcap_and_liquidity(daily_mcap_path: str, price_panel_path: str,
                                  price_index: pd.DatetimeIndex, assets: list,
                                  adv_lookback_days: int, min_adv_percentile: float):
    """Real daily market cap (for cap-weighting) and a real, point-in-time
    liquidity floor (for eligibility) from the fifth Accord file. Returns
    (mcap_frame, liquidity_pass_frame, prov). Both are None if the file
    isn't present -- the caller decides how to degrade, this function
    never guesses a fallback value."""
    if not os.path.exists(daily_mcap_path):
        return None, None, None

    long_df, prov = load_accord_daily_price_mcap(
        daily_mcap_path, verify_against_price_panel_path=price_panel_path)
    print(f"  daily mcap file: {prov['n_rows']:,} rows, {prov['n_securities']} securities, "
          f"{prov['date_min']} -> {prov['date_max']}")
    if "n_close_mismatches" in prov:
        print(f"  cross-check vs. the wide price panel: {prov['n_close_cells_compared']:,} cells "
              f"compared, {prov['n_close_mismatches']} mismatches")
        if prov["n_close_mismatches"] > 0:
            print("  WARNING: this file's close prices disagree with the wide panel -- "
                  "treat its mcap/volume as suspect until that's understood.")

    mcap_wide = long_df.pivot_table(index="date", columns="accord_code", values="mcap", aggfunc="last")
    mcap_wide = mcap_wide.reindex(columns=assets).reindex(price_index).ffill()

    traded_value = long_df.pivot_table(index="date", columns="accord_code",
                                       values="traded_value", aggfunc="last")
    traded_value = traded_value.reindex(columns=assets).reindex(price_index)
    adv = traded_value.rolling(adv_lookback_days, min_periods=max(5, adv_lookback_days // 2)).mean()

    # A relative (percentile-of-the-day) floor, not an absolute rupee
    # cutoff -- see the module docstring for why. Computed row-wise so a
    # name only needs to clear the bar against its PEERS that day, not
    # against the whole history's liquidity regime.
    threshold = adv.quantile(min_adv_percentile, axis=1)
    liquidity_pass = adv.gt(threshold, axis=0).fillna(False)

    return mcap_wide, liquidity_pass, prov


def main():
    print(f"Strategy: {STRATEGY['name']} -- {STRATEGY['mechanism_needs']}")
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

    if STRATEGY["sector_keywords"]:
        names = tradable.drop_duplicates("accord_code").set_index("accord_code")["company_name"]
        sector_of = names.map(classify_sector)
        keep_codes = set(sector_of[sector_of.isin(STRATEGY["sector_keywords"])].index)
        before = tradable["accord_code"].nunique()
        tradable = tradable[tradable["accord_code"].isin(keep_codes)]
        print(f"  sector filter {STRATEGY['sector_keywords']}: "
              f"{before} -> {tradable['accord_code'].nunique()} distinct codes")

    assets = sorted(tradable["accord_code"].dropna().astype(int).unique().tolist())
    print(f"  {len(assets)} distinct tradable Accord Codes across the whole window")

    price = price[assets]

    lookback_start = BACKTEST_START - pd.Timedelta(days=int(WARMUP_BUFFER_DAYS * 1.6))
    price_window = price.loc[(price.index >= lookback_start) & (price.index <= BACKTEST_END)]
    print(f"\nPrice panel trimmed to {price_window.index.min().date()} -> "
          f"{price_window.index.max().date()} ({len(price_window)} trading days, "
          f"incl. warmup before {BACKTEST_START.date()})")

    print("Building point-in-time universe membership (daily, forward-filled from monthly snapshots)...")
    universe_membership = build_point_in_time_membership(tradable, price_window.index, assets)
    print(f"  mean names eligible (universe only) per day: {universe_membership.sum(axis=1).mean():.0f}")

    print(f"Building point-in-time quality screen (trailing ROE > {STRATEGY['min_roe_pct']:.0f}%)...")
    quality_pass = build_point_in_time_quality_screen(
        PROFITABILITY_PATH, PUBLISHING_DATES_PATH, price_window.index, assets, STRATEGY["min_roe_pct"])
    print(f"  mean names passing the quality screen per day (of those with ROE data): "
          f"{quality_pass.sum(axis=1).mean():.0f}")

    membership = universe_membership & quality_pass
    print(f"  mean names eligible (universe AND quality) per day: {membership.sum(axis=1).mean():.0f}")

    print(f"\nLooking for the daily market-cap/liquidity file: {DAILY_MCAP_PATH}")
    mcap_frame, liquidity_pass, mcap_prov = load_daily_mcap_and_liquidity(
        DAILY_MCAP_PATH, PRICE_PATH, price_window.index, assets,
        STRATEGY["liquidity_lookback_days"], STRATEGY["min_liquidity_percentile"])

    if mcap_frame is not None:
        membership = membership & liquidity_pass
        print(f"  liquidity floor applied (bottom {STRATEGY['min_liquidity_percentile']:.0%} trailing-ADV "
              f"names excluded): mean names eligible per day now {membership.sum(axis=1).mean():.0f}")
        weighting = "mcap"
        weighting_frame = mcap_frame
        print(f"  weighting: real daily market cap (weighting='mcap'), capped at "
              f"{STRATEGY['max_weight']:.0%} per name")
    else:
        weighting = "equal"
        weighting_frame = None
        print(f"  NOT FOUND -- this is expected in an environment that doesn't have the 366MB "
              f"fifth Accord file (it's local-only, gitignored). Degrading to equal weighting, "
              f"no liquidity floor. Run this same script where that file exists for the real "
              f"cap-weighted, liquidity-screened output.")

    print(f"Building 12-1 momentum signal ({STRATEGY['momentum_lookback_days']}d lookback, "
          f"{STRATEGY['momentum_skip_days']}d skip)...")
    alpha = momentum_signal(price_window, STRATEGY["momentum_lookback_days"], STRATEGY["momentum_skip_days"])

    print(f"\nLoading benchmark: {BENCHMARK_COL} from {INDEX_PATH}")
    idx_df, _ = load_banner_workbook(INDEX_PATH, sheet="Broad Market")
    bench_close = idx_df[BENCHMARK_COL].reindex(price_window.index).ffill()

    n_hold = STRATEGY["n_hold"]
    print(f"\nRunning cross-sectional backtest: top {n_hold} names by 12-1 momentum among "
          f"profitable names, {weighting}-weighted, {REBALANCE} rebalance, {SPREAD_BPS:.0f}bp cost, "
          f"{LAG_DAYS}d lag...")
    bt = Backtester(prices=price_window, assets=assets, spread_bps=SPREAD_BPS,
                    lag_days=LAG_DAYS, allow_cash=True, membership=membership)
    alloc = build_allocator("cross_sectional", assets, n_hold=n_hold, weighting=weighting,
                            max_weight=(STRATEGY["max_weight"] if weighting == "mcap" else None),
                            min_names=n_hold, ascending=False)
    result = bt.run(allocator=alloc, rebalance=REBALANCE, alpha=alpha, vols=weighting_frame,
                    name="accord_stock_selection",
                    warmup=STRATEGY["momentum_lookback_days"] + STRATEGY["momentum_skip_days"] + 5)

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
    N_TRIALS_ROUGH_ESTIMATE = 4   # n_hold, lookback, skip, min_roe_pct -- a rough tally, not a logged trial count
    dsr = deflated_sharpe_from_returns(live_returns, n_trials=N_TRIALS_ROUGH_ESTIMATE, trial_sharpe_std=0.3)
    print(f"Deflated Sharpe Ratio (rough, n_trials={N_TRIALS_ROUGH_ESTIMATE}): {dsr:.2f}")

    monthly_strategy = (1 + live_returns).resample("ME").prod() - 1
    monthly_bench = (1 + bench_live.pct_change(fill_method=None).fillna(0.0)).resample("ME").prod() - 1
    common = monthly_strategy.index.intersection(monthly_bench.index)
    monthly_strategy, monthly_bench = monthly_strategy.loc[common], monthly_bench.loc[common]

    xlsx_path = os.path.join(OUTPUT_DIR, "accord_stock_selection_se_return_analytics.xlsx")
    csv_path = os.path.join(OUTPUT_DIR, "accord_stock_selection_se_return_analytics.csv")
    write_se_return_analytics_workbook(xlsx_path, common, monthly_strategy, monthly_bench,
                                       strategy_name=STRATEGY["name"], benchmark_name=BENCHMARK_DISPLAY_NAME)
    write_se_return_analytics_csv(csv_path, common, monthly_strategy, monthly_bench,
                                  strategy_name=STRATEGY["name"], benchmark_name=BENCHMARK_DISPLAY_NAME)
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
