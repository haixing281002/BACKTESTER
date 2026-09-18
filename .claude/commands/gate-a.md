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

## Open with the card itself

Three blocks, in this order, before any prose:

```bash
python -c "
from ros.cards.schema import load_card
from ros.cards.completeness import assess
c = load_card('$1')
print(c.at_a_glance())
print(assess(c).render(only_missing=True))
print(c.asks())"
```

1. **At a glance** — universe, signal, lookback, lag, weights, rebalance,
   benchmark, costs, ambiguities, confidence, mandate conflicts, engine. A
   reviewer who reads only this should be able to say "that is not the strategy
   I expected" or "that lag cannot be right". Both objections are cheap here.
2. **Completeness** — what a reviewer will find thin. Report the score and every
   `MISS`; those are gaps nobody can work around.
3. **What the model is asking for** — the data requests and open questions.

That third block is the part people skip and should not. Gate A is a
conversation: the human confirms judgements, and the model says what would let
it do better. Present each request with its fallback, so the answer is a
decision rather than a favour — and put the `ask_of` label on every question, so
a PM is not reading the data owner's queue.

If the card has no requests and no questions, **say that explicitly**. It claims
no further data would improve the test and the paper settled everything, which
is worth confirming rather than passing over.

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

## Then the data shortfall — this is the moment it can still be fixed

Gate A is the last cheap point. If the translation needs instruments the fund
does not hold, print the shortfall block and say plainly that supplying the data
here is a five-minute fix, whereas discovering it after a run is not:

```bash
python -c "
from ros.data.intake import describe_shortfall; print(describe_shortfall(['<missing>']))"
```

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

State the queue length honestly at the top. **If it is long, say so** — a queue
nobody can read is a rubber stamp, and that failure mode arrives exactly when
throughput starts working.

End with: *"Nothing above has been decided. A named researcher confirms these
before Gate A passes."*

```bash
python -m ros.interpretation record --stage gate_a \
    --output outputs/interpretation/<slug>__gate_a_queue.md --operator "<name>" --input "$1"
```
