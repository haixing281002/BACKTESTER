# Pipeline review — issues, red flags and green flags at every step

Written from the test case: **Devanathan, Tzikas & Boyd (Sept 2026), *Simple Dynamic
Stock/Bond/Gold Portfolios***, run against our NSE factor-index dataset, plus a second
paper (Moskowitz–Ooi–Pedersen time-series momentum) used to prove the engine is
paper-agnostic.

Every number quoted below is reproducible from `outputs/`.

---

## Headline outcome

| Card | Mode | Stopped at | Outcome |
|---|---|---|---|
| `devanathan_2026_replication` | replication | **Step 03** | FAIL_FAST_DATA — 0/13 mandatory series held |
| `devanathan_2026_india_factor_adaptation` | adaptation | **INDIA_VALIDATED** | REJECTED |
| `moskowitz_2012_tsmom_india` | adaptation | **INDIA_VALIDATED** | REJECTED |

Both adaptations **lose to buying the NIFTY500 MULTIFACTOR MQVLV 50 index**, which costs
nothing to run and has zero turnover. That is the finding. It is a good one: it was
produced in one session, it is fully lineaged, and it is now permanently in the library so
nobody pays for it twice.

---

## STEP 01 — INGEST

### Issues found
- **`pdfplumber.extract_tables()` returned 0 tables** on a paper full of them. Academic
  papers use LaTeX `booktabs`, which draws almost no ruling lines, and the ruled-table
  detector needs rules. The tables it missed are precisely the results tables that define
  replication targets. Fixed with a **text-geometry parser** (a row = a label followed by
  ≥2 numeric tokens, anchored to its `Table N:` caption): **19 tables, 64 candidate
  targets recovered**, including Table 1 exactly.
- **Equations are destroyed by text extraction.** 7.2% of lines carry math fingerprints.
  `w^spy_t + w^agg_t + w^gld_t ≤ 1` extracts as `wspy +wagg +wgld ≤ 1` — subscripts gone.
  An LLM handed this will confidently reconstruct a *plausible wrong* formula.
- **Rotated figure text extracts reversed** — pages 10, 12, 13, 15, 16, 30 contain
  `nruter evitalumuC` (Cumulative return). Numbers on these pages are axis ticks, not
  results. The scanners skip these pages entirely.
- **Harvesting all targets produces contradictory ones — 22 conflicts detected.**
  Markowitz Sharpe appears as **1.08** (Table 1, pre-tax), **0.99** (p17,
  inflation-adjusted), **0.83 / 0.67 / 0.64** (p19, three tax brackets) and **1.01**
  (p34, lagged-data variant). Accept all of them and the replication test *can never
  fail* — some row always matches.

### 🟢 Green flags
- Machine-readable text, 93k characters, no OCR needed.
- **Open-source code published** (`github.com/cvxgrp/simple-portfolio-code`) — the single
  strongest replication signal available; it converts a replication from archaeology into
  a diff.
- Explicit data provenance named in-text: Yahoo Finance, FRED, Kenneth French.
- Results tables are clean and complete enough to serve as hard targets.

### 🔴 Red flags
- Equation-bearing text cannot be trusted; any card field derived from a formula must be
  checked against the rendered page by a human. Gate A carries this as a standing warning.
- Metric values are reported on ≥4 accounting bases without a single canonical table.
- Figure-only results (the risk-return frontier, §3.4) are unreadable from text and cannot
  be turned into targets at all.

---

## STEP 02 — STRATEGY CARD

Seven material ambiguities were logged **and resolved** before any code ran. These are the
ones that would have quietly broken a replication:

| # | Field | Issue | Why it matters |
|---|---|---|---|
| 1 | `metrics.sharpe` | Sharpe is **geometric** — (CAGR − compounded fed funds CAGR) / vol — not the conventional arithmetic-excess Sharpe | Differs by ~½σ²; ~0.05 Sharpe at 10% vol. Enough to fail a replication that is actually correct. The engine now reports **both**, always. |
| 2 | `signal.lookback_days` | The 11-day window was chosen "after a modest search over various values" | The headline is **in-sample at the hyperparameter level**. Inflates the trial budget. |
| 3 | `portfolio.target_vol` | 7% is asserted, not derived; §3.4 then sweeps 3–12% in 0.5% steps | **19 further configurations** on the same sample. |
| 4 | `costs.cost_model` | Appendix A: "moving value into or out of cash is not itself a trade" | **Volatility control works by moving into and out of cash — its main activity is free by construction.** |
| 5 | `signal.cov_estimator` | A 3×3 covariance (6 free parameters) estimated from **11 daily observations** | Near-degenerate. The risk cap it feeds is extremely noisy. |
| 6 | `universe.cash_asset` | The fed funds rate is both the Sharpe numeraire *and* the yield earned on cash | **No investor earns DFF on a cash balance.** This flatters every cash-holding portfolio — which is all the winners. |
| 7 | `signal.alpha_source` | Forecast target is a **100-day forward return**; causality rests on the training set ending at *t−100* | A single off-by-one inflates every downstream number. |

