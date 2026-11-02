# Clenow on NIFTY 500: baseline -> universe v2 -> start rule

Quant AI Researcher by Harshil Pahuja

Every number below is read from the run's own files; no run was edited. Runs:

- baseline (v1, old start): `outputs/lightyear/20261030-191604-3399` (first signal 2014-01-07, first fill 2014-01-08, universe holdings_workbook (pre-field))
- (a) v2, old start: `C:/Users/HARSHI~1.PAH/AppData/Local/Temp/claude/C--Users-harshil-pahuja/1f38b5bc-b362-4137-9357-83fbec9e2af6/scratchpad/uv2/runs/a_v2_oldstart` (first signal 2014-01-07, first fill 2014-01-08, universe nifty500_members_v2)
- (b) v1, new start: `C:/Users/HARSHI~1.PAH/AppData/Local/Temp/claude/C--Users-harshil-pahuja/1f38b5bc-b362-4137-9357-83fbec9e2af6/scratchpad/uv2/runs/b_v1_newstart` (first signal 2013-12-31, first fill 2014-01-01, universe holdings_workbook)
- final (v2, new start): `outputs/lightyear/20261102-105054-0427` (first signal 2013-12-31, first fill 2014-01-01, universe nifty500_members_v2)

## Headline

| label | cagr | nifty_cagr | excess_cagr | vol | sharpe | max_dd | turnover_2way | names_mean | cash_mean | alpha_t | alpha_t_no_filter | deflated_sharpe | worst_wf_sharpe | paired_p_vs_nifty | gate_b_pass |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline (v1, old start) | 21.2% | 12.8% | 8.3% | 16.8% | 0.91 | 22.1% | 10.3 | 30.0 | 19.5% | 1.88 | 2.11 | 0.003 | -0.261 | 0.029 | 2 |
| (a) v2, old start | 20.5% | 12.8% | 7.7% | 16.8% | 0.87 | 22.3% | 10.3 | 30.0 | 19.5% | 1.70 | 2.03 | 0.002 | -0.279 | 0.046 | 2 |
| (b) v1, new start | 20.4% | 12.8% | 7.6% | 16.8% | 0.86 | 22.1% | 10.3 | 29.9 | 19.4% | 1.69 | 2.03 | 0.002 | -0.275 | 0.045 | 2 |
| final (v2, new start) | 19.8% | 12.8% | 7.0% | 16.8% | 0.83 | 22.5% | 10.3 | 29.9 | 19.4% | 1.52 | 1.94 | 0.001 | -0.291 | 0.058 | 1 |

## Decomposition

**cagr**: universe effect, old start (a - baseline) = -0.67 pts; start-rule effect, v1 (b - baseline) = -0.73 pts; universe effect, new start (final - b) = -0.63 pts; start-rule effect, v2 (final - a) = -0.70 pts; total (final - baseline) = -1.36 pts
**sharpe**: universe effect, old start (a - baseline) = -0.04; start-rule effect, v1 (b - baseline) = -0.04; universe effect, new start (final - b) = -0.04; start-rule effect, v2 (final - a) = -0.04; total (final - baseline) = -0.08
**max_dd**: universe effect, old start (a - baseline) = +0.15 pts; start-rule effect, v1 (b - baseline) = +0.01 pts; universe effect, new start (final - b) = +0.33 pts; start-rule effect, v2 (final - a) = +0.19 pts; total (final - baseline) = +0.34 pts
**excess_cagr**: universe effect, old start (a - baseline) = -0.67 pts; start-rule effect, v1 (b - baseline) = -0.73 pts; universe effect, new start (final - b) = -0.63 pts; start-rule effect, v2 (final - a) = -0.70 pts; total (final - baseline) = -1.36 pts
**turnover_2way**: universe effect, old start (a - baseline) = 0.01; start-rule effect, v1 (b - baseline) = 0.00; universe effect, new start (final - b) = 0.02; start-rule effect, v2 (final - a) = 0.02; total (final - baseline) = 0.03

## Gate B, every criterion

| criterion | baseline (v1, old start) | (a) v2, old start | (b) v1, new start | final (v2, new start) | threshold |
|---|---|---|---|---|---|
| deflated Sharpe clears selection bias | 0.00 (FAIL) | 0.00 (FAIL) | 0.00 (FAIL) | 0.00 (FAIL) | 0.95 |
| positive Sharpe in every out-of-sample window | -0.26 (FAIL) | -0.28 (FAIL) | -0.28 (FAIL) | -0.29 (FAIL) | 0.3 |
| advantage over benchmark is significant | 0.029 (PASS) | 0.046 (PASS) | 0.045 (PASS) | 0.058 (FAIL) | <=0.05 |
| differentiated from existing book | NO COMPARISON (FAIL) | NO COMPARISON (FAIL) | NO COMPARISON (FAIL) | NO COMPARISON (FAIL) | <=0.8 |
| improves the book's information ratio | NO COMPARISON (FAIL) | NO COMPARISON (FAIL) | NO COMPARISON (FAIL) | NO COMPARISON (FAIL) | >=0.05 |
| alpha survives the factor fingerprint | 1.88 (FAIL) | 1.70 (FAIL) | 1.69 (FAIL) | 1.52 (FAIL) | |t|>=2.0 |
| implementable within mandate | None (PASS) | None (PASS) | None (PASS) | None (PASS) |  |
| turnover within operational tolerance | 1030% (FAIL) | 1031% (FAIL) | 1031% (FAIL) | 1033% (FAIL) | <=400% |

