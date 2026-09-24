# Individual-stock data — local only, never committed

This folder holds individual-stock-level data **on your machine only**.
Gitignored (`data/raw/stocks/*`), never pushed to GitHub. See the reasoning
in the git history if you want it; the short version is GitHub hard-blocks
any file over 100MB, and this data doesn't belong in a shared repo anyway.

## The four files, verified against the real thing (2026-09-24)

Everything below was checked by actually reading these files — not
guessed. All four join on **Accord Code**, a stable internal numeric
security id from the data vendor (Accord Fintech / Ace Equity) used
consistently across every file (verified: Reliance Industries = 100325,
TCS = 132540, in the price panel's column headers AND the fundamentals
files' `Accord Code` column AND the universe file's `Accord Code` column).
**Never key anything on NSE symbol or company name** — this repo's own
rule for ISIN applies the same way here: symbols get reused, names change.

| File | Canonical name expected by the loader | Shape |
|---|---|---|
| Daily prices | `price_data_till_03aug2026.xlsx` | Wide: 1 `NDP_Date` column + 1314 security columns (headers = Accord Code), daily, 2012-01-02 → 2026-07-31 |
| Valuation ratios | `valuation_ratios_all_till_2025.xlsx` | Long: one row per (Accord Code, fiscal year end, Consolidated/Standalone). PE, EV/EBIT. 1988 → 2025, 1266 companies |
| Profitability ratios | `profitability_ratios_consol_stdalon_till_march2025.xlsx` | Same shape as valuation. ROA, ROE, ROCE. Same coverage |
| Monthly universe | `Monthly_uni_new.xlsx` | 163 sheets, one per month-end (Dec 2011 → Jul 2026), each ranking that month's universe by market cap |

Loaders: `universal_backtester/accord_data.py` — `load_accord_price_panel()`,
`load_accord_fundamentals()`, `load_accord_monthly_universe()`,
`diagnose_accord_dataset()`.

## Four real problems, found by actually reading the data — read before trusting anything built on this

**1. The monthly universe file's breadth is not continuous after mid-2023.**
2011–2022 grows smoothly (~1450 → ~1950 names/month). From July 2023 on,
it **alternates almost every other month** between ~500 names and
~2000–2400 names:

```
Jul-2023: 2005 names   Oct-2023: 501    Nov-2023: 2114   Dec-2023: 501
Feb-2024: 2160         Mar-2024: 501    Sep-2024: 2388   Oct-2024: 501
Dec-2024: 2407         Jan-2025: 601
```

This is not real market turnover — it looks like two different extraction
processes were interleaved when the file was built. **A "top-500 by rank"
universe selected naively from this file will alternate, every other
month, between a genuine top-500 pick and a pick out of an effectively
top-500-only pool** — a real, structural bias, not something that averages
out. `diagnose_accord_dataset()` flags every such swing (`severity: block`)
before you build anything on top of this.

**2. Universe coverage ends ~4 months before the price data does.** The
last four sheets (Apr–Jul 2026) are completely empty. Price data runs to
3 Aug 2026; treat anything past March 2026 as having no membership
information at all.

**3. The universe file's own column schema varies sheet to sheet.** 135 of
163 sheets have 7 columns (adds `NDP_Close` and `NSE_symbol`); 36 sheets
have only 5. The loader handles both — `close`/`nse_symbol` come back as
`NaN`/`None` on the shorter sheets, never fabricated — but a naive
fixed-column parser will silently break or silently drop data here.

**4. Valuation/profitability have no results-publication date, only fiscal
year end** (`FR_Year End`, e.g. `202503` = FY ended March 2025). Indian
companies report annual results 1–3 months after fiscal year-end. Using
the fiscal year-end itself as "the date this number became known" is a
look-ahead bias — this repo's own `lag_days >= 1` non-negotiable is about
exactly this mistake, just months wide here instead of a day.
`load_accord_fundamentals()` adds a `known_date` column
(`fiscal_year_end + DEFAULT_REPORTING_LAG_DAYS`, currently 75 days) — a
**stated assumption**, not a fact; there is no better number in this file.

**Also note:** the price panel (1314 securities) only covers a subset of
the ~3060 distinct Accord Codes that ever appear in the universe file —
1767 universe-file codes never have a matching price series. A
cross-sectional strategy ranking further down the universe than the price
panel covers will have names it cannot actually price or trade.

## Run the diagnostic yourself

```python
from universal_backtester.accord_data import diagnose_accord_dataset
print(diagnose_accord_dataset(
    "data/raw/stocks/price_data_till_03aug2026.xlsx",
    "data/raw/stocks/Monthly_uni_new.xlsx",
).to_string())
```

## Still missing

The ~100MB CSV mentioned alongside these four files has not arrived (size
limits, most likely — same story as the earlier 38MB/162MB zips). Whatever
it turns out to hold, run it through the same discipline: read it before
trusting it, and add a real diagnostic here once its actual shape is known,
not a guessed one.
