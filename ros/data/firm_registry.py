"""What this fund actually holds, with provenance. Edited by the data owner, not
by a researcher chasing a result.

Honesty here is the whole point of Step 03: an over-generous registry converts a
fail-fast into three wasted days and a result nobody can defend.

Three files back every capability here (ros/data/sources.py): the Ace Equity price
file, the NIFTY 500 holdings workbook and the NSE index workbook. This module reads
none of them -- Gate A must run without market data -- so the coverage dates below
come from the cached provenance when a cache exists and from constants otherwise.
"""
from __future__ import annotations

import glob
import json
import os

from ros.data import sources
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
PARTIAL_FIELDS_CAVEAT = (
    "Source workbook also carries Open/High/Low/PE/PB alongside Close for this "
     "index, but only Close spans the full history -- Open/High/Low and PE/PB "
     "are populated for a recent window only. The registry (and the engine) uses "
     "Close exclusively; treat the other fields as informational, not backtestable."
)
ACE_LICENCE = "Ace Equity (Accord Fintech) daily price file, fund subscription -- internal research use"
ACE_PRICE_CAVEATS = [
    ("Price returns only: the file carries no dividends. Absolute returns understate total return; "
     "say so in every report."),
    ("Adjusted OHLC are Ace's back-adjusted series (splits, bonuses, other corporate actions); unadjusted "
     "OHLC are the prices actually traded. Signals and returns use the adjusted close; fills quoted to a human "
     "cite the unadjusted close of the day."),
    ("Keyed by Accord Code in the file; ISIN comes from the holdings workbook's security master. Ace codes "
     "with no ISIN there (about 700, mostly delisted before the master was exported) are in the file but "
     "cannot be joined to index membership and are left out of ISIN-keyed panels (ace.unmapped_report())."),
    "Market cap is TOTAL, not free float: it overstates investable size and flatters capacity.",
]
MEMBERSHIP_CAVEATS = [
    ("Quarterly snapshots (end-March/June/September/December, from 2012-03-31). A name is a member from the "
     "snapshot that first lists it until the first snapshot that does not; NSE's exact effective date inside "
     "a quarter is not represented, and the intermediate quarter-ends normally repeat the semi-annual review."),
    ("Members whose Bloomberg id resolved to no ISIN (delisted or merged before the security master was "
     "exported) are left out: 40 of ~500 names in 2012, 20 in 2016, under 5 after 2019, 0 by 2026. This is "
     "survivorship bias at the margin and every result must carry the counts (nifty500.snapshot_summary())."),
    "Three truncated pulls (2017-09-30, 2018-06-30, 2018-09-30) are skipped; the previous list carries forward.",
    ("After the last snapshot the list is carried forward. nifty500.staleness(end_date) reports whether an NSE "
     "review has happened since; post-review lists go in data/raw/nifty500_updates/YYYY-MM-DD.csv."),
]
SUBINDEX_CAVEAT = (
    "Sub-index flags are read off the same quarterly snapshots. Before 2016 the Midcap 150 / Smallcap 250 "
     "flags in the file undercount (107-125 and 141-178 names instead of 150 and 250): treat sub-index "
     "membership before 2016-06-30 as incomplete."
)

# Factor sleeves, from the 'Factor Indices' sheet.
_FACTOR_INDICES = {
    "NIFTY ALPHA 50": "2003-12-31",
    "NIFTY500 MOMENTUM 50": "2005-04-01",
    "NIFTY500 MULTIFACTOR MQVLV 50": "2005-04-01",
    "NIFTY500 QUALITY 50": "2005-04-01",
    "NIFTY500 VALUE 50": "2005-04-01",
    "NIFTY500 LOW VOLATILITY 50": "2005-04-01",
    "NIFTY HIGH BETA 50": "2012-11-30",
    "NIFTY200 VALUE 30": "2005-04-01",
    "NIFTY200 MOMENTUM 30": "2005-04-01",
    "NIFTY200 Quality 30": "2015-12-31",
}