## Year by year (2014 and 2017-2018 highlighted)

| year | strategy baseline | nifty baseline | strategy a | nifty a | strategy b | nifty b | strategy final | nifty final | highlight |
|---|---|---|---|---|---|---|---|---|---|
| 2014 | 71.0% | 37.6% | 72.3% | 37.6% | 69.0% | 37.6% | 66.2% | 37.6% | 2014: first year, earliest universe |
| 2015 | 3.8% | -0.7% | 2.6% | -0.7% | 3.7% | -0.7% | 3.7% | -0.7% |  |
| 2016 | 14.2% | 3.8% | 13.4% | 3.8% | 10.5% | 3.8% | 10.4% | 3.8% |  |
| 2017 | 52.1% | 35.9% | 48.2% | 35.9% | 50.3% | 35.9% | 49.8% | 35.9% | 2017-2018: Alpha Lab gap |
| 2018 | -7.0% | -3.4% | -8.3% | -3.4% | -6.2% | -3.4% | -8.5% | -3.4% | 2017-2018: Alpha Lab gap |
| 2019 | 6.0% | 7.7% | 5.1% | 7.7% | 6.8% | 7.7% | 6.5% | 7.7% |  |
| 2020 | 24.3% | 16.7% | 23.7% | 16.7% | 24.0% | 16.7% | 23.6% | 16.7% |  |
| 2021 | 72.4% | 30.2% | 73.9% | 30.2% | 69.7% | 30.2% | 70.3% | 30.2% |  |
| 2022 | 0.5% | 3.0% | -0.1% | 3.0% | 0.8% | 3.0% | -0.8% | 3.0% |  |
| 2023 | 45.2% | 25.8% | 44.9% | 25.8% | 45.2% | 25.8% | 45.2% | 25.8% |  |
| 2024 | 20.4% | 15.2% | 20.5% | 15.2% | 20.7% | 15.2% | 21.2% | 15.2% |  |
| 2025 | -2.6% | 6.7% | -3.2% | 6.7% | -3.4% | 6.7% | -4.0% | 6.7% |  |
| 2026 | 3.0% | -4.3% | 3.0% | -4.3% | 1.4% | -4.3% | 1.4% | -4.3% |  |

## Universe attribution

| pair | year | trades_v1 | trades_v2 | buys_v1 | buys_v2 | names_only_v2 | names_only_v1 | gap_years |
|---|---|---|---|---|---|---|---|---|
| baseline (v1, old start) -> (a) v2, old start | 2014 | 1105 | 1110 | 233 | 233 | 3 | 1 |  |
| baseline (v1, old start) -> (a) v2, old start | 2015 | 697 | 730 | 100 | 102 | 2 | 1 |  |
| baseline (v1, old start) -> (a) v2, old start | 2016 | 667 | 666 | 151 | 153 | 2 | 0 |  |
| baseline (v1, old start) -> (a) v2, old start | 2017 | 927 | 933 | 160 | 163 | 13 | 8 | yes |
| baseline (v1, old start) -> (a) v2, old start | 2018 | 715 | 708 | 109 | 107 | 5 | 6 | yes |
| baseline (v1, old start) -> (a) v2, old start | 2019 | 564 | 570 | 117 | 119 | 1 | 0 |  |
| baseline (v1, old start) -> (a) v2, old start | 2020 | 777 | 759 | 168 | 167 | 1 | 1 |  |
| baseline (v1, old start) -> (a) v2, old start | 2021 | 1155 | 1150 | 206 | 205 | 1 | 1 |  |
| baseline (v1, old start) -> (a) v2, old start | 2022 | 835 | 827 | 157 | 157 | 1 | 0 |  |
| baseline (v1, old start) -> (a) v2, old start | 2023 | 856 | 863 | 149 | 149 | 0 | 0 |  |
| baseline (v1, old start) -> (a) v2, old start | 2024 | 1018 | 1021 | 203 | 203 | 0 | 0 |  |
| baseline (v1, old start) -> (a) v2, old start | 2025 | 606 | 603 | 118 | 116 | 1 | 4 |  |
| baseline (v1, old start) -> (a) v2, old start | 2026 | 382 | 387 | 75 | 76 | 2 | 1 |  |
| (b) v1, new start -> final (v2, new start) | 2014 | 1105 | 1102 | 235 | 236 | 3 | 2 |  |
| (b) v1, new start -> final (v2, new start) | 2015 | 745 | 753 | 105 | 106 | 2 | 1 |  |
| (b) v1, new start -> final (v2, new start) | 2016 | 707 | 701 | 154 | 155 | 1 | 0 |  |
| (b) v1, new start -> final (v2, new start) | 2017 | 896 | 900 | 163 | 164 | 12 | 9 | yes |
| (b) v1, new start -> final (v2, new start) | 2018 | 698 | 681 | 105 | 103 | 5 | 5 | yes |
| (b) v1, new start -> final (v2, new start) | 2019 | 542 | 545 | 116 | 117 | 1 | 0 |  |
| (b) v1, new start -> final (v2, new start) | 2020 | 792 | 795 | 165 | 166 | 2 | 0 |  |
| (b) v1, new start -> final (v2, new start) | 2021 | 1132 | 1142 | 201 | 204 | 3 | 0 |  |
| (b) v1, new start -> final (v2, new start) | 2022 | 877 | 876 | 164 | 167 | 5 | 0 |  |
| (b) v1, new start -> final (v2, new start) | 2023 | 812 | 814 | 141 | 140 | 0 | 0 |  |
| (b) v1, new start -> final (v2, new start) | 2024 | 1034 | 1032 | 190 | 190 | 0 | 0 |  |
| (b) v1, new start -> final (v2, new start) | 2025 | 599 | 598 | 120 | 119 | 0 | 1 |  |
| (b) v1, new start -> final (v2, new start) | 2026 | 403 | 404 | 77 | 78 | 0 | 0 |  |