### 🟢 Green flags
- Constraints stated unambiguously: long-only, no leverage, no derivatives, monthly.
- The paper reports its own conventional-Sharpe cross-check and notes its margins are, if
  anything, conservative.
- Hyperparameters are few and disclosed rather than buried.

### 🔴 Red flags
- Issues 2 + 3 together mean the headline Sharpe is **selected**, not estimated.
- Issue 4 is a structural understatement of the cost of the paper's core mechanism.
- Issue 6 means the risk-free asset is simultaneously the benchmark and a holding — an
  investor cannot occupy both sides.

---

## STEP 03 — DATA FEASIBILITY  ← *the step that paid for itself*

**Replication card: `FAIL_FAST`. 0 of 13 mandatory series held.** We have no US ETF
prices, no ETF volumes, no FRED series, no Fama–French factors. The pipeline halted in
seconds, before a line of strategy code was written, and wrote a library entry recording
why plus the conditions under which it becomes viable.

This is the cheapest gate in the system and the highest-value one. It is a **procurement
question, not a research question.**

**Adaptation card: `GO_WITH_PROXY`, with 8 sign-offs required** — 7 DEGRADED series
(backfilled) and 1 PROXY (the cash rate).

### 🔴 Red flags on our own data
- **Every factor index starts at exactly 1000.00 on 2005-04-01.** That is the signature of
  a rebased, **backfilled** index. NSE defined these sleeves years after 2005; the
  construction rules were chosen knowing the intervening returns. **Selection bias is
  built into the series itself**, and no amount of clever backtesting removes it. This
  alone caps the ladder at ROBUST — no live claim may rest on backfilled sleeve history.
- **Price-return, not total-return.** ~1.3–1.5% p.a. of dividends missing from every
  series. Biases every equity-vs-cash comparison against equity.
- **An index is not a portfolio.** No replication tracking error, no rebalance impact, no
  sleeve-level turnover is charged inside the index level.
- **No Indian risk-free series at all.** The cash proxy is a declared constant 6%. It is
  wrong in level *and in shape* — it cannot capture the 2009 or 2020 easing cycles, which
  is exactly when a de-risking strategy is sitting in cash.
- Benchmark coverage ends 2026-05-29, nine trading days before the sleeves.

### 🟢 Green flags
- 5,247 complete daily observations, **zero internal gaps, zero stale runs, zero
  non-positive prices, no return above 16.3%** — mechanically clean.
- 21 years spanning 2008, 2013 taper, 2020 and 2022 — several genuine regimes.
- The proxy is *declared*, appears in the feasibility report, the snapshot manifest and the
  final report, and is **swept 4–8%** rather than assumed.

---

## STEP 04 — POINT-IN-TIME DATA + LINEAGE

Every run freezes a snapshot recording: source SHA-256, materialised-frame content hash,
engine code hash, git commit, every transformation in order, declared PIT status, and
every proxy used. `verify()` re-derives the content hash; the test suite confirms a
1e-9 mutation is detected.

### 🔴 Red flags
- `pit_status = backfilled` for **everything we own**. There is no true point-in-time
  series in this dataset.
- No membership history, no corporate actions, no publication dates — so index
  reconstruction cannot be independently validated.

### 🟢 Green flags
- Lineage is mandatory and automatic; a result that cannot cite a snapshot cannot exist.
- Proxies cannot be silent: the builder records them structurally.
- The data audit (gaps, stale runs, extreme returns, non-positive prices) runs before any
  backtest touches the frame.

---

## STEP 05 — BUILD + EXECUTE

Two genuine bugs were caught here **by the pipeline's own checks**, not by inspection:

1. **The look-ahead tripwire was broken.** Its negative control used `returns.shift(-1)`
   while the check correlated signal[t] against return[t] — testing a leak it could not
   see. Rewritten to check **both** leak classes (h=0 same-bar, h=1 next-bar); both
   planted controls are now caught on every run, and the live signals pass.