# Broad-market and cap-segment indices, from the 'Broad Market' sheet. Index levels
# only; constituent prices come from the Ace file and membership from the holdings
# workbook (both registered below).
_BROAD_MARKET_INDICES = {
    "NIFTY 50": "1996-01-01",
    "NIFTY 100": "2003-01-01",
    "NIFTY 200": "2005-01-03",
    "NIFTY 500": "1996-01-01",
    "NIFTY MIDCAP 100": "2003-01-01",
    "NIFTY MIDCAP 150": "2005-04-01",
    "NIFTY SMALLCAP 100": "2004-01-01",
    "NIFTY SMALLCAP 250": "2005-04-01",
    "NIFTY MIDSMALLCAP 400": "2005-04-01",
    "NIFTY MICROCAP 250": "2005-04-01",
}

_WORKBOOK = "data/raw/NSE_Broad_Factor_Indices_Historical_Data.xlsx"
_END = "2026-09-18"                       # last NIFTY 500 close in the index workbook
_ACE_START, _ACE_END_FALLBACK = "2000-01-03", "2026-10-26"
_N500_START, _N500_END_FALLBACK = "2012-03-31", "2026-05-31"

# The universe catalogue (ros/data/universes.py) names instruments two ways: the recorded translation pairs say
# `nifty500_constituent_prices`, the universe entries slug their own name (`nifty_500_constituent_prices`).
# Both spellings are registered for every index the two files can serve, so either path resolves.
_SERVED_INDEXES = {
    "NIFTY 500": ("nifty500", "nifty_500"),
    "NIFTY 50": ("nifty50", "nifty_50"),
    "NIFTY NEXT 50": ("nifty_next50", "nifty_next_50"),
    "NIFTY 100": ("nifty100", "nifty_100"),
    "NIFTY MIDCAP 150": ("nifty_midcap150", "nifty_midcap_150"),
    "NIFTY SMALLCAP 250": ("nifty_smallcap250", "nifty_smallcap_250"),
    "NIFTY LARGEMIDCAP 250": ("nifty_largemidcap250", "nifty_largemidcap_250"),
    "NIFTY MIDSMALLCAP 400": ("nifty_midsmallcap400", "nifty_midsmallcap_400"),
}
_CONSTITUENT_PRICE_NAMES = [f"{stem}_constituent_prices" for stems in _SERVED_INDEXES.values() for stem in stems]
_FREE_FLOAT_NAMES = [f"{stem}_free_float_marketcap" for stems in _SERVED_INDEXES.values() for stem in stems]
_MEMBERSHIP_NAMES = {f"{stem}_membership_history": index for index, stems in _SERVED_INDEXES.items() for stem in stems}


def _ace_end() -> str:
    """Last Ace date from the cached provenance if a cache exists; never parses the CSV here."""
    try:
        hits = sorted(glob.glob(os.path.join(sources.PROCESSED_DIR, "ace", "prices_*.json")), key=os.path.getmtime)
        if hits:
            with open(hits[-1], encoding="utf-8") as fh:
                return json.load(fh)["last_date"]
    except (OSError, ValueError, KeyError):
        pass
    return _ACE_END_FALLBACK


def _n500_end() -> str:
    """Last snapshot date: the newest update CSV if any, else the workbook's last snapshot (constant)."""
    ups = sorted(glob.glob(os.path.join(sources.NIFTY500_UPDATES_DIR, "*.csv")))
    return os.path.basename(ups[-1])[:10] if ups else _N500_END_FALLBACK