**(b) v1, new start -> final (v2, new start)**: 4 names held only with v2 (total P&L -4,149,791 Rs where known), 2 names held only with v1 (total P&L 954,435 Rs).
Only with v2: GODREJAGRO (2018-05-08..2018-05-15), GUJENERGY (2017-05-02..2021-09-14), PIRAMALFIN (2014-07-15..2017-12-12), RAJTV (2014-03-25..2014-04-22)
Only with v1: FMGOETZE (2014-08-12..2014-09-23), HATHWAY (2017-02-14..2017-02-28)

**baseline (v1, old start) -> (a) v2, old start**: 3 names held only with v2 (total P&L -484,778 Rs where known), 3 names held only with v1 (total P&L -161,168 Rs).
Only with v2: GUJENERGY (2017-04-25..2021-05-25), MTEDUCARE (2014-09-02..2014-10-28), PIRAMALFIN (2014-07-15..2017-12-12)
Only with v1: NYKAA (2025-11-18..2025-12-23), PTCIL (2025-12-30..2026-02-24), WABAG (2017-05-30..2017-06-13)

## Start rule: the first sessions of 2014

| run | first_signal | first_fill | buys_at_first_fill | strategy_2014-01-02_to_01-08 | nifty_2014-01-02_to_01-08 | invested_share_first_session |
|---|---|---|---|---|---|---|
| baseline (v1, old start) | 2014-01-07 | 2014-01-08 | 39 | 0.1% | -1.8% | 0.9929566261636815 |
| (a) v2, old start | 2014-01-07 | 2014-01-08 | 39 | 0.1% | -1.8% | 0.9929566261636815 |
| (b) v1, new start | 2013-12-31 | 2014-01-01 | 37 | 0.5% | -1.8% | 0.9862738771404163 |
| final (v2, new start) | 2013-12-31 | 2014-01-01 | 37 | 0.5% | -1.8% | 0.9862738771404163 |

## Universe-sensitive red flags, re-checked

- baseline (v1, old start): 2014 strategy 71.0% vs NIFTY 37.6% (early survivorship: ? of ? first-signal members priced, 0 names never priced); small-cap NAV share 36.4%; factor alpha t 1.88 headline, 2.11 no-filter; alpha 6.1% a year.
- (a) v2, old start: 2014 strategy 72.3% vs NIFTY 37.6% (early survivorship: 468 of 500 first-signal members priced, 38 names never priced); small-cap NAV share 37.6%; factor alpha t 1.70 headline, 2.03 no-filter; alpha 5.5% a year.
- (b) v1, new start: 2014 strategy 69.0% vs NIFTY 37.6% (early survivorship: 467 of 500 first-signal members priced, 32 names never priced); small-cap NAV share 38.4%; factor alpha t 1.69 headline, 2.03 no-filter; alpha 5.5% a year.
- final (v2, new start): 2014 strategy 66.2% vs NIFTY 37.6% (early survivorship: 467 of 500 first-signal members priced, 39 names never priced); small-cap NAV share 38.0%; factor alpha t 1.52 headline, 1.94 no-filter; alpha 4.9% a year.

## Note for Rohit

The 'Rohit Rakhecha - Adjusted Prices' folder is empty on this machine. The unpriced names in each run's Notes are in the universe but have no Ace price for the dates they were members; price history for them is the only fix for the remaining survivorship bias. PIRAMALFIN and GUJENERGY in the lists above are the Ace master's current symbols for the DHFL and GUJGASLTD ISIN keys.
