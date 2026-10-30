# Data sources: three files, nothing else

Changed 2026-10-30. Every price, membership and index number a run uses comes
from one of the three files below, named in `ros/data/sources.py`. Nothing is
downloaded; there is no downloader in the repository. If a file is missing the
loader raises with the path it tried. Each path can be overridden with an
environment variable so a second machine points at its own copies.

| # | What | Default path | Env override | Loader |
|---|---|---|---|---|
| 1 | Ace Equity daily prices, every listed company, 2000 onward | `C:\Users\harshil.pahuja\Alpha Alternatives Holdings Private Limited\Rohit Rakhecha - Ace_Equity_Prices\prices_2000_2026_merged.csv` | `LIGHTYEAR_ACE_PRICES` | `ros/data/ace.py` |
| 2 | NIFTY 500 quarterly constituents since 2012, with sub-index split, plus the Accord/ISIN/symbol master | `C:\Users\harshil.pahuja\Desktop\20261022 Nifty 500 Historical Holdings since 2013.xlsx` | `LIGHTYEAR_NIFTY500_HOLDINGS` | `ros/data/nifty500.py` |
| 3 | NSE index levels: broad-market and factor sleeves | `data/raw/NSE_Broad_Factor_Indices_Historical_Data.xlsx` | `LIGHTYEAR_INDEX_WORKBOOK` | `ros/data/loaders.py` |

```bash
python -m ros.data.sources      # present / MISSING, size, last modified (IST)
python -m ros.data.ace          # build the Parquet cache; provenance and coverage by year
python -m ros.data.nifty500     # every snapshot: names, mapped, unmapped, complete, sleeve counts
python check_setup.py           # the same, as part of the setup check
```

## 1. Ace Equity prices (`ros/data/ace.py`)

One row per (Accord Code, trading day): about 9.5 million rows, 4,512
securities, 2000-01-03 to the file's last date, 6,669 trading days. Columns
used, with the canonical names the loader gives them:

| Ace column | Field | Meaning |
|---|---|---|
| `NDP_Open/High/Low/Close` | `open high low close` | back-adjusted for splits, bonuses and other corporate actions |
| `NDP_Un Adj Open/.../Close` | `unadj_*` | the prices actually traded that day |
| `NDP_Mcap` | `mcap_cr` | total market cap, Rs crore (not free float) |
| `NDP_Volume ('000)` | `volume_000` | shares traded, thousands |
| `NDP_Value` | `value_cr` | traded value, Rs crore |
| `NDP_No of trades` | `trades` | number of trades |
| `NDP_PE, NDP_Price_BV, NDP_EV_EBIDTA, NDP_MCAP_NS` | `pe pbv ev_ebitda mcap_sales` | standalone valuation ratios |
| `NDP_Consolidated ...` | `*_cons` | the same, consolidated |

Not in the file: dividends (returns are price returns), balance-sheet or
cash-flow lines, announcement dates, free float.

**Keys.** The file is keyed by Accord Code. The house key is the ISIN, so the
loader bridges through the security master in file 2 ("Sheet2": Accord Code,
NSE symbol, Bloomberg code, ISIN, sector). `ace.security_master()` returns the
bridge for every code in either file; about 700 Ace codes have no ISIN there
(mostly companies delisted before the master was exported) and are left out
of ISIN-keyed panels, with the count in `ace.unmapped_report()`.

**Cache.** The CSV is 2.3 GB. The first call parses it in chunks into
`data/processed/ace/prices_<signature>.parquet` (about 0.9 GB) plus a
one-row-per-security table and a provenance JSON (sha256 of the source, row
counts, dropped rows, build time in IST). Later calls read only the columns
they need. The signature is the source file's size and mtime, so a refreshed
file is re-parsed automatically. `data/processed/ace/` is gitignored.

**Cleaning.** Rows with an unparseable date (0 in the current file) and rows
with a missing or non-positive adjusted close (374) are dropped and counted.
Nothing else is altered.

**Calendar.** `ace.trading_calendar()` is the set of dates with at least 100
priced securities: the NSE calendar as traded, including Saturday special
sessions, excluding holidays. Never use weekday logic.

```python
from ros.data import ace
close = ace.wide("close", start="2013-01-01")        # dates x ISIN
p = ace.panel(["close", "mcap_cr", "value_cr"])       # aligned grid, several fields
long = ace.load_long(["close", "unadj_close"], start="2024-01-01", end="2024-03-31")
sm = ace.security_master()                             # accord_code, isin, nse_symbol, company_name, sector, ...
```

## 2. NIFTY 500 holdings workbook (`ros/data/nifty500.py`)

