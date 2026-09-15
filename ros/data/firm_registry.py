"""What this fund actually holds, with provenance. Edited by the data owner, not
by a researcher chasing a result.

Honesty here is the whole point of Step 03: an over-generous registry converts a
fail-fast into three wasted days and a result nobody can defend.
"""
from __future__ import annotations

from ros.data.registry import DataCapability, DataRegistry

NSE_BACKFILL_CAVEAT = (
    "NSE factor index: history backfilled to a 2005 base date, but the index was "
    "launched and its methodology fixed years later. Sleeve construction rules were "
    "chosen with knowledge of this history -- selection bias is built into the series."
)
PRICE_RETURN_CAVEAT = (
    "Price-return index: excludes dividends (~1.3-1.5% p.a. for Indian large/mid caps). "
    "Absolute returns understate; any equity-vs-cash comparison is biased against equity."
)
NOT_INVESTABLE_CAVEAT = (
    "An index is not a portfolio: no replication tracking error, no rebalance impact, "
    "no sleeve-level turnover cost is charged inside the index level."
)

_FACTOR_INDICES = [
    "NIFTY ALPHA 50", "NIFTY500 MOMENTUM 50", "NIFTY500 MULTIFACTOR MQVLV 50",
    "NIFTY500 QUALITY 50", "NIFTY500 VALUE 50", "NIFTY500 LOW VOLATILITY 50",
    "NIFTY HIGH BETA 50",
]


def build_firm_registry() -> DataRegistry:
    reg = DataRegistry()

    for name in _FACTOR_INDICES:
        reg.add(DataCapability(
            name=name, kind="price", frequency="daily",
            start="2005-04-01" if name != "NIFTY ALPHA 50" else "2003-12-31",
            end="2026-06-11",
            pit_status="backfilled",
            licence="NSE Indices (internal use)",
            coverage_note="daily close only; no volume, no constituents, no dividends",
            caveats=[NSE_BACKFILL_CAVEAT, PRICE_RETURN_CAVEAT, NOT_INVESTABLE_CAVEAT],
        ))
    reg.get("NIFTY HIGH BETA 50").start = "2012-11-30"

    reg.add(DataCapability(
        name="NIFTY 500", kind="price", frequency="daily",
        start="2003-09-30", end="2026-05-29",
        pit_status="backfilled",
        licence="NSE Indices (internal use)",
        coverage_note="fund benchmark; daily close only",
        caveats=[PRICE_RETURN_CAVEAT,
                 "Benchmark series ends 2026-05-29, nine trading days before the "
                 "factor sleeves. Comparisons are truncated to the common window."],
    ))

    # A DECLARED proxy. It appears in every feasibility report as a proxy, and every
    # result that depends on it is reported under a rate sweep.
    reg.add(DataCapability(
        name="CASH_PROXY_CONSTANT_6PCT", kind="risk_free_rate", frequency="daily",
        start="2003-09-30", end="2026-06-11",
        pit_status="backfilled",
        licence="internal assumption",
        is_proxy_for=["india_cash_rate"],
        coverage_note="constant 6% annualised accrual",
        caveats=[
            "NOT a real series. A constant rate is wrong in level and wrong in shape: "
            "it cannot capture the 2009 or 2020 easing cycles, which is exactly when a "
            "de-risking strategy parks in cash. Treat every cash-holding result as "
            "provisional until a real MIBOR/T-bill series is procured.",
        ],
    ))
    return reg
