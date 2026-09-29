"""Execution script for cards/asness_2015_india_value_composite_longshort.yaml.

Step 05 for this card, referenced in the card's own signal.description but
not written until now. Mirrors scripts/alquist_2018_india_small_cap_backtest.py
in shape (same Accord loaders, same point-in-time universe discipline), but:

  - ranks on a COMPOSITE FUNDAMENTAL VALUE Z-SCORE (E/P + EBIT/EV, both
    inverted from Accord's Adjusted PE / EV-EBIT), not market cap;
  - the composite is built POINT-IN-TIME per security: each name's ratio
    updates exactly on ITS OWN known_date (real result-publication date
    where available, else the assumed lag), never before;
  - trades BOTH legs -- CHEAP (long) and EXPENSIVE (short) -- through
    universal_backtester's allow_short=True engine path with
    CrossSectionalLongShort, per the fund's 2026-09-28 short-selling
    mandate update. ros/engine is never touched.
  - rebalances ANNUALLY (quantile=0.10, the card's own decile decision --
    revised 2026-09-28 from the paper's own tercile/30% convention).

SIMPLIFICATION FROM THE CARD'S OWN backtest_plan.rebalance_rule: the card
states each security should rebalance "at the first trading day on or after
each security's own known_date," not a single fixed calendar date for the
whole book. This script uses one fixed annual rebalance date for every name
(the engine's standard "annual" cadence: the last trading day of each
fiscal-year period present in the data) and, AT that single date, reads
each name's own latest point-in-time-correct composite value as of that
date. This is a common, reasonable backtesting simplification -- a desk
picks one review date and uses whatever is publicly known for each name as
of it -- rather than the harder problem of a genuinely per-security
rebalance calendar, which no allocator in this repo currently supports.
Recorded here, not silently taken.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from universal_backtester.accord_data import (
    load_accord_price_panel, load_accord_monthly_universe, load_accord_fundamentals,
    get_top_n_universe, restrict_to_priced_universe, BACKTEST_START, BACKTEST_END,
)
from universal_backtester.data import load_banner_workbook, write_holdings_log
from universal_backtester.engine import Backtester, assert_causal, LookaheadError
from universal_backtester.allocators import build_allocator
from universal_backtester.tearsheet import compute_tearsheet, render_tearsheet
from universal_backtester.validation import bootstrap_sharpe_ci, deflated_sharpe_from_returns
from universal_backtester.charting import save_backtest_charts, save_decile_charts
from universal_backtester.metrics import cagr as _cagr, ann_vol as _ann_vol, max_drawdown as _mdd
from universal_backtester.excel_tearsheet import (
    write_se_return_analytics_workbook, write_se_return_analytics_csv,
)
from universal_backtester.decile_analysis import (
    compute_decile_membership, run_decile_backtests, summarize_deciles,
    write_decile_membership_log, write_decile_summary_workbook,
)
from ros.validation.portfolio import factor_fingerprint
from universal_backtester.checkpoint import checkpoint

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICE_PATH = os.path.join(REPO_ROOT, "data", "raw", "stocks", "price_data_till_03aug2026.xlsx")
UNIVERSE_PATH = os.path.join(REPO_ROOT, "data", "raw", "stocks", "Monthly_uni_new.xlsx")
VALUATION_PATH = os.path.join(REPO_ROOT, "data", "raw", "stocks", "valuation_ratios_all_till_2025.xlsx")
PUBDATES_PATH = os.path.join(REPO_ROOT, "data", "raw", "stocks", "w_publishing_date_data.xlsx")
INDEX_PATH = os.path.join(REPO_ROOT, "data", "raw", "NSE_Broad_Factor_Indices_Historical_Data.xlsx")
OUTPUT_DIR = os.path.join(REPO_ROOT, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# REVERTED 2026-09-28 to the paper's own top/bottom-30% tercile cut exactly
# (Exhibit 3 caption) -- see cards/.../longshort.yaml broken_assumptions.
QUANTILE = 0.30
MIN_NAMES = 60           # TOTAL across both legs -- see signal.params comment on the card
LONG_WEIGHT = 0.5
SHORT_WEIGHT = 0.5
SPREAD_BPS = 30.0
BORROW_BPS = 100.0       # flat placeholder -- card's own stated, unverified assumption
LAG_DAYS = 1
REBALANCE = "annual"
WARMUP_BUFFER_DAYS = 365  # one fiscal year + publication lag, per the card's own warmup_days

# Local override, requested 2026-09-28: run this specific comparison from
# 2014-04-01 instead of accord_data.BACKTEST_START (2013-03-31). Shadows the
# imported name for THIS script only -- accord_data.py itself is untouched,
# so every other script still uses the original window.
BACKTEST_START = pd.Timestamp("2014-04-01")

BASIS_PREFERENCE = {"consolidated": 0, "standalone": 1}

BENCHMARKS = {
    "NIFTY 500": ("Broad Market", "NIFTY 500 Close"),
    "NIFTY500 VALUE 50": ("Factor Indices", "NIFTY500 VALUE 50 Close"),
    "NIFTY200 VALUE 30": ("Factor Indices", "NIFTY200 VALUE 30 Close"),
    "NIFTY500 MOMENTUM 50": ("Factor Indices", "NIFTY500 MOMENTUM 50 Close"),
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


def build_daily_step(fund_pref: pd.DataFrame, value_col: str, assets: list,
                      price_index: pd.DatetimeIndex) -> pd.DataFrame:
    """Per-security step function: value updates exactly on known_date, held
    constant until the next known_date for that security. Never leaks a
    value before it was actually knowable."""
    piv = fund_pref.pivot_table(index="known_date", columns="accord_code",
                                values=value_col, aggfunc="last")
    piv = piv.reindex(columns=assets).sort_index()
    union_idx = price_index.union(piv.index)
    daily = piv.reindex(union_idx).sort_index().ffill().reindex(price_index)
    return daily


def zscore_cross_section(frame: pd.DataFrame, mask: pd.DataFrame) -> pd.DataFrame:
    valid = frame.where(mask)
    mean = valid.mean(axis=1)
    std = valid.std(axis=1)
    return valid.sub(mean, axis=0).div(std.replace(0.0, np.nan), axis=0)


def run_causality_checks(signals: dict, returns: pd.DataFrame, lag_days: int) -> None:
    """Look-ahead tripwire on every real signal this script feeds the
    engine, plus two negative controls proving the tripwire itself would
    catch a real leak in THIS run's own return series -- the same
    discipline run_pipeline.py's governed path already applies
    automatically.

    The real-signal checks print PASS/FAIL rather than raising:
    assert_causal is a correlation-based smell test, not a proof, and a
    genuinely strong, correctly-lagged signal (e.g. a momentum score) can
    legitimately correlate with the return it trades above the default
    threshold with no leak present -- a hard raise here would abort a
    correct production run on exactly the signals most worth running.
    Consistent with this repo's own rule that code reports and a human
    decides, a FAIL here is a flag for review, not an automatic halt.
    The negative controls, by contrast, are EXPECTED to be caught --
    "BROKEN" (not raising) means the tripwire itself is broken and is
    printed loudly for that reason."""
    print("\nLook-ahead tripwires (signal[t] vs return[t] and return[t+1]):")
    for label, sig in signals.items():
        if sig is None:
            continue
        shifted = sig.shift(1 + lag_days)
        try:
            assert_causal(shifted, returns, label=label)
            print(f"  PASS  {label}")
        except LookaheadError as e:
            print(f"  FAIL  {e}")
    for label, planted in [("planted same-bar leak", returns),
                           ("planted next-bar leak", returns.shift(-1))]:
        try:
            assert_causal(planted, returns, label=label)
            print(f"  BROKEN  negative control '{label}' was NOT caught")
        except LookaheadError:
            print(f"  PASS  negative control '{label}' correctly caught")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--auto-approve", action="store_true",
                    help="Skip every interactive stage pause and run straight through.")
    args = ap.parse_args()
    produced: list = []   # absolute local paths, shown at every checkpoint below

    print("Card: asness_2015_india_value_composite_longshort")
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

    assets = sorted(tradable["accord_code"].dropna().astype(int).unique().tolist())
    print(f"  {len(assets)} distinct tradable Accord Codes across the whole window")
    price = price[assets]

    # Root cause of the flat "0.00%" rows the user saw at the start of the
    # reported window: engine.py's `warmup` parameter counts TRADING-DAY
    # rows since price_window's own start, not calendar days -- so
    # warmup=365 is really ~17.4 calendar months of runway before the FIRST
    # rebalance is even eligible, not ~12. With only the ~13.2-month
    # lookback below (WARMUP_BUFFER_DAYS*1.1), the engine's warmup-eligible
    # date lands ~4 months AFTER BACKTEST_START, pushing the Dec-31 annual
    # anchor right before BACKTEST_START out of reach and forcing the
    # engine to wait for the NEXT Dec-31 anchor -- several months of
    # cash-only (0.00%) rows sitting inside the reported window. Requested
    # fix: pull price/signal history far enough back that the Dec-31
    # rebalance immediately BEFORE BACKTEST_START is already warmup-eligible,
    # so the fund already holds live positions on day one of the reported
    # window -- BACKTEST_START itself (the reporting/truncation boundary)
    # is unchanged.
    EXTRA_LOOKBACK_DAYS = 270  # ~9 months, sized to the trading/calendar-day gap above
    lookback_start = BACKTEST_START - pd.Timedelta(days=int(WARMUP_BUFFER_DAYS * 1.1) + EXTRA_LOOKBACK_DAYS)
    price_window = price.loc[(price.index >= lookback_start) & (price.index <= BACKTEST_END)]
    print(f"\nPrice panel trimmed to {price_window.index.min().date()} -> "
          f"{price_window.index.max().date()} ({len(price_window)} trading days)")

    print("Building point-in-time universe membership...")
    universe_membership = build_point_in_time_membership(tradable, price_window.index, assets)
    print(f"  mean names eligible (universe only) per day: {universe_membership.sum(axis=1).mean():.0f}")

    print(f"\nLoading Accord valuation ratios: {VALUATION_PATH}")
    pub_path = PUBDATES_PATH if os.path.exists(PUBDATES_PATH) else None
    if pub_path is None:
        print(f"  WARNING: {PUBDATES_PATH} not found on this machine -- despite the README and "
              f"firm_registry.py describing it as held locally. Falling back to the flat "
              f"DEFAULT_REPORTING_LAG_DAYS assumption for every row (no real result dates). "
              f"This is a real, newly-discovered discrepancy: this card's known_date-based "
              f"point-in-time gating is weaker in practice than documented until this file is "
              f"actually supplied. Recorded, not silently absorbed.")
    else:
        print(f"Loading Accord publication dates: {PUBDATES_PATH}")
    fund, fund_prov = load_accord_fundamentals(VALUATION_PATH, publishing_dates_path=pub_path)
    print(f"  {fund_prov['n_rows']:,} rows, {fund_prov['n_securities']} securities, "
          f"{fund_prov['n_known_date_from_real_date']:,} real result dates, "
          f"{fund_prov['n_known_date_from_assumption']:,} assumed-lag fallback")

    # Basis preference: consolidated over standalone (card's own stated,
    # unswept choice -- see cards/.../longshort.yaml ambiguities).
    fund = fund.copy()
    fund["basis_rank"] = fund["basis"].map(BASIS_PREFERENCE).fillna(2)
    fund = fund.sort_values(["accord_code", "fiscal_year_end_date", "basis_rank"])
    fund_pref = fund.drop_duplicates(["accord_code", "fiscal_year_end_date"], keep="first")

    pe_col, evebit_col = "FR_Adjusted PE (x)", "FR_EV/EBIT(x)"
    fund_pref["ep"] = 1.0 / fund_pref[pe_col]
    fund_pref.loc[fund_pref[pe_col] <= 0, "ep"] = np.nan
    fund_pref["ebit_ev"] = 1.0 / fund_pref[evebit_col]
    fund_pref.loc[fund_pref[evebit_col] <= 0, "ebit_ev"] = np.nan

    print("Building point-in-time daily E/P and EBIT/EV step series (per-security known_date)...")
    ep_daily = build_daily_step(fund_pref, "ep", assets, price_window.index)
    ebitev_daily = build_daily_step(fund_pref, "ebit_ev", assets, price_window.index)

    eligible = universe_membership & ep_daily.notna() & ebitev_daily.notna()
    print(f"  mean names eligible (universe + both value ratios known) per day: "
          f"{eligible.sum(axis=1).mean():.0f}")

    ep_z = zscore_cross_section(ep_daily, eligible)
    ebitev_z = zscore_cross_section(ebitev_daily, eligible)
    composite = (ep_z + ebitev_z) / 2.0
    print("  composite = equal-weighted average of E/P and EBIT/EV cross-sectional z-scores")

    # Diagnostic the card itself flags as decisive: how correlated are the
    # two legs actually? If near 1.0, "composite" is a label, not a fact.
    corr_by_date = ep_z.corrwith(ebitev_z, axis=1)
    print(f"  E/P vs EBIT/EV cross-sectional correlation: mean {corr_by_date.mean():.3f}, "
          f"median {corr_by_date.median():.3f} across {corr_by_date.notna().sum()} rebalance-eligible days")

    returns_check = price_window[assets].pct_change(fill_method=None)
    run_causality_checks({"composite_value_z": composite}, returns_check, LAG_DAYS)

    print(f"\nLoading benchmarks from {INDEX_PATH}")
    bench_closes = {}
    for disp_name, (sheet, col) in BENCHMARKS.items():
        idx_df, _ = load_banner_workbook(INDEX_PATH, sheet=sheet)
        bench_closes[disp_name] = idx_df[col].reindex(price_window.index).ffill()
        print(f"  {disp_name}: loaded")

    def to_live(v):
        return v.loc[(v.index >= BACKTEST_START) & (v.index <= BACKTEST_END)]

    if not checkpoint("STAGE 1 OF 5 -- DATA LOADED, UNIVERSE + VALUE SIGNAL BUILT", produced,
                      auto_approve=args.auto_approve):
        return

    print(f"\nRunning long-short book (CHEAP top {QUANTILE:.0%} long, "
          f"EXPENSIVE bottom {QUANTILE:.0%} short, {LONG_WEIGHT:.0%}/{SHORT_WEIGHT:.0%} notional)...")
    bt_ls = Backtester(prices=price_window, assets=assets, spread_bps=SPREAD_BPS,
                       lag_days=LAG_DAYS, allow_cash=True, membership=eligible,
                       allow_short=True, max_gross_exposure=1.0, short_borrow_bps=BORROW_BPS)
    alloc_ls = build_allocator("cross_sectional_long_short", assets, quantile=QUANTILE,
                               weighting="equal", long_weight=LONG_WEIGHT,
                               short_weight=SHORT_WEIGHT, min_names=MIN_NAMES)
    result_ls = bt_ls.run(allocator=alloc_ls, rebalance=REBALANCE, alpha=composite,
                          name="India composite value, long-short", warmup=WARMUP_BUFFER_DAYS)

    print(f"Running CHEAP-only long leg (top {QUANTILE:.0%}, same universe and rule)...")
    bt_cheap = Backtester(prices=price_window, assets=assets, spread_bps=SPREAD_BPS,
                          lag_days=LAG_DAYS, allow_cash=True, membership=eligible)
    alloc_cheap = build_allocator("cross_sectional", assets, quantile=QUANTILE, weighting="equal",
                                  ascending=False, min_names=MIN_NAMES // 2)
    result_cheap = bt_cheap.run(allocator=alloc_cheap, rebalance=REBALANCE, alpha=composite,
                                name="CHEAP-only long leg", warmup=WARMUP_BUFFER_DAYS)

    live_ls = to_live(result_ls.value)
    live_cheap = to_live(result_cheap.value)
    ret_ls = live_ls.pct_change(fill_method=None).fillna(0.0)
    ret_ls.iloc[0] = 0.0
    ret_cheap = live_cheap.pct_change(fill_method=None).fillna(0.0)
    ret_cheap.iloc[0] = 0.0

    print("\n" + "=" * 78)
    print(f"RESULTS -- {live_ls.index.min().date()} -> {live_ls.index.max().date()}")
    print("=" * 78)

    rows = []
    for label, value, returns in [
        ("India composite value, long-short", live_ls, ret_ls),
        ("CHEAP-only long leg", live_cheap, ret_cheap),
    ]:
        rows.append({
            "name": label, "cagr": _cagr(value), "vol": _ann_vol(returns),
            "sharpe": (_cagr(value) - 0.06) / _ann_vol(returns) if _ann_vol(returns) > 0 else float("nan"),
            "max_dd": _mdd(value), "n_obs": len(value),
            "start": str(value.index.min().date()), "end": str(value.index.max().date()),
        })
    for disp_name, close in bench_closes.items():
        bv = close.reindex(live_ls.index).dropna()
        br = bv.pct_change(fill_method=None).fillna(0.0)
        rows.append({
            "name": disp_name, "cagr": _cagr(bv), "vol": _ann_vol(br),
            "sharpe": (_cagr(bv) - 0.06) / _ann_vol(br) if _ann_vol(br) > 0 else float("nan"),
            "max_dd": _mdd(bv), "n_obs": len(bv),
            "start": str(bv.index.min().date()), "end": str(bv.index.max().date()),
        })
    summary = pd.DataFrame(rows)
    print(summary.to_string(index=False))

    summary_path = os.path.join(OUTPUT_DIR, "asness_2015_india_value_longshort_comparison.csv")
    summary.to_csv(summary_path, index=False)
    print(f"\nMulti-benchmark comparison written to: {summary_path}")
    produced.append(summary_path)

    name_lookup = (tradable.drop_duplicates("accord_code")
                          .set_index("accord_code")["company_name"].to_dict())
    for label, result in [("longshort", result_ls), ("cheap_only", result_cheap)]:
        holdings_path = os.path.join(
            OUTPUT_DIR, f"asness_2015_india_value_holdings_{label}.csv")
        holdings = write_holdings_log(holdings_path, result, name_lookup=name_lookup,
                                      start=BACKTEST_START, end=BACKTEST_END)
        print(f"{label} holdings log written to: {holdings_path} "
              f"({holdings['date'].nunique()} rebalance dates, "
              f"{holdings.groupby('date').size().mean():.0f} names/rebalance on average)")
        produced.append(holdings_path)

    print("\nWriting chart set (long-short vs CHEAP-only vs benchmarks)...")
    chart_series = {"Long-short (CHEAP + EXPENSIVE)": live_ls, "CHEAP-only long leg": live_cheap}
    for disp_name, close in bench_closes.items():
        chart_series[disp_name] = close.reindex(live_ls.index).dropna()
    produced += save_backtest_charts(
        chart_series, outdir=os.path.join(OUTPUT_DIR, "charts"),
        tag="asness_2015_india_value_longshort",
        weights=result_ls.weights.loc[live_ls.index],
        weights_name="Long-short book",
        cash_weight=result_ls.cash_weight.loc[live_ls.index],
    )

    # CHEAP-only leg gets its OWN full chart set too (cumulative return,
    # drawdown, rolling vol, calendar-year returns, holdings composition) --
    # not just the shared overlay above -- vs NIFTY 500 specifically, same
    # shape as the long-short set, so the two comparators are equally
    # inspectable rather than the long-short book being the only one with
    # its own dedicated views.
    print("Writing chart set (CHEAP-only leg vs NIFTY 500)...")
    produced += save_backtest_charts(
        {"CHEAP-only long leg": live_cheap}, outdir=os.path.join(OUTPUT_DIR, "charts"),
        tag="asness_2015_india_value_cheap_only",
        benchmark=bench_closes[PRIMARY_BENCHMARK].reindex(live_cheap.index).dropna(),
        benchmark_name=PRIMARY_BENCHMARK,
        weights=result_cheap.weights.loc[live_cheap.index],
        weights_name="CHEAP-only leg",
        cash_weight=result_cheap.cash_weight.loc[live_cheap.index],
    )

    if not checkpoint("STAGE 2 OF 5 -- LONG-SHORT + CHEAP-ONLY BACKTESTS + CHARTS WRITTEN",
                      produced, auto_approve=args.auto_approve):
        return

    boot = bootstrap_sharpe_ci(ret_ls, block_size=20, n_resamples=1000, seed=0)
    print(f"\nLong-short Sharpe ratio, 90% block-bootstrap CI: [{boot.ci_low:.2f}, {boot.ci_high:.2f}] "
          f"(point estimate {boot.point_estimate:.2f}, {boot.fraction_positive:.0%} of resamples positive)")
    dsr = deflated_sharpe_from_returns(ret_ls, n_trials=1, trial_sharpe_std=0.3)
    print(f"Deflated Sharpe Ratio (n_trials=1, per this card's own n_configs_tried convention): {dsr:.2f}")

    print(f"\nFull tearsheet -- long-short book vs {PRIMARY_BENCHMARK}:")
    class _Wrapped:
        pass
    wrapped = _Wrapped()
    wrapped.value, wrapped.returns = live_ls, ret_ls
    sheet = compute_tearsheet(wrapped, bench_closes[PRIMARY_BENCHMARK].reindex(live_ls.index))
    print(render_tearsheet(sheet))

    # ---------------- Step 06 critique follow-up #1: borrow-cost sweep ----
    # Closes the "headline driven by one unswept knob" finding: is the
    # long-short book's underperformance vs CHEAP-only a borrow-cost
    # artifact, or does it survive down to a near-zero borrow rate?
    print("\n" + "=" * 78)
    print("SHORT-BORROW-COST SENSITIVITY SWEEP (card's own success_looks_like criterion)")
    print("=" * 78)
    sweep_rows = []
    for bps in (0.0, 25.0, 50.0, 100.0, 200.0):
        bt_sweep = Backtester(prices=price_window, assets=assets, spread_bps=SPREAD_BPS,
                              lag_days=LAG_DAYS, allow_cash=True, membership=eligible,
                              allow_short=True, max_gross_exposure=1.0, short_borrow_bps=bps)
        alloc_sweep = build_allocator("cross_sectional_long_short", assets, quantile=QUANTILE,
                                      weighting="equal", long_weight=LONG_WEIGHT,
                                      short_weight=SHORT_WEIGHT, min_names=MIN_NAMES)
        res_sweep = bt_sweep.run(allocator=alloc_sweep, rebalance=REBALANCE, alpha=composite,
                                 name=f"long-short, borrow={bps:.0f}bp", warmup=WARMUP_BUFFER_DAYS)
        v = to_live(res_sweep.value)
        r = v.pct_change(fill_method=None).fillna(0.0)
        r.iloc[0] = 0.0
        sweep_rows.append({
            "short_borrow_bps": bps, "cagr": _cagr(v), "vol": _ann_vol(r),
            "sharpe_vs_6pct": (_cagr(v) - 0.06) / _ann_vol(r) if _ann_vol(r) > 0 else float("nan"),
            "max_dd": _mdd(v),
        })
    sweep_df = pd.DataFrame(sweep_rows)
    print(sweep_df.to_string(index=False))
    sweep_path = os.path.join(OUTPUT_DIR, "asness_2015_india_value_longshort_borrow_sweep.csv")
    sweep_df.to_csv(sweep_path, index=False)
    print(f"Borrow-cost sweep written to: {sweep_path}")
    produced.append(sweep_path)
    if (sweep_df["cagr"] > 0.06).any():
        print("  NOTE: sign of the vs-6% comparison flips somewhere in this sweep -- the earlier "
              "negative headline is at least partly a cost-assumption finding, not purely a "
              "signal-quality one.")
    else:
        print("  The long-short book stays below the 6% hurdle across the ENTIRE sweep, including "
              "short_borrow_bps=0 -- the earlier negative headline is NOT primarily a borrow-cost "
              "artifact. Even a free short does not rescue this construction.")

    # ---------------- Step 06 critique follow-up #2: factor fingerprint ---
    # Closes the "alpha that survives against the benchmark but not against
    # the factor sleeves" check the card's own success_looks_like requires.
    print("\n" + "=" * 78)
    print("FACTOR FINGERPRINT -- CHEAP-only leg vs NIFTY500 VALUE 50 / VALUE 30 / MOMENTUM 50")
    print("=" * 78)
    factor_rets = pd.DataFrame({
        name: bench_closes[name].reindex(live_cheap.index).pct_change(fill_method=None).fillna(0.0)
        for name in ("NIFTY500 VALUE 50", "NIFTY200 VALUE 30", "NIFTY500 MOMENTUM 50")
    })
    fp = factor_fingerprint(ret_cheap, factor_rets, rf_daily=None)
    if "error" in fp:
        print(f"  factor_fingerprint unavailable: {fp['error']}")
    else:
        print(f"  alpha (ann.): {fp['alpha_ann']:.2%}   alpha t-stat (HAC): {fp['alpha_t_hac']:.2f}   "
              f"R^2: {fp['r_squared']:.2f}   n_obs: {fp['n_obs']}")
        print(f"  loadings: {fp['loadings']}")
        print(f"  {fp['interpretation']}")
        if abs(fp["alpha_t_hac"]) < 2.0:
            print("  |HAC t| < 2.0: alpha does NOT survive the factor-fingerprint check -- the "
                  "CHEAP-only leg's return is not distinguishable from a relabelled blend of "
                  "sleeves the fund already holds, at conventional significance.")

    if not checkpoint("STAGE 3 OF 5 -- BORROW-COST SWEEP + FACTOR FINGERPRINT COMPLETE",
                      produced, auto_approve=args.auto_approve):
        return

    # ---------------- THE FULL COMPOSITE-VALUE DECILE DEEP-DIVE -----------
    # CHEAP/EXPENSIVE above are decile 10 and decile 1 of this same split --
    # this runs all ten deciles (~48 names each) so the value effect's shape
    # across the WHOLE composite-score range is visible, not just its two
    # extremes -- mirrors scripts/alquist_2018_india_small_cap_backtest.py's
    # own full decile deep-dive, ranking on the composite value z-score
    # instead of market cap.
    print("\n" + "=" * 78)
    print("FULL COMPOSITE-VALUE DECILE DEEP-DIVE (10 deciles, ~48 names each)")
    print("=" * 78)
    decile_masks = compute_decile_membership(composite, eligible, n_deciles=10)
    decile_results = run_decile_backtests(
        price_window, assets, composite, decile_masks,
        spread_bps=SPREAD_BPS, lag_days=LAG_DAYS, rebalance=REBALANCE,
        warmup=WARMUP_BUFFER_DAYS, min_names=MIN_NAMES // 10)

    live_deciles = {k: to_live(r.value) for k, r in decile_results.items()}
    decile_summary = summarize_deciles(decile_results, start=BACKTEST_START, end=BACKTEST_END,
                                       cash_rate=0.06)
    # Decile 10 = highest composite z-score = CHEAPEST (matches CHEAP leg above);
    # decile 1 = lowest = MOST EXPENSIVE (matches EXPENSIVE leg above).
    print("  (decile 10 = cheapest per the composite score, decile 1 = most expensive)")
    print(decile_summary.to_string(index=False))

    bench_primary_live = bench_closes[PRIMARY_BENCHMARK].reindex(live_cheap.index)
    bench_primary_ret = bench_primary_live.pct_change(fill_method=None).fillna(0.0)
    bench_cagr = _cagr(bench_primary_live)
    bench_vol = _ann_vol(bench_primary_ret)
    bench_sharpe = (bench_cagr - 0.06) / bench_vol if bench_vol > 0 else float("nan")
    bench_row = pd.DataFrame([{
        "decile": PRIMARY_BENCHMARK, "n_obs": len(bench_primary_live),
        "start": str(bench_primary_live.index.min().date()),
        "end": str(bench_primary_live.index.max().date()),
        "cagr": bench_cagr, "vol": bench_vol, "sharpe": bench_sharpe,
        "max_dd": _mdd(bench_primary_live),
    }])

    decile_summary_csv = os.path.join(OUTPUT_DIR, "asness_2015_india_value_decile_summary.csv")
    pd.concat([decile_summary, bench_row], ignore_index=True, sort=False).to_csv(
        decile_summary_csv, index=False)
    print(f"Decile summary (CSV) written to: {decile_summary_csv}")
    produced.append(decile_summary_csv)

    live_rebalances = result_cheap.rebalances[
        (result_cheap.rebalances >= BACKTEST_START) & (result_cheap.rebalances <= BACKTEST_END)]
    decile_membership_path = os.path.join(OUTPUT_DIR, "asness_2015_india_value_decile_membership.csv")
    membership_log = write_decile_membership_log(
        decile_membership_path, decile_masks, live_rebalances, composite, name_lookup=name_lookup)
    print(f"Decile membership (the universe, stock by stock) written to: {decile_membership_path} "
          f"({membership_log['accord_code'].nunique()} distinct names across "
          f"{membership_log['date'].nunique()} rebalance dates)")
    produced.append(decile_membership_path)

    decile_chart_paths = save_decile_charts(
        live_deciles, decile_summary, outdir=os.path.join(OUTPUT_DIR, "charts"),
        tag="asness_2015_india_value_decile", benchmark=bench_primary_live,
        benchmark_name=PRIMARY_BENCHMARK, benchmark_cagr=bench_cagr, benchmark_sharpe=bench_sharpe,
    )

    decile_summary_xlsx = os.path.join(OUTPUT_DIR, "asness_2015_india_value_decile_summary.xlsx")
    write_decile_summary_workbook(
        decile_summary_xlsx, decile_summary, benchmark_rows=bench_row,
        chart_paths=decile_chart_paths,
        decile_definition_note="Decile 10 = cheapest by composite value score, decile 1 = most expensive.")
    print(f"Decile summary workbook (numbers + all {len(decile_chart_paths)} charts, "
          f"one file) written to: {decile_summary_xlsx}")
    produced.append(decile_summary_xlsx)

    if not checkpoint("STAGE 4 OF 5 -- COMPOSITE-VALUE DECILE DEEP-DIVE COMPLETE",
                      produced, auto_approve=args.auto_approve):
        return

    # ---------------- LIVE-FORMULA EXCEL RATIO WORKBOOK --------------------
    # The detailed .xlsx the repo's earlier version always produced --
    # every ratio (Sharpe, Sortino, max drawdown, Omega, hit rate, ...) as
    # a REAL Excel formula referencing the raw monthly return columns, not
    # a value pasted in. Open the file and click any Analytics cell to see
    # exactly how it's computed. One workbook for the long-short book vs
    # NIFTY 500, one for the CHEAP-only leg vs NIFTY 500.
    print("\nWriting live-formula SE Return Analytics workbooks (all ratios, as real Excel formulas)...")
    for label, live_series, ret_series, strat_name in [
        ("longshort", live_ls, ret_ls, "India Composite Value (Long-Short)"),
        ("cheap_only", live_cheap, ret_cheap, "India Composite Value (CHEAP-only long leg)"),
    ]:
        monthly_strat = (1 + ret_series).resample("ME").prod() - 1
        monthly_bench = (1 + bench_closes[PRIMARY_BENCHMARK].reindex(live_series.index)
                         .pct_change(fill_method=None).fillna(0.0)).resample("ME").prod() - 1
        common = monthly_strat.index.intersection(monthly_bench.index)
        monthly_strat, monthly_bench = monthly_strat.loc[common], monthly_bench.loc[common]

        xlsx_path = os.path.join(OUTPUT_DIR, f"asness_2015_india_value_{label}_se_return_analytics.xlsx")
        csv_path = os.path.join(OUTPUT_DIR, f"asness_2015_india_value_{label}_se_return_analytics.csv")
        write_se_return_analytics_workbook(xlsx_path, common, monthly_strat, monthly_bench,
                                           strategy_name=strat_name, benchmark_name=PRIMARY_BENCHMARK)
        write_se_return_analytics_csv(csv_path, common, monthly_strat, monthly_bench,
                                      strategy_name=strat_name, benchmark_name=PRIMARY_BENCHMARK)
        print(f"  {label}: {xlsx_path}")
        print(f"  {label}: {csv_path}")
        produced += [xlsx_path, csv_path]

    checkpoint("STAGE 5 OF 5 -- ALL OUTPUTS WRITTEN", produced, auto_approve=args.auto_approve)


if __name__ == "__main__":
    main()
