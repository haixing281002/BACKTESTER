# Individual-stock data — local only, never committed

This folder holds individual-stock-level data **on your machine only**.
Gitignored (`data/raw/stocks/*`), never pushed to GitHub. See the reasoning
in the git history if you want it; the short version is GitHub hard-blocks
any file over 100MB, and this data doesn't belong in a shared repo anyway.

## The five files, verified against the real thing (2026-09-24)

Everything below was checked by actually reading these files — not
guessed. All five join on **Accord Code**, a stable internal numeric
security id from the data vendor (Accord Fintech / Ace Equity) used
consistently across every file (verified: Reliance Industries = 100325,
TCS = 132540, in the price panel's column headers AND the fundamentals
files' `Accord Code` column AND the universe file's `Accord Code` column
AND the daily OHLC+mcap file's `Accord Code` column).
**Never key anything on NSE symbol or company name** — this repo's own
rule for ISIN applies the same way here: symbols get reused, names change.

| File | Canonical name expected by the loader | Shape |
|---|---|---|
| Daily prices | `price_data_till_03aug2026.xlsx` | Wide: 1 `NDP_Date` column + 1314 security columns (headers = Accord Code), daily, 2012-01-02 → 2026-07-31. **This is the file to use for both pricing and, joined against the universe below, stock selection** — the fund's own call, see §Resolutions. |
| Daily OHLC + market cap + volume | `prices_marketcap_data_till_03082026.csv` | Long: one row per (Accord Code, date), 3,441,492 rows, 1,314 securities, daily, 2012-01-02 → 2026-07-31. Added 2026-09-24. **Confirmed by direct comparison to be the SAME panel as the wide price file above** (same 1,314 codes, same date range, `close` matches to floating-point precision, 0 mismatches over 3.44M compared cells) — it is a superset, not a different security set: full daily O/H/L (the wide file is close-only) plus the dataset's first DAILY market cap, volume and traded value. `mcap` is TOTAL, not free-float, same caveat as the monthly universe file below. |
| Valuation ratios | `valuation_ratios_all_till_2025.xlsx` | Long: one row per (Accord Code, fiscal year end, Consolidated/Standalone). PE, EV/EBIT. 1988 → 2025, 1266 companies |
| Profitability ratios | `profitability_ratios_consol_stdalon_till_march2025.xlsx` | Same shape as valuation. ROA, ROE, ROCE. Same coverage |
| Monthly universe | `Monthly_uni_new.xlsx` | 176 sheets (163 real months + some duplicated/mislabeled, see below), one per month-end (Dec 2011 → Jul 2026 nominal), each ranking that month's universe by market cap. **Use only via `get_top_n_universe()`, not the raw rows** — see §Resolutions. Its `mcap` column is monthly-only; the daily OHLC+mcap file above is the one to use where a DAILY market cap is needed (e.g. daily-rebalanced size sorts, liquidity/ADV checks). |
| Results publication dates | `w_publishing_date_data.xlsx` | Long: one row per (Accord Code, fiscal year end, C/S basis) with a **real** `YR_Result Date` — 65,853 rows, 8,536 companies, 2012–2026. Fixes finding #4 below. |

Loaders: `universal_backtester/accord_data.py` — `load_accord_price_panel()`,
`load_accord_daily_price_mcap()`, `load_accord_fundamentals()`,
`load_accord_monthly_universe()`, `load_publishing_dates()`,
`get_top_n_universe()`, `restrict_to_priced_universe()`,
`diagnose_accord_dataset()`.

## How the fund has resolved each finding (2026-09-24)

**1. The monthly universe file's raw row count alternates after mid-2023 — RESOLVED.**
Confirmed by the fund: the ~500-row months are a genuine top-500-by-`Market Rank`
export, and the ~2000+-row months are the *same* top 500 plus the rest of the
universe beneath it — both carry a correct, usable `Market Rank` column. So the
fix is not to discard months, it's to stop reading the raw row count as the
universe: **`get_top_n_universe(df, n=500)` filters every month to
`market_rank <= 500`**, recovering one consistent NIFTY 500 proxy across the
whole file. Verified against the real file: every real month now reports
exactly 500 names (occasionally 1000, where a sheet has duplicate ranks — see
finding #5).

**2. One entire sheet is mislabeled, not just alternating in size.** The tab
named `31-Jul-2023` contains, in full, the `30-Jun-2023` top-500 snapshot —
every row's own `NDP_Date` says 30 June, not 31 July. July 2023 therefore has
**no real data of its own** anywhere in this file. `load_accord_monthly_universe()`
now derives `month_end` from each sheet's own row-date *mode* rather than the
tab name, so this sheet's content correctly folds into June instead of
fabricating a distinct July snapshot — and `diagnose_accord_dataset()` flags
any such case as `block` under "sheets whose entire content is dated to a
different month than their tab name" (currently: exactly this one).

**3. Universe coverage ends ~4 months before the price data does — still open.**
The last four sheets (Apr–Jul 2026) are completely empty. Price data runs to
3 Aug 2026; treat anything past March 2026 as having no membership information
at all. No new data has closed this gap.

**4. The universe file's own column schema varies sheet to sheet — handled, not a blocker.**
135 of 176 sheets have 7 columns (adds `NDP_Close` and `NSE_symbol`); the rest
have only 5. The loader handles both — `close`/`nse_symbol` come back as
`NaN`/`None` on the shorter sheets, never fabricated.

**5. Valuation/profitability had no results-publication date — RESOLVED.**
`w_publishing_date_data.xlsx` (uploaded 2026-09-24) carries a **real**
`YR_Result Date` for ~65,800 (Accord Code, fiscal year, basis) rows. Pass its
path as `publishing_dates_path=` to `load_accord_fundamentals()` and the real
date is used as `known_date` wherever a match exists (confirmed median real
lag: **58 days** after fiscal year-end, close to but not identical to the old
75-day guess). `DEFAULT_REPORTING_LAG_DAYS` now only covers rows with no match,
or with an implausible result date in the source (negative lag, or >365 days —
both are data errors present in the raw file, ~29 and ~1277 rows respectively;
kept on the assumption rather than trusted). Every row's `known_date_source`
column says which case applied (`real_result_date` or `assumed_lag`).

**Also note (still relevant):** the price panel (1314 securities) only covers
a subset of the ~3060 distinct Accord Codes that ever appear in the universe
file. **Per the fund's own guidance, stock selection and backtesting should
draw only from the 1314-security priced set** — `restrict_to_priced_universe()`
intersects a (typically top-500-filtered) universe frame against the price
panel's own columns, dropping names that could be ranked but never priced or
traded. In practice this drops almost nothing from the top-500 proxy (1 code,
2 rows, in the real file) — the mismatch is concentrated well outside the top
500.

## The recommended join, end to end

```python
from universal_backtester.accord_data import (
    load_accord_price_panel, load_accord_monthly_universe, load_accord_fundamentals,
    get_top_n_universe, restrict_to_priced_universe,
)

price, _ = load_accord_price_panel("data/raw/stocks/price_data_till_03aug2026.xlsx")
uni, _ = load_accord_monthly_universe("data/raw/stocks/Monthly_uni_new.xlsx")
top500, _ = get_top_n_universe(uni, n=500)                       # fixes finding #1
tradable, _ = restrict_to_priced_universe(top500, price.columns)  # only what's priceable

fund, fund_prov = load_accord_fundamentals(
    "data/raw/stocks/valuation_ratios_all_till_2025.xlsx",
    publishing_dates_path="data/raw/stocks/w_publishing_date_data.xlsx",  # fixes finding #5
)
```

`tradable` is a monthly, point-in-time, NIFTY-500-proxy universe restricted to
names that can actually be priced — this is the frame a Stage 02 card's
`selection` section should be built against.

## Run the diagnostic yourself

```python
from universal_backtester.accord_data import diagnose_accord_dataset
print(diagnose_accord_dataset(
    "data/raw/stocks/price_data_till_03aug2026.xlsx",
    "data/raw/stocks/Monthly_uni_new.xlsx",
).to_string())
```

## Resolved: the fifth CSV

The CSV mentioned alongside the original four files arrived 2026-09-24, via
local VS Code checkout as planned (not chat upload — it's 366MB, well past
the earlier 38MB/162MB zip limits, and 3.5x the ~100MB originally guessed).
Read before trusting it, per the discipline above: `load_accord_daily_price_mcap()`
in `universal_backtester/accord_data.py`, with an optional
`verify_against_price_panel_path=` argument that re-runs the cross-check
against `price_data_till_03aug2026.xlsx` live rather than trusting this
README. Finding: it is the same 1,314-security, 2012-2026 panel as the
existing wide price file, re-exported long-format with OHLC + the dataset's
first DAILY market cap, volume and traded value added (previously mcap only
existed monthly, in `Monthly_uni_new.xlsx`, for ranking). Not a different
security set, not new names to reconcile — a superset. Tests:
`tests/test_universal_backtester_accord_data.py::test_real_daily_ohlc_mcap_matches_the_real_price_panel_exactly`
re-runs the same check on every CI run against whatever copy of the real
files is present.
