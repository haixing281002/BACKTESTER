# Research log

Quant AI Researcher

## 2026-11-13: gate-b-tests (experiment, branch `experiment/gate-b-tests`)

**Question.** Which extra statistical tests would help Gate B tell a good strategy from luck?

**Set before the run** (`research/gate_b_tests/config.yaml`, commit 46d4e22):
- Success: a test passes the Clenow run, fails the NIFTY 500 itself and the equal-weight basket, and passes no more than 5% of 200 random 30-stock books.
- Kill: drop a test that passes more than 10% of the random books.

**What was run.** `scripts/gate_v2/experiment_tests.py`: nine tests on the Clenow run (20261111-163906-237b, 0bp), its four comparators, the index, the equal-weight basket and 200 random monthly equal-weight books from NIFTY 500 members, 2014-01 to 2026-09, Ace prices. Outputs: `docs/gate_b/experiment_tests/scores.csv`, `summary.csv`.

**Result.**

| Test | Pass mark | Clenow | Equal weight | Random books passing | Verdict |
|---|---|---|---|---|---|
| Current: paired bootstrap, daily Sharpe | p <= 0.10 | 0.094 pass | 0.214 fail | 9.0% | borderline |
| Paired bootstrap, monthly Sharpe | p <= 0.10 | 0.086 pass | 0.345 fail | 4.0% | keep |
| Probabilistic Sharpe vs the benchmark | >= 0.95 | 0.846 fail | 0.645 fail | 0.0% | fails the candidate |
| Alpha against NIFTY 500, HAC t | >= 2.0 | 2.24 pass | 1.15 fail | 3.5% | keep |
| Active return t-stat | >= 2.0 | 1.52 fail | 1.42 fail | 8.0% | fails the candidate |
| Worst drawdown shallower, share of draws | >= 0.90 | 0.614 fail | 0.072 fail | 0.0% | fails the candidate |
| Upside capture above downside, share of draws | >= 0.90 | 0.991 pass | 0.704 fail | 11.0% | drop |
| Rolling 3-year alpha positive | >= 75% | 87.3% pass | 68.6% fail | 6.0% | borderline |
| Edge left at a 30bp round trip | > 0 | +4.3% pass | +2.8% pass | 27.5% | drop |

**What it shows.**
- 91.5% of the random books beat the index at zero cost (median +2.7% a year). The index is a price index with no dividends and the books are equal-weight, which tilts them to smaller stocks. So "edge over the benchmark > 0" alone tells almost nothing.
- The current daily bootstrap lets through 9% of random books, which is what a 10% pass mark means. The monthly bootstrap (4%) and the alpha t-stat against the index (3.5%) are stricter and both pass the Clenow run.
- The Clenow run fails the three strictest tests (probabilistic Sharpe, active-return t, drawdown).
- Two of its own comparators pass everything it passes: the NSE Momentum 50 index, and the same rules without the 200-day filter (which passes more strongly). That agrees with the amber factor-alpha row: much of the edge is the momentum factor.

**Limits.** One good candidate only, so the pass rates for luck are measured well and the pass rate for skill is not. The deflated Sharpe was not run (no trial count for placebos). Power needs the calibration simulation, which was not run.

**Decision.** None taken. Nothing in the live gate changed. The operator chooses whether any of these join Gate B.
