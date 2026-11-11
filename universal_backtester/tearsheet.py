# Quant AI Researcher
"""The extended tearsheet for a universal_backtester result. This module ARRANGES and PRINTS; it defines no metric.

Every number comes from ros.metrics.core.tearsheet(), the single definition the Excel workbook
(universal_backtester/excel_tearsheet.py) reproduces cell for cell. Conventions: daily returns, sample standard deviation,
252, the Sharpe hurdle from config/fund.yaml, losses as positive numbers.

The benchmark here is a PRICE index (dividends excluded), because that is the only NIFTY 500 series this repo holds. A
price index understates the benchmark by its dividend yield, roughly 1.3 to 1.5 points a year for Indian large and mid
caps, so every benchmark-relative row flatters the strategy by about that much.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ros import config
from ros.metrics import core

TRI_CAVEAT = ("Benchmark is a PRICE index (dividends excluded), not the total-return index: it understates the true benchmark by "
              "about 1.3 to 1.5 points a year, and every benchmark-relative row inherits that in the strategy's favour.")
_PCT = {"Total Return", "CAGR", "Annualized Volatility", "Positive Volatility", "Negative Volatility", "Max Drawdown",
        "Average Annual Max Drawdown", "Avg Month Ret", "Max Month Ret", "Min Month Ret", "95% VaR", "99% VaR", "95% CVaR",
        "99% CVaR", "Alpha", "Jensens Alpha (Adj Beta)", "Tracking Error"}


def compute_tearsheet_from_returns(returns: pd.Series, bench_returns: pd.Series, start, hurdle_annual: float | None = None) -> dict[str, float]:
    """core.tearsheet() for a daily return series and its benchmark. `start` is the value-100 base date."""
    h = config.hurdle_annual() if hurdle_annual is None else float(hurdle_annual)
    return core.tearsheet(returns, start, h, bench_returns)


def compute_tearsheet(result, bench_close: pd.Series, hurdle_annual: float | None = None) -> dict[str, float]:
    """`result` has .value (starting at the base date) and .returns. `bench_close` is the benchmark's price series."""
    value = result.value.dropna()
    start = value.index[0]
    r = value.pct_change().iloc[1:]
    b = bench_close.reindex(value.index).pct_change().iloc[1:]
    return compute_tearsheet_from_returns(r, b, start, hurdle_annual)


def render_tearsheet(ts: dict[str, float]) -> str:
    lines = []
    for label, v in ts.items():
        s = "--" if v is None or not np.isfinite(v) else f"{v:.2%}" if label in _PCT else f"{v:.0f}" if label.endswith("Months") else f"{v:.2f}"
        lines.append(f"  {label:<32s} {s:>10s}")
    lines.append(f"\n  {TRI_CAVEAT}")
    return "\n".join(lines)