2. **Runs started on different dates.** The Markowitz strategy cannot rebalance until its
   252-day EWMA exists; equal-weight trades from day one. Unaligned, the strategy carried
   ~250 days of flat NAV while benchmarks banked a real year. **Fixing this changed the
   ranking**: the vol-target overlay went from *beating* equal-weight sleeves (0.60 vs
   0.49) to *losing* to them (0.42 vs 0.45). The earlier result was an artifact.

A third coherence bug: the cost sweep charged higher spreads without telling the optimiser,
so it kept trading as if costs were 30bp. Now the swept spread enters the allocator's
objective too — and turnover correctly falls from 262% to 67% as costs rise 0→100bp.

### Results (net of 30bp, mandate-compliant variants, common window from 2006-04-29)

| Portfolio | CAGR | Vol | Sharpe | Max DD | Turnover |
|---|---|---|---|---|---|
| **NIFTY500 MULTIFACTOR MQVLV 50** (buy & hold) | **15.1%** | 17.4% | **0.53** | 54.8% | **0%** |
| Equal-weight sleeves | 15.0% | 20.2% | 0.45 | 64.0% | 5% |
| **Markowitz adaptation [fully invested]** | 15.2% | 21.2% | **0.44** | 69.3% | 147% |
| Inverse vol / Equal risk contribution | 14.3% | 19.4% | 0.43 | 62.4% | ~91% |
| Vol-target overlay | 13.0% | 16.9% | 0.42 | 54.0% | 77% |
| Min variance | 12.5% | 17.0% | 0.39 | 54.7% | **553%** |
| Markowitz adaptation [holds cash] | 12.1% | 17.5% | 0.35 | 53.3% | 160% |
| NIFTY 500 | 10.5% | 20.4% | 0.22 | 64.3% | 0% |

**The paper's central mechanism is the second-worst performer here.** Every sleeve
strategy beats NIFTY 500 — but that is the factor premium (and its backfill), not the
paper's contribution.

### 🔴 Red flags
- Min variance turns over **553% a year** on an 11-day covariance — the estimator is so
  noisy the portfolio flips constantly. A direct demonstration of ambiguity #5.
- The optimiser sits at **100% cash through much of 2008–2009** (48.6% and 50.9% average).
  Excellent risk control; completely outside a long-only equity mandate.

### 🟢 Green flags
- 242 solves, **0 solver failures**; PSD projection handles the indefinite short-window
  covariances cleanly.
- Both planted look-ahead controls caught; both live signals pass.
- 17 engine tests pass, including exact cost arithmetic, the buy-and-hold identity, the
  cash-accrual identity, and constraint satisfaction for the Markowitz problem.

---

## STEP 06 — RESEARCH VALIDATION

| Check | Result | Verdict |
|---|---|---|
| Replication gap | N/A — adaptation card | correctly refused |
| Sub-period Sharpe | 0.16 → 0.44 → 0.67 → 0.69 across four 5-year blocks | 🔴 monotonically rising — **regime, not skill** |
| Walk-forward (anchored, 4 folds) | 0.79 / **0.19** / 0.64 / 0.88 | 🔴 one window near zero |
| Paired bootstrap vs Equal-weight sleeves | mean Δ **−0.01**, CI [−0.15, +0.14], P(no advantage) **0.54** | 🔴 coin flip |
| Paired bootstrap vs MQVLV | mean Δ **−0.09**, P(no advantage) **0.79** | 🔴 loses |
| Paired bootstrap vs NIFTY 500 | mean Δ +0.22, CI [+0.01, +0.46], P = 0.021 | 🟢 the *only* thing it beats |
| **Deflated Sharpe** | 7 trials → threshold **1.39**; observed **0.51**; **P(skill) = 0.0%** | 🔴 fails outright |
| Cost breakeven | Sharpe 0.49 → 0.37 across 0→100bp | 🟢 not cost-killed |
| **Lag sensitivity** | 0.43 (lag 0) → **0.47 (lag 10)** | 🔴 **Sharpe *improves* with delay** |
| Target-vol sweep | monotone decreasing, 0.45 → 0.37 | 🔴 the "edge" is just de-risking |
| Cash-rate proxy sweep | 0.54 (4%) → 0.35 (8%) | 🔴 **highly proxy-dependent** |

Two of these deserve emphasis.

**The lag test is the most damning.** A genuine timing signal decays as you delay
execution. This one *improves* — trading ten days late is better than trading on time.
That is not a signal with an implementation constraint; that is **no timing information at
all**. A backtest can look fine and still fail this.

