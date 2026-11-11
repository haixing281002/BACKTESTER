# Quant AI Researcher
"""The Clenow run's Validation rows and table sheet names are a FIXED template: this test fails on any sheet rename or
any Validation row removal. New diagnostics may only be appended (add them to the frozen lists here on purpose)."""
import importlib.util
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
SCRIPT = os.path.join(REPO, "scripts", "oceanofpdf_com_stocks_on_the_move_andreas_clenow_india_backtest.py")

# 2026-11-11, operator's Wave 4 ruling: every Sharpe row is labelled geometric (headline) or arithmetic (bootstrap, deflated),
# over the risk-free rate (5%, config). Renamed in place, on purpose; "hurdle" became "risk-free rate" the same day.
# 2026-11-11, operator's Wave 3 ruling: "Walk-forward" renamed "Sub-period stability" (fixed rules: nothing is out of sample)
# and its row judged on excess over NIFTY 500. Renamed in place, on purpose.
FROZEN_SHEETS = ["Performance", "Appendix cost sweep", "Cash-rate sweep", "Sensitivities", "Calendar-year returns", "Sub-period stability",
                 "Sub-period CAGR", "Rebalance log", "Exits by reason", "Worst days", "Contributors", "Cap mix by year", "Gap events", "Checks",
                 "Universe coverage"]      # appended 2026-11-02

FROZEN_VALIDATION = [
    "CAGR, strategy", "CAGR, NIFTY 500 price index", "CAGR, equal-weight members (monthly)", "CAGR, NIFTY500 Momentum 50 (backfilled)",
    "CAGR, same rules without the index filter", "Volatility, strategy", "Volatility, NIFTY 500",
    "Sharpe (risk-free rate 5%), strategy", "Sharpe (risk-free rate 5%), NIFTY 500",
    "Max drawdown, strategy", "Max drawdown, NIFTY 500",
    "Drawdown in the latest index correction, strategy", "Drawdown in the latest index correction, NIFTY 500",
    "Beta to NIFTY 500", "Information ratio vs NIFTY 500",
    "Deflated Sharpe (arithmetic, risk-free rate 5%), repo default (unit variance)", "Deflated Sharpe (arithmetic, risk-free rate 5%), variance of the variants' Sharpes",
    "Two-way turnover a year (x capital)", "Breakeven round-trip cost vs NIFTY 500 (bp; beyond the sweep if blank)",
    "Names held per rebalance, mean", "Rebalances with fewer than 5 names", "Largest single weight at any rebalance",
    "Different stocks held over the run", "Top-2 stocks' share of gross gains", "Mean cash share of NAV",
    "Share of signals with buying shut by the index filter", "Median holding period (days)",
    "Top-band names removed by the gap rule, mean per signal", "Buys on days the stock closed up more than 9.5% (band proxy)",
    "Average NAV share in Smallcap 250 names",
    "Bootstrap Sharpe (arithmetic, risk-free rate 5%) 95% low", "Bootstrap Sharpe (arithmetic, risk-free rate 5%) 95% high",
    "Paired P(no arithmetic Sharpe edge, risk-free rate 5%) vs NIFTY 500", "Paired P(no arithmetic Sharpe edge, risk-free rate 5%) vs equal-weight members",
    "Paired P(no arithmetic Sharpe edge, risk-free rate 5%) vs Momentum 50", "Paired P(no arithmetic Sharpe edge, risk-free rate 5%) vs no-filter variant",
    "Worst sub-period excess CAGR over NIFTY 500", "Factor alpha a year", "Factor alpha HAC t-stat",
    "Factor alpha a year, over the risk-free rate", "Factor alpha HAC t-stat, over the risk-free rate",   # inserted 2026-11-11, Wave 4
    "Loading on NIFTY500 Momentum 50", "Loading on NIFTY500 Value 50", "Factor R-squared",
    "Alpha HAC t without the Momentum 50 sleeve", "Alpha HAC t, no-filter variant",
    "CAGR, Thursday signal / Friday fill", "CAGR, 20% gap limit", "CAGR, 120-day regression", "CAGR with cash at 0%",
    "Look-ahead and accounting checks passed", "Signals (weekly)", "Member-days with a move over the gap limit that coincide with an Ace adjustment change",
    # appended 2026-11-02 (universe v2 and the start rule)
    "Universe source (card: universe.membership_source)", "First signal and first fill", "Members at the first signal",
    "Members with an Ace close at the first signal", "Members never priced over the run (in universe, never tradable)",
]


@pytest.fixture(scope="module")
def mod():
    if not os.path.exists(SCRIPT):
        pytest.skip("Clenow script not on this machine")
    spec = importlib.util.spec_from_file_location("clenow_script_frozen", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_sheet_names_are_frozen(mod):
    titles = [t["title"] for t in mod.FIXED_TABLES]
    assert titles == FROZEN_SHEETS, f"a fixed sheet was renamed, dropped or reordered: {titles}"
    assert all(len(t) <= 28 and "  " not in t for t in titles)


def test_validation_rows_are_frozen(mod):
    labels = [r["label"] for r in mod.FIXED_VALIDATION_SPEC]
    missing = [x for x in FROZEN_VALIDATION if x not in labels]
    assert not missing, f"fixed Validation rows removed or renamed: {missing}"
    assert labels[:len(FROZEN_VALIDATION)] == FROZEN_VALIDATION, "fixed rows must keep their order; append new ones at the end"
    assert "Bootstrap Sharpe (arithmetic, risk-free rate 5%) 95% low" in labels and "Bootstrap Sharpe (arithmetic, risk-free rate 5%) 95% high" in labels   # two numbers, never one text cell


def test_sheet_title_sanitiser_collapses_spaces():
    from lightyear.workbook import _sheet_title
    assert _sheet_title("Appendix: cost sweep", set()) == "Appendix cost sweep"