The "Bifurcation" sheet lists the Bloomberg members of the NSE 500 index at
every quarter-end from 2012-03-31 to 2026-05-31 (58 snapshots, about 500
rows each), with ISIN and NSE symbol looked up from the security master and
a flag for the sub-index each name sat in (Nifty 50, Next 50, 100, Midcap 150,
Smallcap 250). The workbook must have been calculated in Excel: the loader
reads the saved values, not the formulas.

**Membership rule.** A name is a member from the snapshot that first lists it
(inclusive) until the first later snapshot that does not (exclusive). Nothing
is interpolated. NSE reviews the index twice a year (effective end-March and
end-September); the intermediate quarter-ends normally repeat the list.

**What is checked.**

- Snapshots with fewer than 480 names are truncated pulls and are skipped.
  The file has three: 2017-09-30 (392 names), 2018-06-30 (353), 2018-09-30
  (299). The previous complete list carries forward across them.
- Members whose Bloomberg id has no ISIN (delisted or merged before the master
  was exported, ids like `1909315D IS Equity`) cannot be priced and are left
  out: 40 of 498 in 2012-03, 20 in 2016-06, 7 in 2018-12, 2 from 2021, 0 by
  2026. This is survivorship bias at the margin; `snapshot_summary()` carries
  the counts and every result built on the file must mention them.
- Every ISIN that was ever a member since 2013 has a price in the Ace file
  (979 of 979, checked 2026-10-30).
- Sub-index flags before 2016-06-30 undercount (Midcap 150 shows 107-125
  names, Smallcap 250 shows 141-178). Treat sub-index membership before then
  as incomplete; NIFTY 500 itself is complete.

**Staleness and updates.** The last snapshot is 2026-05-31. NSE's next review
was effective 2026-09-30, so any run that extends past that date is using the
May list for the post-review period. `nifty500.staleness(end_date)` says so
and names the fix: drop the post-review constituents into
`data/raw/nifty500_updates/2026-09-30.csv` with an `isin` column (optionally
`symbol`, `company_name`). The CSV is read as one more snapshot. A file dated
on or before the workbook's last snapshot, with a malformed ISIN, with
duplicates, or with fewer than 480 rows is refused.

```python
from ros.data import nifty500 as n
n.members_on("2024-03-28")                                   # isin, symbol, company_name
n.membership_panel(close.index, columns=close.columns)        # dates x ISIN booleans -> Backtester(membership=)
n.membership_panel(dates, index="NIFTY MIDCAP 150")
n.staleness("2026-10-24")["message"]
n.snapshot_summary()
```

## 3. NSE index workbook (`ros/data/loaders.py`)

`data/raw/NSE_Broad_Factor_Indices_Historical_Data.xlsx`, two sheets: "Broad
Market" (NIFTY 50, 100, 200, 500, Midcap 100/150, Smallcap 100/250,
MidSmallcap 400, Microcap 250) and "Factor Indices" (Alpha 50, NIFTY500
Momentum/Quality/Value/Low Volatility 50, Multifactor, High Beta, NIFTY200
Value/Momentum/Quality 30). Daily Open/High/Low/Close/PE/PB; only Close spans
the full history. Price-return indices; the factor sleeves are backfilled to
2005 from a later launch. Last NIFTY 500 close 2026-09-18. Loaders:
`ros.data.loaders.load_nse_factor_workbook` and
`universal_backtester.data.load_banner_workbook`.

## What was removed on 2026-10-30

NSE bhavcopy download and ingest, Screener.in fetch and parse, the
bhavcopy-plus-Screener master panel, the Accord Fintech panel loaders
(`universal_backtester/accord_data.py`) and the `data/raw/stocks` loader, the
NSE-rebuilt `data/raw/nifty500` membership file, and the per-paper backtest
scripts that read any of them. The local data folders (`cache/`, `scr/`,
`data/raw/master/`, `data/raw/stocks/`, `data/raw/nifty500/`) were moved out
of the repository to `C:\Users\harshil.pahuja\Lightyear_removed_data_2026-10-30\`,
not deleted. Everything is in git history before commit `6e09344`'s successor.

## Registry

`ros/data/firm_registry.py` registers what the three files hold, so Step 03
can bind a card: the index levels, `ACE_EQUITY_STOCK_PRICES` (and the
`*_constituent_prices` names the universe catalogue asks for),
`ACE_EQUITY_TRADED_VALUE`, `ACE_EQUITY_DAILY_VALUATION`, the six
`*_membership_history` names, and the declared 6% cash proxy. The registry
reads none of the files; Gate A runs without market data.
