---
description: "Gate A — assemble the human review queue. You do NOT decide."
argument-hint: "<card.yaml>"
---

# GATE A — HUMAN INTERPRETATION CONTROL

**You do not decide anything here.** Your job is to make a human's five minutes
count: assemble everything they must personally confirm before a line of strategy
code runs. Everything up to this point is cheap; everything after is not.

Read the card `$1`, its analysis and critique in `outputs/interpretation/`, and
the deterministic feasibility verdict.

---

## The one rule: EMIT, DO NOT SUMMARISE

The card is better than any prose retelling of it, and the code already renders
it for a human. A queue that re-describes the universe, the strategy and the
dataset in your own words is strictly worse than the thing it describes: it is
shorter, it loses the argued detail, and it can drift from what the run will
actually do.

So **paste the deterministic output, then add only what a model can add.**

```bash
python run_interpret.py --pdf <paper.pdf> --card $1
```

That one command produces the whole brief a reviewer needs — blocking failures,
where this runs as instruments, what data it takes against what the fund holds,
every judgement call tagged with its owner, what declining each request costs,
the India requirements, the convertibility chain, and the audit trail. Your
queue carries that output. It does not paraphrase it.

**What is yours to write, and nothing else:**

1. Where a reviewer should spend their attention first, and WHY that one and
   not the other nine.
2. What the critique caught that the first draft treated as settled — the one
   thing no deterministic block can know, because it is the difference between
   two versions of a reading.
3. Where you are least confident in your own reading, in your own words.
4. Anything in the paper the card could not hold: extraction concerns, a
   template gap, a policy question the fund has never had to answer.

**Never:**

- Restate a section the code renders. Point at it.
- **Compare this queue to another paper's queue.** "About the same size as the
  devanathan queue" tells a reviewer nothing about THIS paper, and reaching into
  another run's artifacts to say it is how one paper's work starts appearing in
  another's gate. Queue length is a fact about this card. State it and stop.
- Report "no data shortfall" from the feasibility verdict. See below.

## Open with the card itself

Three blocks, in this order, before any prose:

```bash
python -c "
from ros.cards.schema import load_card
from ros.cards.completeness import assess
c = load_card('$1')
print(c.at_a_glance())
print(c.plan())
print(assess(c).render(only_missing=True))
print(c.convertibility_block())
print(c.asks())"
```

Or, for the whole thing assembled the way the reviewer will read it — the
decision brief first, the audit trail after:

```bash
python run_interpret.py --pdf <paper.pdf> --card $1
```

1. **At a glance** — universe, signal, lookback, lag, weights, rebalance,
   benchmark, costs, ambiguities, confidence, mandate conflicts, engine. A
   reviewer who reads only this should be able to say "that is not the strategy
   I expected" or "that lag cannot be right". Both objections are cheap here.
2. **The plan** (`card.plan()`) — the dataset the card designed and why it is the
   right one, which securities and on whose word, and exactly what will be run:
   window, warmup, rebalance, weights, benchmarks with reasons, must-beat, and
   what success and failure look like. **This is the block a human is actually
   verifying.** Gate A is confirmation, not design: if any of it is missing, say
   so plainly and send it back to Stage 02 rather than filling it in yourself.
3. **Completeness** — what a reviewer will find thin. Report the score and every
   `MISS`; those are gaps nobody can work around.
4. **What the model is asking for** — the data requests and open questions.

Two things in block 2 deserve a sentence of their own when you present it:

- **A named security list with `verified_against: UNVERIFIED`** is a guess that
  looks like a fact. Flag it first, above everything else.
- **`failure_looks_like`** is what stops the bar moving after the numbers arrive.
  If it is vague, that is the finding.

That third block is the part people skip and should not. Gate A is a
conversation: the human confirms judgements, and the model says what would let
it do better. Present each request with its fallback, so the answer is a
decision rather than a favour — and put the `ask_of` label on every question, so
a PM is not reading the data owner's queue.

If the card has no requests and no questions, **say that explicitly**, and say
which of the two cases it is. `no_further_data_needed` filled in is a claim a
reviewer can disagree with. Both sections blank is not a claim at all, and it
cannot be told apart from nobody having looked.

## The convertibility verdict is the model's opinion. Present it as one.

`convertibility` is the only section on the card that is an opinion rather than
a reading of the paper. Lead with the **weakest link** and what would settle it,
not with the verdict — the verdict is the least interesting part, because it is
the part a human is most likely to have their own view on. A reviewer who
disagrees with the weakest link has found something; a reviewer who disagrees
with the verdict alone has only voted.

