---
name: new-paper-backtest
description: "Scaffold a new individual-stock backtest script for a paper, in the shape this repo's three real scripts already use (accord_stock_selection_backtest.py, alquist_2018_india_small_cap_backtest.py, asness_2015_india_value_longshort_backtest.py). Use this when a Strategy Card's mechanism needs individual-stock ranking on the Accord Fintech dataset rather than the NSE index-sleeve workbook -- ros/runner.py's execute_card() cannot run this path yet (it's coupled to the index workbook loader), so a dedicated scripts/<slug>_backtest.py is still the correct, documented way to execute such a card's Step 05."
---

# New paper -> individual-stock backtest script

## Why this exists as its own skill, not just "write a script"

`execute_card()` (`ros/runner.py`), the pipeline's generic Step 05 driver,
only understands the NSE factor-index workbook (`load_banner_workbook`) and a
card's `universe.assets` as a short list of index sleeve names. It has no
concept of a point-in-time, membership-bearing individual-stock panel like
the Accord Fintech dataset produces. Every card whose mechanism ranks and
trades individual stocks (not index sleeves) currently needs its own
`scripts/<slug>_backtest.py` — this is real, acknowledged technical debt (the
Alquist card's own `EXECUTION NOTE` names it), not a style choice, and it is
why three separate scripts in this repo look structurally identical.

**Until `execute_card()` gets a supplied-membership-panel extension, use this
skill to scaffold the next one consistently, instead of copy-pasting the
previous script and hand-editing it.**

## The shape every one of these scripts follows

Read `scripts/alquist_2018_india_small_cap_backtest.py` as the primary
reference (a single-mechanism, single-leg card) or
`scripts/asness_2015_india_value_longshort_backtest.py` (a long-short card
with a long-only comparison leg) if the new paper needs both. Every script
has these sections, in this order:

1. **Module docstring**: which card this executes, what's DIFFERENT about
   this mechanism vs. the reference scripts (the ranking signal, rebalance
   cadence, any simplification from the card's own `backtest_plan` — recorded
   explicitly, never silently taken).
2. **Imports + `--auto-approve` argparse flag** (see the
   `pipeline-stage-checkpoint` skill — every script needs this).
3. **Path constants**: `PRICE_PATH`, `UNIVERSE_PATH`, and whichever
   `valuation_ratios_...`/`profitability_ratios_...`/`w_publishing_date_data.xlsx`
   files this mechanism's signal actually needs (see the `data-inventory-check`
   skill before assuming which ones).
4. **`main()`**, with a `produced: list = []` tracker from the top:
   - Load the price panel + monthly universe, apply `get_top_n_universe()` +
     `restrict_to_priced_universe()` — never the raw universe file rows.
   - Build the point-in-time signal (whatever the card's mechanism ranks on),
     using `build_daily_step()`-style per-security `known_date` gating if it
     reads a fundamental — never a single fixed lag for the whole book unless
     the card says so explicitly.
   - **Checkpoint 1**: data loaded, signal built.
   - Run the backtest(s) via `universal_backtester.engine.Backtester` +
     `build_allocator(...)`. Use `allow_short=True` ONLY if the card's own
     `is_long_short: true` requires it, and only through
     `universal_backtester`, never `ros/engine`.
   - Write the multi-benchmark comparison CSV, holdings log(s)
     (`write_holdings_log`), and chart set (`save_backtest_charts`).
   - **Checkpoint 2**: backtest(s) + charts written.
   - If the mechanism is naturally a cross-sectional sort (market cap, a
     composite score, anything rankable), run the full decile deep-dive
     (`compute_decile_membership`, `run_decile_backtests`,
     `summarize_deciles`, `write_decile_membership_log`,
     `save_decile_charts`, then `write_decile_summary_workbook(...,
     chart_paths=..., decile_definition_note=...)` — the note is REQUIRED and
     must describe what decile 1 vs. 10 actually means for THIS mechanism;
     never reuse another script's wording).
   - **Checkpoint 3**: decile deep-dive complete (if applicable).
   - Write the SE Return Analytics workbook(s)
     (`write_se_return_analytics_workbook`/`_csv`) for every leg the card
     wants reported.
   - **Final checkpoint**: all outputs written.

## Non-negotiables carried over from CLAUDE.md, not optional in the scaffold

- Never key anything on NSE symbol or company name; Accord Code only.
- A cross-section needs `membership=` passed to the `Backtester` — never a
  survivor-only price file.
- `lag_days >= 1` always; this fund's real per-card choices have ranged
  1-100 depending on the signal — check the card, never assume.
- 30bp round-trip cost floor for factor sleeves unless the card states a
  different, justified figure.
- If the card is long-short, the long-short leg is a research finding, never
  reported as investable, and the long-only comparison leg is what actually
  reaches Gate B.
- Every stage gets a `checkpoint()` call (see `pipeline-stage-checkpoint`).
