---
description: "Stage 02b — adversarially attack a drafted Strategy Card"
argument-hint: "<card.yaml> <paper.pdf>"
---

# Stage 02b — AMBIGUITY CRITIC  (LLM owns)

You are **not** drafting. Read the card `$1` against the paper `$2` and find what
the drafter got wrong or waved through. Read the PDF yourself; do not trust the
analysis file.

Hunt specifically for:

- a metric defined non-standardly in the paper but implemented as standard
  (Sharpe conventions are the classic case — a geometric CAGR-based Sharpe and
  the conventional arithmetic one differ by roughly half the variance)
- costs that exclude the strategy's **principal activity**
- an estimator whose window is too short for its parameter count
- a risk-free rate used simultaneously as numeraire and as an achievable yield
- any card field stated with more precision than the paper supports
- constraints the paper assumes that a long-only fully-invested mandate cannot meet
- parameter sweeps the paper ran that the card's `n_configs_tried` ignores
- a `convertibility` chain whose weakest link is not the weakest link. This is
  the highest-value attack available to you: the drafter picked which link they
  least believe, and a drafter is systematically optimistic about the link they
  would have to do the most work to fix
- `decisive_evidence` that names something the card never requests, or a
  `data_request` that would not move the verdict either way and is not marked
  `nice_to_have`
- a `without_it` fallback that reads like a fallback but concedes nothing —
  "we would proceed with a reasonable assumption" is a placeholder in a suit

Write `outputs/interpretation/<slug>__critique.json` conforming to
`AmbiguityReport`. Populate `missed_by_first_pass` with every field the draft
treats as settled that is not.

**Do not manufacture findings.** A critic that always finds something is as
useless as one that never does. If a point is genuinely sound, leave it.

```bash
python -m ros.interpretation validate outputs/interpretation/<slug>__critique.json --schema AmbiguityReport
python -m ros.interpretation record --stage 02_critique \
    --output outputs/interpretation/<slug>__critique.json --operator "<name>" --input "$1" --input "$2"
```