`not_convertible` does not block this gate, and it should not. A well-argued no
here is the cheapest useful output this pipeline produces.

## Then the two that dominate everything else

A reviewer who reads only the first two items must still catch the expensive
mistakes. Put these at the top of the queue, in this order:

**1. THE UNIVERSE.** State it as a sentence a PM can rule on in one read:

> *"The paper studies <source, as constructed>. We propose to test it on
> <target>, a <grade> correspondence. The risk that most worries me is <one>."*

Then show what the code found, not what you believe:

```bash
python -c "
from ros.cards.schema import load_card
from ros.data.firm_registry import build_firm_registry
from ros.data.intake import extend_registry
from ros.data.universes import check_translation
c = load_card('$1'); r, _ = extend_registry(build_firm_registry())
print(check_translation(c.universe_translation, r, long_only=c.portfolio.long_only).render())"
```

Any **DIVERGENCE** line is a top-of-queue item: the card claims something the
registry does not support, and the registry decides. If the source universe is
unrecognised, say so — that means a human either adds it to
`ros/data/universes.py` or corrects the reading.

**2. THE STRATEGY.** One sentence a PM would recognise, then `cross_sectional`,
then — if the source is long-short — exactly what was dropped and what it
plausibly cost. That last point is where most of a long-short paper's result
goes, so it is never a footnote.

If `engine_template` is `NEEDS_NEW_TEMPLATE`, that is a build decision and it
belongs here, with the spec, before anyone spends a day on it.

## Then the data — and there are TWO shortfalls, not one

Gate A is the last cheap point, so this is where data gets supplied. But the
question has two halves and reporting only the first is how a card that holds
none of its own designed dataset gets written up as "no shortfall".

**Shortfall 1 — the named series.** Does every entry in `data_requirements`
resolve against the registry? This is what feasibility answers, and it answers
GO when proxies and degraded series stand in.

**Shortfall 2 — the dataset the card DESIGNED.** Are the `data_plan` fields
marked `minimum_viable` actually in hand? A card can mark "total-return daily
series" and "a real Indian short rate" as minimum-viable, hold neither — price
return indices and a declared 6% constant standing in — and still pass
shortfall 1 on every line.

```bash
python -c "
from ros.cards.schema import load_card, reconcile_data_plan
from ros.data.firm_registry import build_firm_registry
from ros.feasibility import assess
c = load_card('$1')
print(reconcile_data_plan(c, assess(c, build_firm_registry())))"
```

`not_in_hand` is the answer to shortfall 2. If it is non-empty, **say so in the
queue and do not write that there is no shortfall.** The honest sentence is:
every series this card NAMES resolves, and the card is running on a substitute
for its own minimum viable dataset. Both halves are true and only one of them
was being reported.

A run on proxies is a legitimate run. It is not the test the card specified, and
a result from it has to be read as the proxy's answer.

If the data cannot be licensed, that is itself a finding worth recording — it
says what the fund would have to buy, which is a procurement decision rather
than a research one.

The manifest's awkward fields — `pit_status`, `licence`, `caveats` — are
mandatory on purpose and travel with every result computed from the series.
A researcher tempted to type `point_in_time` without checking should be told
that this is the field that decides whether any live claim may rest on the work.

If the data cannot be licensed, that is itself a finding worth recording: it
says what the fund would have to buy, which is a procurement decision rather
than a research one.

## Then the rest of the queue

Each with a page citation and one sentence on why it matters:

1. Every ambiguity you marked **material** or resolved at low confidence
2. Every equation whose confidence is below `high` — "verify eq 3 on p8, it
   governs signal.template"
3. Every **proxy** requiring approval, with the economic claim it changes
4. Every **backfilled** series requiring sign-off
5. Conflicting accounting bases — confirm the card's targets are pinned to one
6. Whether `n_configs_tried` reflects the paper's own sweeps
7. Anything the critic flagged as `missed_by_first_pass`
8. Any extraction concern that would change the reading

State the queue length honestly at the top, as a count of THIS card's items and
which two deserve the most time. **If it is long, say so** — a queue nobody can
read is a rubber stamp, and that failure mode arrives exactly when throughput
starts working. Do not calibrate the length against another paper's queue: that
is not a fact about this paper, and reading another run's artifacts to produce
it is how somebody else's work leaks into this gate.

End with: *"Nothing above has been decided. A named researcher confirms these
before Gate A passes."*

```bash
python -m ros.interpretation record --stage gate_a \
    --output outputs/interpretation/<slug>__gate_a_queue.md --operator "<name>" --input "$1"
```
