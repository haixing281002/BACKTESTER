"""Pipeline driver: card in, governed verdict out.

Runs steps 01-08 for ANY card. Nothing in this module knows about any particular
paper: strategy construction is driven entirely by the card's template name and
params, and benchmarks by its benchmark_templates list.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from ros.cards.schema import StrategyCard
from ros.data.loaders import synthetic_cash_series
from ros.data.snapshot import Snapshot
from ros.engine.backtest import Backtester, BacktestResult
from ros.engine.prepare import build_signal_inputs, strategic_vector
from ros.engine.templates import build_allocator


def _resolve_params(params: Dict[str, Any], assets: List[str]) -> Dict[str, Any]:
    """Expand card shorthands ('equal') into concrete allocator arguments."""
    out = dict(params or {})
    for key in ("weights", "strategic_weights"):
        if key in out:
            vec = strategic_vector(out[key], assets)
            out[key] = {a: float(w) for a, w in zip(assets, vec)}
    # these are consumed by build_signal_inputs, not by the allocator
    for k in ("alpha_halflife", "alpha_scale", "alpha_source",
              "alpha_window", "alpha_skip"):
        out.pop(k, None)
    return out


def buy_and_hold(prices: pd.Series, name: str) -> BacktestResult:
    """Reference series for an asset the fund could simply hold instead.

    Zero turnover, zero cost, no cash. This is the honest 'do nothing' comparator
    and it is frequently the winner.
    """
    v = (prices.dropna() / prices.dropna().iloc[0]).rename(name)
    idx = v.index
    return BacktestResult(
        name=name, value=v,
        weights=pd.DataFrame(1.0, index=idx, columns=[name]),
        returns=v.pct_change().fillna(0.0),
        turnover=pd.Series(0.0, index=idx),
        costs=pd.Series(0.0, index=idx),
        cash_weight=pd.Series(0.0, index=idx),
        rebalances=pd.DatetimeIndex([]),
        meta={"template": "buy_and_hold", "params": {}, "rebalance": "none"})


@dataclass
class RunSet:
    """Everything one card produced: the strategy, its variants, its benchmarks."""
    primary: BacktestResult
    mandate: Optional[BacktestResult]
    benchmarks: List[BacktestResult] = field(default_factory=list)
    references: List[BacktestResult] = field(default_factory=list)
    inputs: Dict[str, Any] = field(default_factory=dict)
    n_configs_run: int = 0

    def all_results(self) -> List[BacktestResult]:
        out = [self.primary]
        if self.mandate is not None:
            out.append(self.mandate)
        return out + self.benchmarks + self.references

    def by_name(self, name: str) -> Optional[BacktestResult]:
        return next((r for r in self.all_results() if r.name == name), None)


def execute_card(
    card: StrategyCard,
    snapshot: Snapshot,
    cash_rate: float = 0.06,
    reference_assets: Optional[List[str]] = None,
    spread_bps_override: Optional[float] = None,
    lag_override: Optional[int] = None,
    warmup_days: Optional[int] = None,
) -> RunSet:
    """Step 05 -- build and execute every portfolio the card defines."""
    assets = list(card.universe.assets)
    prices = snapshot.frame
    spread = spread_bps_override if spread_bps_override is not None else card.costs.spread_bps
    lag = lag_override if lag_override is not None else card.signal.lag_days
    lookback = card.signal.lookback_days or 21

    rf = synthetic_cash_series(prices.index, cash_rate)

    sp = card.signal.params or {}
    inputs = build_signal_inputs(
        prices=prices, assets=assets, lookback=lookback,
        strategic_weights=sp.get("strategic_weights", sp.get("weights", "equal")),
        alpha_halflife=sp.get("alpha_halflife"),
        alpha_scale=sp.get("alpha_scale", 21),
        alpha_source=sp.get("alpha_source", "ewma"),
        alpha_window=sp.get("alpha_window"),
        alpha_skip=sp.get("alpha_skip", 0),
    )
    warm = warmup_days if warmup_days is not None else lookback + 5

    def make_engine(allow_cash: bool, spread_bps: float, lag_days: int) -> Backtester:
        return Backtester(prices=prices, assets=assets, rf_daily=rf,
                          spread_bps=spread_bps, lag_days=lag_days, allow_cash=allow_cash)

    def run_one(template: str, params: Dict[str, Any], name: str, rebalance: str,
                allow_cash: bool, spread_bps: float = None, lag_days: int = None) -> BacktestResult:
        alloc = build_allocator(template, assets, **_resolve_params(params, assets))
        bt = make_engine(allow_cash,
                         spread if spread_bps is None else spread_bps,
                         lag if lag_days is None else lag_days)
        return bt.run(
            allocator=alloc, rebalance=rebalance,
            sigma_bench=inputs["sigma_bench"],
            alpha=inputs["alpha"],
            cov=inputs["cov"], cov_cols=inputs["cov_cols"],
            name=name, warmup=warm)

    n_run = 0

    primary = run_one(card.signal.template, card.signal.params,
                      name=card.signal.name or card.signal.template,
                      rebalance=card.portfolio.rebalance,
                      allow_cash=card.portfolio.allow_cash)
    n_run += 1

    mandate = None
    if (card.portfolio.mandate_allow_cash is not None
            and card.portfolio.mandate_allow_cash != card.portfolio.allow_cash):
        mandate = run_one(card.signal.template, card.signal.params,
                          name=(card.signal.name or card.signal.template) + " [mandate: fully invested]",
                          rebalance=card.portfolio.rebalance,
                          allow_cash=card.portfolio.mandate_allow_cash)
        n_run += 1

    benchmarks: List[BacktestResult] = []
    for spec in card.benchmark_templates:
        benchmarks.append(run_one(
            spec["template"], spec.get("params", {}), name=spec["name"],
            rebalance=spec.get("rebalance", card.portfolio.rebalance),
            allow_cash=spec.get("allow_cash", card.portfolio.allow_cash)))
        n_run += 1

    references = [buy_and_hold(prices[a], a)
                  for a in (reference_assets or []) if a in prices.columns]

    return RunSet(primary=primary, mandate=mandate, benchmarks=benchmarks,
                  references=references,
                  inputs={**inputs, "rf": rf, "spread_bps": spread, "lag_days": lag,
                          "lookback": lookback, "warmup": warm,
                          "run_one": run_one, "cash_rate": cash_rate},
                  n_configs_run=n_run)


def align_runs(runset: RunSet, start: Optional[pd.Timestamp] = None) -> RunSet:
    """Truncate every result to a COMMON start date and rebase NAV to 1.0.

    Without this the comparison is rigged. A momentum-alpha strategy cannot
    rebalance until its 252-day EWMA is defined, while an equal-weight benchmark
    trades from day one. Left unaligned, the strategy carries ~250 days of flat,
    zero-return NAV that depresses its CAGR and its volatility, and the benchmark
    silently banks a year of returns the strategy never had the chance to earn.

    The common start is the LAST first-rebalance across all dynamic runs.
    """
    firsts = [r.rebalances[0] for r in runset.all_results() if len(r.rebalances) > 0]
    if start is None:
        if not firsts:
            return runset
        start = max(firsts)

    def cut(r: BacktestResult) -> BacktestResult:
        v = r.value.loc[start:]
        if v.empty or v.iloc[0] == 0:
            return r
        v = (v / v.iloc[0]).rename(r.name)
        return BacktestResult(
            name=r.name, value=v,
            weights=r.weights.loc[start:],
            returns=v.pct_change().fillna(0.0),
            turnover=r.turnover.loc[start:],
            costs=r.costs.loc[start:],
            cash_weight=r.cash_weight.loc[start:],
            rebalances=pd.DatetimeIndex([d for d in r.rebalances if d >= start]),
            meta={**r.meta, "aligned_start": str(pd.Timestamp(start).date())})

    return RunSet(
        primary=cut(runset.primary),
        mandate=cut(runset.mandate) if runset.mandate is not None else None,
        benchmarks=[cut(b) for b in runset.benchmarks],
        references=[cut(x) for x in runset.references],
        inputs={**runset.inputs, "aligned_start": start},
        n_configs_run=runset.n_configs_run)