**The bootstrap intervals are enormous** — Sharpe CI [−0.12, +1.13] on 20 years of daily
data. This is honest and it is the norm: Sharpe ratios estimated over two decades are
barely distinguishable from zero. The source paper reports the same problem (its own
50/30/20 comparison narrowly includes zero). Anyone quoting a point Sharpe without an
interval is not showing you the uncertainty.

---

## STEP 07 — PORTFOLIO VALIDATION  ← *the step that actually decides*

| Check | Result | Verdict |
|---|---|---|
| Beta to NIFTY 500 | 0.95 | — |
| Alpha vs benchmark | +4.9% p.a., IR 0.50, TE 8.9% | 🟢 looks good in isolation |
| **Factor fingerprint R²** | **0.952** against the five sleeves | 🔴 it *is* the sleeves |
| **Alpha vs sleeves** | **+0.17% p.a., HAC t = 0.15, p = 0.88** | 🔴 **indistinguishable from zero** |
| Max correlation to an available alternative | **0.974** (equal-weight sleeves) | 🔴 not differentiated |
| **Incremental IR** | **−0.003 / −0.007 / −0.017 / −0.036** at 5/10/20/35% sleeve | 🔴 **negative at every size** |
| Mandate (fully-invested variant) | passes, 0% cash | 🟢 implementable |
| Mandate (faithful variant) | **violates — up to 100% cash** | 🔴 un-runnable as published |
| Capacity | 147% turnover, ₹243cr per rebalance, **8.1 days to execute** at ₹1,000cr AUM | 🔴 operationally heavy |

**This is the decisive table.** The +4.9% alpha versus NIFTY 500 evaporates to **+0.17%
with a t-stat of 0.15** once you control for the factor sleeves you already own. The
strategy is a 0.97-correlated repackaging of an equal-weight sleeve basket, with 147%
turnover instead of 5%, and it makes the book's information ratio **worse at every
allocation size**.

A standalone Sharpe of 0.44 looked survivable. Step 07 is where it dies — which is exactly
why orthogonality and incremental IR are gating criteria and not footnotes.

---

## GATE B + STEP 08

Gate B: **6 of 8 blocking criteria failed** → BLOCKED, decision REJECT.
Ladder: **stopped at INDIA_VALIDATED**, criterion *"beats every free alternative the fund
already has"* → **−0.09 Sharpe vs MQVLV**. Nothing above that rung was evaluated, because
nothing should be.

The library now holds three entries — one fail-fast and two rejections — each with its
snapshot hash, code hash, gate records, factor fingerprint and lessons. Duplicate-experiment
detection and fingerprint cosine-similarity search both work, so the same disappointment
cannot be bought twice.

---

## Second paper: does the framework actually generalise?

`cards/moskowitz_2012_tsmom_india.yaml` — long-only time-series momentum, a completely
different mechanism (trend filter + inverse-vol sizing, not mean-variance optimisation).

**Cost to support it: one allocator template (~30 lines) and one branch in the alpha
builder.** The backtest engine, accounting, validation suite, gates and ladder were not
touched. It ran all eight steps first time.

Result: mandate variant Sharpe **0.54**, versus MQVLV **0.59** — loses by 0.06, deflated
Sharpe P(skill) **0.4%**, stopped at the same rung. Worth noting: its cash-holding variant
cut max drawdown to **37.9%** versus MQVLV's 54.8%, which is genuinely good risk control —
but it is the cash doing the work, and the mandate forbids the cash.

---

## What I would do next

1. **Do not run either strategy.** Neither beats an index you can buy tomorrow for a
   management fee.
2. **Procure a real Indian cash/T-bill series.** It is the cheapest gap to close and the
   cash-rate sweep shows it moves the Sharpe by 0.19.
3. **Procure total-return versions of these indices.** Price-return indices bias every
   comparison and the fix is a data request, not research.
4. **Re-run on post-launch-only history.** Restricting to each index's genuine live period
   removes the backfill bias. It shortens the sample severely — which is itself the
   finding.
5. **The mechanism worth keeping is drawdown control, not return enhancement.** Both
   adaptations cut max drawdown meaningfully *when allowed to hold cash* (53% and 38% vs
   64% for NIFTY 500). If the fund ever gets a cash or hedging allowance, re-card that
   specific question. Do not test it as a return strategy again — that question is now
   answered and stored.
6. **Point the pipeline at papers written about Indian equities**, cross-sectionally, on
   data we hold. The screening cost is now minutes per paper, which is the throughput the
   board asked for.
