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
PARTIAL_FIELDS_CAVEAT = (
    "Source workbook also carries Open/High/Low/PE/PB alongside Close for this "
    "index, but only Close spans the full history -- Open/High/Low and PE/PB "
    "are populated for a recent window only. The registry (and the engine) uses "
    "Close exclusively; treat the other fields as informational, not backtestable."
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

# Broad-market and cap-segment indices, from the 'Broad Market' sheet. These
# back several of the catalogued universes in ros/data/universes.py at the
# index level (not constituent level -- no membership history or per-name
# prices come with this workbook, so a cross-sectional sort on any of these
# universes still needs the constituent data ros/data/intake.py asks for).
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
_END = "2026-09-18"


def build_firm_registry() -> DataRegistry:
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
            coverage_note=f"daily close, from {_WORKBOOK}; index-level only -- "
                           f"no constituent prices or membership history",
            caveats=[PRICE_RETURN_CAVEAT, NOT_INVESTABLE_CAVEAT,
                     PARTIAL_FIELDS_CAVEAT],
        ))

    # Individual-stock data, local-only and gitignored (data/raw/stocks/, see
    # its README) -- vendor Accord Fintech / Ace Equity. NOT the NSE workbook
    # above: this is constituent-level, ~1,314 priced Indian names, daily
    # OHLC + market cap + volume + traded value, 2012-01-02 onward. This is
    # what a stock-level cross-sectional card (a real size, momentum or
    # quality sort, not an index-sleeve proxy) actually needs, and what the
    # note on _BROAD_MARKET_INDICES above says is missing from the NSE
    # workbook. Loaders: universal_backtester/accord_data.py. This capability
    # exists so Step 03 resolves a card that declares it, rather than a
    # correct data source showing as UNAVAILABLE just because it lives
    # outside the NSE-workbook-only registry this file used to model.
    reg.add(DataCapability(
        name="ACCORD_STOCK_LEVEL_PRICE_MCAP", kind="price", frequency="daily",
        start="2012-01-02", end="2026-07-31",
        pit_status="true_pit",
        licence="Accord Fintech / Ace Equity (internal use) -- confirm exact terms with the data vendor agreement",
        coverage_note="~1,314 priced Indian securities, daily open/high/low/close, "
                       "market cap, volume and traded value, keyed on Accord Code "
                       "(never NSE symbol or company name -- both get reused/renamed)",
        caveats=[
            "Market cap is TOTAL, not free-float. Indian promoter holdings are "
            "large, so this overstates investable size and flatters capacity "
            "the same way ros/data/master.py flags for any market-cap-only file.",
            "Not scoped to any named index (NIFTY 500, etc.) by itself -- there is "
            "no verified point-in-time index-membership field attached to this "
            "capability. A card using this must state its OWN eligibility rule "
            "(e.g. 'has a price that day' + a liquidity floor) and that rule is "
            "a proxy for investability, not a verified membership history. "
            "data/raw/stocks/Monthly_uni_new.xlsx carries a real monthly "
            "market-rank field when it is present locally, which is a closer "
            "proxy to actual index membership than this capability alone.",
            "Local-only, gitignored (data/raw/stocks/*, see its README): this "
            "capability is only actually resolvable on a machine that has the "
            "file. A clone without it must re-supply data/raw/stocks/ before "
            "any card declaring this requirement can run past Step 03.",
        ],
    ))

    # Three more Accord files, same local-only/gitignored footing as the
    # price panel above -- present on disk and already loaded by
    # universal_backtester/accord_data.py, but never registered until now
    # (found as a Step 03 gap while data-mapping
    # asness_2015_india_value_composite_longshort.yaml: the gate reported
    # these UNAVAILABLE despite the files being right there). Registered
    # under the exact requirement-name strings those cards already use.
    reg.add(DataCapability(
        name="Accord valuation ratios (Adjusted PE, EV/EBIT)", kind="fundamental",
        frequency="annual", start="1988-01-01", end="2025-03-31",
        pit_status="true_pit",
        licence="Accord Fintech / Ace Equity (internal use) -- confirm exact terms with the data vendor agreement",
        coverage_note="data/raw/stocks/valuation_ratios_all_till_2025.xlsx -- long format, one row "
                       "per (Accord Code, fiscal year end, Consolidated/Standalone basis). "
                       "Adjusted PE and EV/EBIT, 1988-2025, 1266 companies. "
                       "Loader: universal_backtester.accord_data.load_accord_fundamentals.",
        caveats=[
            "Two accounting bases per security per year (consolidated / standalone); "
            "no single 'correct' one -- a card using this must state its own preference "
            "and fallback, and record it as a judgement call, not a data property.",
            "Only two value ratios (both earnings-multiples). No book-to-market or "
            "dividend yield in this file -- a composite built from it alone is "
            "narrower than a book/earnings/cash-flow/dividend composite would be.",
            "Local-only, gitignored (data/raw/stocks/*): only resolvable on a machine "
            "that has the file.",
        ],
    ))
    reg.add(DataCapability(
        name="Accord publication dates (w_publishing_date_data.xlsx)", kind="fundamental",
        frequency="annual", start="2012-01-01", end="2026-01-01",
        pit_status="true_pit",
        licence="Accord Fintech / Ace Equity (internal use) -- confirm exact terms with the data vendor agreement",
        coverage_note="data/raw/stocks/w_publishing_date_data.xlsx -- one row per (Accord Code, "
                       "fiscal year end, C/S basis) with a real YR_Result Date, 65,853 rows, "
                       "8,536 companies. Median real lag 58 days after fiscal year end. "
                       "Loader: universal_backtester.accord_data.load_publishing_dates.",
        caveats=[
            "Not every (accord_code, fiscal_year, basis) row in the fundamentals files "
            "has a matching real date here -- unmatched rows fall back to a flat "
            "75-day assumed lag (DEFAULT_REPORTING_LAG_DAYS in accord_data.py).",
            "A small number of source rows carry an implausible result date (negative "
            "lag, or >365 days after fiscal year end) -- treated as data errors and "
            "kept on the assumed-lag fallback rather than trusted.",
            "Local-only, gitignored (data/raw/stocks/*): only resolvable on a machine "
            "that has the file.",
        ],
    ))
    reg.add(DataCapability(
        name="Monthly_uni_new.xlsx point-in-time universe", kind="membership",
        frequency="monthly", start="2011-12-01", end="2026-07-31",
        pit_status="true_pit",
        licence="Accord Fintech / Ace Equity (internal use) -- confirm exact terms with the data vendor agreement",
        coverage_note="data/raw/stocks/Monthly_uni_new.xlsx -- 176 sheets (163 real months), one "
                       "per month-end, each ranking that month's universe by market cap. Use only "
                       "via get_top_n_universe(), not the raw rows -- see the file's own README "
                       "for the alternating-coverage and mislabeled-sheet fixes it applies. "
                       "Loader: universal_backtester.accord_data.load_accord_monthly_universe.",
        caveats=[
            "market_rank is by TOTAL market cap, not free float -- same bias every "
            "other total-cap-based Accord field in this registry carries.",
            "Universe coverage ends ~4 months before the price panel does (last real "
            "snapshot in this file is materially before ACCORD_STOCK_LEVEL_PRICE_MCAP's "
            "own end date) -- treat any date past that gap as having no membership "
            "information at all.",
            "The file's own market-rank field is an Accord product, not an "
            "independently-published index membership list -- 'point-in-time' here "
            "means verified against the file's own internal irregularities, not "
            "cross-checked against NSE's own published constituent history.",
            "Local-only, gitignored (data/raw/stocks/*): only resolvable on a machine "
            "that has the file.",
        ],
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
            "NOT a real series. A constant rate is wrong in level and wrong in shape: "
            "it cannot capture the 2009 or 2020 easing cycles, which is exactly when a "
            "de-risking strategy parks in cash. Treat every cash-holding result as "
            "provisional until a real MIBOR/T-bill series is procured.",
        ],
    ))
    return reg
