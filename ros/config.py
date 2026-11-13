# Quant AI Researcher
"""Fund-level settings the code reads and never types: sweep grids, AUM, the mandate and the gate's thresholds.
A run's own cost and cash rate are not here: they come only from its card."""
from __future__ import annotations

import os
from typing import Any

import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.environ.get("LIGHTYEAR_CONFIG_DIR") or os.path.join(REPO, "config")


def _load(name: str) -> dict[str, Any]:
    with open(os.path.join(CONFIG_DIR, name), encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def cost_sweep_bp() -> list[float]:
    return [float(x) for x in _load("costs.yaml")["sweep_round_trip_bp"]]


def round_trip_bp() -> float:
    """The round-trip cost a new card is drafted with (config/costs.yaml). A run charges only its card's cost."""
    return float(_load("costs.yaml")["round_trip_bp"])


def cash_rate_sweep() -> list[float]:
    return [float(x) for x in _load("fund.yaml")["cash_rate_sweep"]]


def hurdle_annual() -> float:
    """The yearly Sharpe yardstick (config/fund.yaml). Not a cash rate: idle cash earns the card's rate."""
    return float(_load("fund.yaml")["sharpe_hurdle"])


def trading_days_per_year() -> int:
    """Trading days a year (config/fund.yaml), the one annualisation factor of every daily figure: ros/metrics/core.py ANN."""
    return int(_load("fund.yaml")["trading_days_per_year"])


def site_days_per_year() -> int:
    """Days a year of the Barra reconciliation mode (config/fund.yaml): ros/metrics/core.py SITE_ANN. Not a Lightyear figure's day count."""
    return int(_load("fund.yaml")["site_days_per_year"])


def hurdle_daily() -> float:
    """One trading day of the Sharpe yardstick: (1 + annual)^(1/trading_days_per_year) - 1. Every Sharpe subtracts this."""
    return (1.0 + hurdle_annual()) ** (1.0 / trading_days_per_year()) - 1.0


def calibration() -> dict[str, Any]:
    return _load("calibration.yaml")


def fund() -> dict[str, Any]:
    return _load("fund.yaml")


def cash_rate_for(card) -> tuple[float, str]:
    """The annual cash rate and where it came from. Only the card sets it. A card naming none gets no invented rate: Sharpe
    is then simply over zero, and the page says so."""
    from ros.metrics import core
    try:
        return core.cash_rate_from_card(card), "the card"
    except core.MissingCashRate:
        return 0.0, "nowhere: the card names no rate, so Sharpe here is over zero"


def market_phases() -> list[dict[str, Any]]:
    """The operator's NIFTY 500 market phases (config/market_phases.yaml), for the Market phases table and chart only."""
    return list(_load("market_phases.yaml").get("phases") or [])


def mandate() -> dict[str, Any]:
    return _load("mandate.yaml")


def gate_thresholds() -> dict[str, Any]:
    return _load("gate_thresholds.yaml")
