---
description: "Stage 02 — draft a Strategy Card from an ingested analysis"
argument-hint: "<analysis.json> [replication|adaptation]"
---

# Stage 02 — STRATEGY CARD  (LLM owns, code validates)

Read `$1` (a `PaperAnalysis`). Mode is `$2`, defaulting to `adaptation`.
If no analysis exists yet, run `/ingest` first — do not card from the abstract.

Before drafting, read `ros/cards/schema.py` for the field contract and
`cards/devanathan_2026_india_factor_adaptation.yaml` as a worked example.

Write `cards/<slug>_<mode>.yaml`. Hard rules:

- `signal.template` must name one of the **registered** templates
  (`python -c "from ros.engine.templates import list_templates; print(list_templates())"`).
  If none fits, say so in the human queue rather than inventing a name.
- A **replication** card runs the paper's own data and must carry
  `replication_targets` pinned to **one** accounting basis — the headline one.
- An **adaptation** card runs our data, must state `transferred_mechanism`, must
  enumerate `broken_assumptions`, and carries **no** replication targets. It is a
  different question and may never be scored against the paper's numbers.
- Every ambiguity carries a resolution. An unresolved one blocks Gate A, so if you
  cannot resolve it, it belongs in the human queue instead of half-written.
- `n_configs_tried` counts what the **paper** tried, appendix sweeps included.
  Understating it is how a lucky draw launders itself through the deflated Sharpe.
- Costs: 30bp round trip. Do not copy the paper's assumption.
- `lag_days` >= 1. NSE closes publish after the close.
- Set `mandate_allow_cash: false` — this fund is fully invested. If the mechanism
  needs cash, run both variants and say the mandate one governs.

Validate before you claim anything:

```bash
python -c "from ros.cards.schema import load_card; c=load_card('cards/<slug>_<mode>.yaml'); print('valid', c.fingerprint())"
python -m ros.interpretation record --stage 02_card --output cards/<slug>_<mode>.yaml \
    --operator "<name>" --input "$1"
```

Then run `/critique-card` on it. Do not skip that — you are invested in your own
card being coherent.

---

## Score the card before you hand it over

```bash
python -c "
from ros.cards.schema import load_card
from ros.cards.completeness import assess
print(assess(load_card('cards/<slug>.yaml')).render())"
```

42 checks, drawn from what a strong card actually contains. Each one names the
failure it prevents rather than asserting a house style, so a gap is an argument
to answer, not a box to tick. The repo's worked example scores 99%; a card that
validates but says nothing scores 17%.

**Anything marked `MISS` is worth fixing before Gate A.** Those are the gaps a
reviewer cannot work around: no source sha256, no transferred mechanism, no
transfer risks, a cost copied from the paper, unresolved ambiguities.

## Two sections that are yours to fill, and easy to leave empty

### `data_requests` — what you would ask the fund for

You have just read the paper and you know what would make this test better than
it can currently be. Say so. One entry per thing, each with:

- **`why`** — what the mechanism needs it for
- **`unlocks`** — what becomes possible
- **`without_it`** — **mandatory.** The fallback, and what it costs. A request
  with no fallback is a demand, and a demand at Gate A stops the work instead of
  informing it. "Declared constant 6% proxy, swept 4-8%, so every cash result is
  rate-dependent" lets a human decide. "We need a rate series" does not.
- **`priority`** — `blocking` only if the test is genuinely impossible without
  it. `blocking` halts Gate A, so use it when that is the honest answer and not
  as emphasis.
- **`format_hint`** — the columns you want, so nobody has to guess.

If nothing would improve the test, leave it empty — but that is a strong claim
and the completeness check will say so, because silence reads as nobody having
looked.

### `open_questions` — what the paper does not settle

Not ambiguities. An ambiguity is a call you MADE and resolved. An open question
is a call that is the fund's to make: a risk budget, which variant governs,
whether a trial count is honest.

**`what_i_assumed` is mandatory** unless you set `blocks_run`. The run proceeds
under your stated guess and a human can overturn it. A question with neither
stalls the pipeline for no reason, which is you asking someone else to do your
job.

Address each one with `ask_of`: `pm`, `data_owner`, `researcher`. A PM should not
have to work out which questions are theirs.

---

# Stage 02 is where the work happens. Gate A only verifies.

A human at Gate A should be **confirming a plan, not writing one.** If they have
to work out the sample window, the warmup, the benchmarks, or what would count as
failure, Stage 02 did not finish. Three sections exist to stop that.

## `data_plan` — design the dataset, do not shop for it

**Order matters. Design the dataset this paper deserves FIRST, then look at what
the fund holds.** Inverting that is how a paper quietly becomes whatever the
available data can answer, which is a different paper with the same title.

