---
description: "Stages 03-08 — run the deterministic pipeline on a card"
argument-hint: "<card.yaml>"
---

# Stages 03–08 — THE DETERMINISTIC PIPELINE

```bash
python run_pipeline.py --card $1 --n-boot 2000
```

**No model touches any number this produces.** Feasibility, the frozen snapshot,
the backtest, the bootstrap, the deflated Sharpe, the factor regressions and both
gate checklists are all deterministic Python. Your role is to read the output, not
to compute anything in it.

It ends at **Gate B PENDING**. That is correct and not an error — the pipeline
scores the evidence and stops.

Then read the result and report, in this order:

1. Did the look-ahead tripwires pass, including **both planted controls**? If a
   planted leak was not caught, stop and say so — nothing downstream is
   trustworthy.
2. The performance table. Compare against **every free alternative**: NIFTY 500,
   the equal-weight sleeves, and the off-the-shelf MQVLV index. Beating NIFTY 500
   alone is not interesting.
3. Where the promotion ladder stopped, and the single criterion that stopped it.

Do not summarise this as a success because the run completed. A clean run that
fails six of eight Gate B criteria is a clean run and a failed strategy.
