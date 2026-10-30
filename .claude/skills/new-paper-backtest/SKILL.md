---
name: new-paper-backtest
description: "Scaffold a new individual-stock backtest script for a paper, loading prices from the Ace Equity file (ros/data/ace.py) and point-in-time NIFTY 500 membership from the holdings workbook (ros/data/nifty500.py). Use this when a Strategy Card's mechanism needs individual-stock ranking rather than the NSE index-sleeve workbook -- ros/runner.py's execute_card() cannot run this path yet (it's coupled to the index workbook loader), so a dedicated scripts/<slug>_india_backtest.py is still the correct, documented way to execute such a card's Step 05."
---

# New paper -> individual-stock backtest script

## The data (changed 2026-10-30)

Three files, nothing else, named in `ros/data/sources.py`:

```python
from ros.data import ace, nifty500
from ros.data.sources import NSE_INDEX_WORKBOOK
from universal_backtester.data import load_banner_workbook

close = ace.wide("close", start=START)                 # dates x ISIN, adjusted close (price return)
extra = ace.panel(["mcap_cr", "value_cr"], start=START)  # same grid, other fields
cal = ace.trading_calendar()                           # the NSE calendar as the file saw it
members = nifty500.membership_panel(close.index, columns=close.columns)   # dates x ISIN booleans
bench, _ = load_banner_workbook(NSE_INDEX_WORKBOOK, sheet="Broad Market")  # NIFTY 500 level
stale = nifty500.staleness(close.index.max())          # report .message when ["stale"] is True
```

Pass `membership=members` to the `Backtester`; never a survivor-only price
frame. Key everything on ISIN. `ace.security_master()` turns an ISIN back
into an NSE symbol and company name for the holdings and trades files.

## Why this exists as its own skill, not just "write a script"

`execute_card()` (`ros/runner.py`), the pipeline's generic Step 05 driver,
only understands the NSE index workbook (`load_banner_workbook`) and a card's
`universe.assets` as a short list of index sleeve names. It has no concept of
a point-in-time, membership-bearing individual-stock panel. Every card whose
mechanism ranks and trades individual stocks therefore needs its own
`scripts/<slug>_india_backtest.py`. This is acknowledged technical debt, not a
style choice, and it is why the stock-level scripts look structurally
identical. Use this skill to scaffold the next one consistently instead of
copy-pasting the previous script and hand-editing it.

## The shape every one of these scripts follows

1. **Module docstring**: which card this executes, what's DIFFERENT about
   this mechanism (the ranking signal, rebalance cadence, any simplification
   from the card's own `backtest_plan` — recorded explicitly, never silently
   taken), and the exact data lines above.
2. **Imports + `--auto-approve` argparse flag** (see the
   `pipeline-stage-checkpoint` skill — every script needs this).
3. **No path constants of your own.** Paths come from `ros.data.sources`; the
   loaders find the files. Record `ace.provenance()["source_sha256"]` and
   `nifty500.provenance()["last_snapshot"]` in the run manifest
   (`ros.data.lineage.write_run_manifest`).
4. **`main()`**, with a `produced: list = []` tracker from the top:
   - Load the price panel(s) and the membership panel as above. Restrict the
     grid to `cal` (the file's dates) and to the card's window.
   - Build the point-in-time signal (whatever the card's mechanism ranks on)
     from trailing data only; shift by `1 + lag_days`.
   - **Checkpoint 1**: data loaded, signal built, staleness reported.
   - Run the backtest(s) via `universal_backtester.engine.Backtester` +
     `build_allocator(...)` (or `ros/engine` for a long-only card). Use
     `allow_short=True` ONLY if the card's own `is_long_short: true` requires
     it, and only through `universal_backtester`, never `ros/engine`.
   - Write daily_returns.csv, holdings.csv, trades.csv (with isin,
     signal_date, execution_date, price_date, price, price_basis),
     selection.csv and comparators.csv as the Lightyear contract asks.
   - **Checkpoint 2**: backtest(s) + hand-off files written.
   - If the mechanism is a cross-sectional sort, run the decile deep-dive
     (`compute_decile_membership`, `run_decile_backtests`, `summarize_deciles`,
     `write_decile_membership_log`, `save_decile_charts`, then
     `write_decile_summary_workbook(..., decile_definition_note=...)` — the
     note is REQUIRED and must describe what decile 1 vs. 10 means for THIS
     mechanism).
   - **Final checkpoint**: all outputs written, run manifest written.

## Non-negotiables carried over from CLAUDE.md, not optional in the scaffold

- Key on ISIN, never on NSE symbol or company name — symbols get reused and
  renamed across corporate actions.
- A cross-section needs `membership=` passed to the `Backtester` — never a
  survivor-only price file. Names that leave the index are sold at cost on
  the first date the exit was observable.
- `lag_days >= 1` always; close signals trade the next session.
- Costs come from the card; report gross AND net. Never copy a paper's cost
  assumption.
- Returns are price returns (no dividends in the Ace file): say so in the
  docstring and the notes.
- The calendar is `ace.trading_calendar()`, never `pd.bdate_range`.
- If the card is long-short (`is_long_short: true`), both legs stay live and
  are investable — run them through `allow_short=True`, never `ros/engine`.
- Every stage gets a `checkpoint()` call (see `pipeline-stage-checkpoint`).
