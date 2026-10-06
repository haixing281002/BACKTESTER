---
name: data-inventory-check
description: "Before drafting or trusting a Strategy Card's data_plan, or before claiming a data file is/isn't present or what it contains, actually run the loaders and print the real answer. Use this whenever you're about to write a sentence like 'X file is not present' or 'we only have N series' or 'this data doesn't support that signal' -- this repo has a real, documented incident of a card falsely claiming a file wasn't present when it was, which caused a backtest to silently use the wrong universe."
---

# Check the data before describing it

## Why this exists

A card in this repo once stated `Monthly_uni_new.xlsx` "is not present on
this machine" and fell back to an unrestricted, unverified pool of all 1,314
Accord-priced names instead of the real, verified top-500 point-in-time
universe. The file was present the whole time. The false claim wasn't
malicious — it just wasn't checked — but it silently changed which stocks a
backtest was allowed to select from, and the error was only caught when a
human noticed the resulting stock count looked wrong. **Never describe what
data is or isn't available, or what it contains, from memory or assumption.
Run the check.**

## The checks to actually run, by question

**"Is file X present, and what's really in it?"**
```python
import os
os.path.exists(path)  # first, always
```
Then load it with the real loader (never `pd.read_excel` ad hoc — this
repo's loaders already handle the quirks: mixed sheet schemas, empty
trailing sheets, alternating coverage). For the default stock-level source
(NSE bhavcopy, via `ros/data/nse_bhavcopy_ingest.py` into a
`ros/data/master.py` master CSV):
```python
from ros.data.master import load_master
mu = load_master(master_csv_path)
print(mu.diagnosis.render())
```
For the Accord dataset (kept, not deleted, but no longer the pipeline's
default — see CLAUDE.md's "Individual-stock data changes what Stage 02 has
to decide"):
```python
from universal_backtester.accord_data import diagnose_accord_dataset
print(diagnose_accord_dataset(price_path, universe_path).to_string())
```
This surfaces survivorship risk, coverage swings, and schema variants as a
named table — read it, don't guess.

**"What series/columns does the NSE index workbook actually have?"**
```python
from universal_backtester.data import load_banner_workbook
df, prov = load_banner_workbook(
    "data/raw/NSE_Broad_Factor_Indices_Historical_Data.xlsx", sheet="Broad Market")
print(list(df.columns))          # real series names, not a guess from a README
print(df.index.min(), df.index.max())
```
Repeat for `sheet="Factor Indices"`. As of this check (2026-09-29): 20 index
series x 6 fields each (Open/High/Low/Close/PE/PB) = 120 usable columns —
richer than older repo documentation states. Don't trust a prior summary;
re-run this and compare.

**"Does this signal need a fundamental, and is its publication date real or assumed?"**
```python
from universal_backtester.accord_data import load_accord_fundamentals
fund, prov = load_accord_fundamentals(valuation_path, publishing_dates_path=pubdates_path)
print(prov["n_known_date_from_real_date"], "real vs.", prov["n_known_date_from_assumption"], "assumed")
```
If `publishing_dates_path` doesn't exist locally, say so explicitly in
whatever you're writing (card, script docstring, chat reply) — this is a
real, previously-hit discrepancy (`w_publishing_date_data.xlsx` not being
present on a given machine despite being documented as held locally), and it
weakens point-in-time gating from "real result date" to "flat assumed lag."
Never silently substitute one for the other without saying so.

**"Do we have a ticker/company name for this Accord Code?"**
```python
from universal_backtester.accord_data import build_accord_ticker_bridge
bridge, prov = build_accord_ticker_bridge(monthly_universe_df)
```
`n_months_symbol_known == 0` means genuinely unknown, not unresolved — say
that, don't invent a plausible-looking symbol.

## The rule this enforces

Every data claim in a card, a script docstring, or a chat reply should be
traceable to one of the checks above having actually been run in this
session (or a prior one, cited) — never to "the dataset probably has X" or
"this file typically contains Y." If you haven't run the check, say "I
haven't verified this — let me check" instead of asserting an answer.