So: do **not** open `ros/data/firm_registry.py` before writing this section.
Write what the mechanism needs, from the paper. Check availability afterwards —
Stage 03 does that mechanically and will tell you.

For each field in `ideal`:

- **`why`** — what the mechanism needs it for. Not "prices are needed".
- **`why_granularity`** — **why not coarser, and why not finer.** This is the
  choice that decides what data costs, and it is almost always made by habit.
  A 21-day skip cannot be computed from monthly closes. Twenty years of tick
  data answers a question nobody asked. Say which and why.
- **`why_history`** — why this start date. An unargued start date is one the
  vendor chose for you. Name what the window includes that matters — a stress
  regime, a policy change, the earliest date all series exist.
- **`adjustments`** — corporate actions, free float, publication dates. Two
  vendors sell a file with the same NAME and only one lets you run the strategy.
  The adjustments are the difference.
- **`minimum_viable`** — mark the fields without which the answer is *not
  interpretable*. Without a smallest honest subset, every request reads as
  essential and none can be traded against cost. Be strict: most fields improve
  what you may CLAIM, not what the answer IS.

Then:

- **`rejected_alternatives`** — at least one, with `why_not`. A dataset with no
  rejected alternative was not designed, it was assumed. Include the obvious
  ones and say why they lose: a coarser frequency, a finer one, a broader
  universe, and — if you are about to run on data the fund already holds — that
  option too, with its shortcomings stated rather than forgotten.
- **`granularity_verdict`** — the headline call in one sentence, with its reason.
- **`optimality_argument`** — why THIS dataset is the right way to test THIS
  paper in Indian equities. Optimal, not merely sufficient: every addition you
  considered either tests a different mechanism, cannot form the estimator, or
  prices a decision the strategy does not make.
- **`what_would_change_the_answer`** — which fields could move the verdict versus
  which only change what you may claim from it. This is what lets a null result
  be told apart from an underpowered one.

## `selection` — which securities, and on whose word

**`rule` is always required.** A named list without a rule cannot be re-derived
on any other date.

**An explicit list is optional and dangerous.** Naming Indian stocks from memory
produces a plausible, unverifiable list — and that is *worse* than no list,
because it looks checked and a reviewer skips it.

So if you name securities:

- **`verified_against`** must say what confirmed them: `firm_registry`,
  `master_universe`, `index_factsheet`, `paper`, `supplied_by_human` — or
  `UNVERIFIED`, which is a legal value and which Gate A will surface as a guess.
  **Use `UNVERIFIED` honestly rather than picking a source you did not check.**
- **`as_of`** must give a date. Index membership is true on a date, not in
  general.

If you cannot verify a list, **state the rule and stop there.** "Top decile by
book-to-market within NIFTY 500 constituents as of each rebalance" is complete,
checkable and better than ten tickers you recalled. Then add a `data_request`
for the membership file that would let the rule resolve.

## `backtest_plan` — exactly what will be run

Every field a human would otherwise have to decide:

- **`sample_start` / `sample_end` / `why_this_window`** — an unargued sample is
  the easiest place to pick a period that flatters the result. Say what the
  window includes and what truncating it would hide.
- **`warmup_days` / `why_warmup`** — without it the estimator's burn-in becomes
  part of the track record, and different runs start on different dates. Aligning
  start dates once reversed a ranking in this repo.
- **`rebalance_rule`** — trading days, not calendar dates.
- **`weights_rule`**, and **`explicit_weights`** if the mix is fixed. Long-only
  and summing to at most 1; the schema refuses otherwise.
- **`benchmarks`** — each with **`why_this`**. The promotion question is never
  "is the Sharpe good". Name the do-nothing option, the off-the-shelf product
  that would replace this strategy for zero turnover, and a stripped-down version
  that isolates what the machinery actually buys.
- **`must_beat`** — named BEFORE the run, so the bar cannot move afterwards.
- **`success_looks_like` AND `failure_looks_like`** — both mandatory. A plan that
  cannot fail is not a test, and a success criterion written after the numbers is
  not a criterion.
- **`known_failure_modes`** — the ways this specific mechanism is known to break
  in India.

## Then score it

```bash
python -c "
from ros.cards.schema import load_card
from ros.cards.completeness import assess
c = load_card('cards/<slug>.yaml')
print(c.at_a_glance()); print(c.plan()); print(c.asks())
print(assess(c).render())"
```

62 checks. The repo's worked example scores 99%. Anything marked `MISS` is a gap
a reviewer cannot work around — fix it before Gate A, where it is still cheap.
