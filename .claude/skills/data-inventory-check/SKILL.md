---
name: data-inventory-check
description: "Before drafting or trusting a Strategy Card's data_plan, or before claiming a data file is/isn't present or what it contains, actually run the loaders and print the real answer. Use this whenever you're about to write a sentence like 'X file is not present' or 'we only have N series' or 'this data doesn't support that signal' -- this repo has a real, documented incident of a card falsely claiming a file wasn't present when it was, which caused a backtest to silently use the wrong universe."
---

# Check the data before describing it

## Why this exists

A card in this repo once stated a universe file "is not present on this
machine" and fell back to an unrestricted pool of every priced name instead of
the real, verified point-in-time universe. The file was present the whole
time. The false claim wasn't malicious — it just wasn't checked — but it
silently changed which stocks a backtest was allowed to select from, and the
error was only caught when a human noticed the stock count looked wrong.
**Never describe what data is or isn't available, or what it contains, from
memory or assumption. Run the check.**

## The three files, and nothing else

```bash
python -m ros.data.sources          # the three paths: present or MISSING, size, last modified (IST)
```

If a path says MISSING, say so in those words with the path. Do not look for
the data anywhere else; there is nowhere else.

## The checks to actually run, by question

**"What does the Ace price file cover?"**
```python
from ros.data import ace
prov = ace.provenance()            # rows, securities, first/last date, trading days, dropped rows, sha256
print(prov["first_date"], prov["last_date"], prov["securities"], prov["dropped_rows"])
print(ace.coverage_report().tail())            # per year: trading days, securities, how many carry an ISIN
print(ace.unmapped_report().head())            # Ace codes with no ISIN (cannot join to membership)
```

**"Who was in NIFTY 500 (or a sub-index) on a date, and is the list current?"**
```python
from ros.data import nifty500 as n
print(n.snapshot_summary().tail())             # per snapshot: names, mapped, unmapped, complete, sleeve counts
print(len(n.members_on("2024-03-28")))
print(n.staleness("<run end date>")["message"])  # quote this in the data map when it says stale
```

**"Is a security priced on the dates the strategy needs?"**
```python
close = ace.wide("close", start="2013-01-01")
isins = n.members_on("2013-04-18")["isin"]
print(close.loc["2013-04-18", isins].notna().sum(), "of", len(isins), "members have a close")
```

**"What series does the NSE index workbook actually have?"**
```python
from ros.data.sources import NSE_INDEX_WORKBOOK
from universal_backtester.data import load_banner_workbook
df, prov = load_banner_workbook(NSE_INDEX_WORKBOOK, sheet="Broad Market")
print(list(df.columns)); print(df.index.min(), df.index.max())
```
Repeat for `sheet="Factor Indices"`.

**"Does this signal need a fundamental?"** The Ace file carries daily PE,
P/BV, EV/EBITDA and market cap to sales (standalone and consolidated) and
market cap. It carries no balance-sheet or cash-flow lines and no announcement
dates. If the card needs those, the honest answer is "missing", recorded as a
`data_request` with `without_it`, never a stand-in from memory.

## The rule this enforces

Every data claim in a card, a script docstring, or a chat reply should be
traceable to one of the checks above having actually been run in this
session (or a prior one, cited) — never to "the dataset probably has X" or
"this file typically contains Y." If you haven't run the check, say "I
haven't verified this — let me check" instead of asserting an answer.