def build_firm_registry() -> DataRegistry:
    """Everything the three files hold, as capabilities Step 03 can bind a card to."""
    reg = DataRegistry()

    for name, start in _FACTOR_INDICES.items():
        reg.add(DataCapability(
            name=name, kind="price", frequency="daily",
            start=start, end=_END,
            pit_status="backfilled",
            licence="NSE Indices (internal use)",
            coverage_note=f"daily close, from {_WORKBOOK}; no volume, no "
                           f"constituents, no dividends",
            caveats=[NSE_BACKFILL_CAVEAT, PRICE_RETURN_CAVEAT,
                     NOT_INVESTABLE_CAVEAT, PARTIAL_FIELDS_CAVEAT],
        ))

    for name, start in _BROAD_MARKET_INDICES.items():
        reg.add(DataCapability(
            name=name, kind="price", frequency="daily",
            start=start, end=_END,
            pit_status="backfilled",
            licence="NSE Indices (internal use)",
            coverage_note=f"daily close, from {_WORKBOOK}; index level -- constituent prices are "
                           f"ACE_EQUITY_STOCK_PRICES and membership is *_membership_history",
            caveats=[PRICE_RETURN_CAVEAT, NOT_INVESTABLE_CAVEAT,
                     PARTIAL_FIELDS_CAVEAT],
        ))

    ace_end = _ace_end()
    reg.add(DataCapability(
        name="ACE_EQUITY_STOCK_PRICES", kind="price", frequency="daily",
        start=_ACE_START, end=ace_end, pit_status="true_pit", licence=ACE_LICENCE,
        is_proxy_for=_FREE_FLOAT_NAMES,
        coverage_note="every listed Indian company, ~4,500 securities, daily adjusted and unadjusted OHLC, "
                      "market cap, volume, traded value and number of trades. Loader ros.data.ace: "
                      "wide('close') is dates x ISIN. A proxy, not a source, for FREE-FLOAT market cap.",
        caveats=ACE_PRICE_CAVEATS,
    ))
    for name in _CONSTITUENT_PRICE_NAMES:
        reg.add(DataCapability(
            name=name, kind="price", frequency="daily", start=_N500_START, end=ace_end,
            pit_status="true_pit", licence=ACE_LICENCE,
            coverage_note="ACE_EQUITY_STOCK_PRICES joined on ISIN to the matching *_membership_history: "
                          "every member has a price from 2013 on (checked 2026-10-30, 979 of 979 ISINs)",
            caveats=ACE_PRICE_CAVEATS[:1] + MEMBERSHIP_CAVEATS[1:2],
        ))
    reg.add(DataCapability(
        name="ACE_EQUITY_TRADED_VALUE", kind="volume", frequency="daily",
        start=_ACE_START, end=ace_end, pit_status="true_pit", licence=ACE_LICENCE,
        coverage_note="daily shares traded (thousands), traded value (Rs crore) and number of trades per "
                      "security, from the same file; the liquidity floor and ADV inputs",
        caveats=["Exchange-aggregate turnover as Ace reports it; no bid-ask or depth."],
    ))
    reg.add(DataCapability(
        name="ACE_EQUITY_DAILY_VALUATION", kind="fundamental", frequency="daily",
        start=_ACE_START, end=ace_end, pit_status="restated", licence=ACE_LICENCE,
        coverage_note="daily PE, price/book, EV/EBITDA and market-cap/sales, standalone and consolidated, "
                      "as Ace computes them from the financials it held for that day",
        caveats=[
            ("Ratios built from financial statements whose first-reported values and announcement dates are not "
             "in the file: treat as restated history, usable for mechanism work, not for a live claim."),
            "No balance-sheet, cash-flow or shareholding lines; a signal that needs them is a data request.",
        ],
    ))

    n500_end = _n500_end()
    for name, index in _MEMBERSHIP_NAMES.items():
        reg.add(DataCapability(
            name=name, kind="membership", frequency="quarterly",
            start=_N500_START, end=n500_end, pit_status="true_pit",
            licence="NSE 500 constituents via Bloomberg (fund terminal), fund workbook -- internal research use",
            coverage_note=f"{index} membership from the NIFTY 500 holdings workbook (ros.data.nifty500, "
                          f"index='{index}'): members_on(d), membership_panel(dates, columns=isins)",
            caveats=MEMBERSHIP_CAVEATS + ([SUBINDEX_CAVEAT] if index != "NIFTY 500" else []),
        ))

    # A DECLARED proxy. It appears in every feasibility report as a proxy, and every
    # result that depends on it is reported under a rate sweep.
    reg.add(DataCapability(
        name="CASH_PROXY_CONSTANT_6PCT", kind="risk_free_rate", frequency="daily",
        start="2003-09-30", end=_END,
        pit_status="backfilled",
        licence="internal assumption",
        is_proxy_for=["india_cash_rate"],
        coverage_note="constant 6% annualised accrual",
        caveats=[
            ("NOT a real series. A constant rate is wrong in level and wrong in shape: "
             "it cannot capture the 2009 or 2020 easing cycles, which is exactly when a "
             "de-risking strategy parks in cash. Treat every cash-holding result as "
             "provisional until a real MIBOR/T-bill series is procured."),
        ],
    ))
    return reg
