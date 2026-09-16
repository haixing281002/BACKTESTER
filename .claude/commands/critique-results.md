---
description: "Stages 06-07 — adversarially attack our own backtest output"
argument-hint: "<report.txt>"
---

# Stages 06–07 — RESULTS CRITIC  (code computes, LLM critiques)

Read `$1` (or the newest `outputs/report_*.txt`). **Do not recompute anything** —
every number there came from deterministic code. Interpret it.

You have no stake in this succeeding. Attack it.

Patterns that should be **blocking**:

- **Sharpe that improves with implementation lag.** A real timing signal decays.
  One that gets better when traded ten days late carries no timing information at
  all — it is a slow exposure that would have been equally available a fortnight
  later.
- **Sub-period performance rising monotonically** while every comparator rises
  too. That is a regime signature, not skill. Check the benchmark's own column.
- **Alpha that survives against the benchmark but not against the factor
  sleeves.** The first number is unaccounted factor beta; only the second is alpha.
- **Negative incremental IR** at realistic sleeve sizes. Standalone Sharpe is
  irrelevant once the book gets worse.
- **Bootstrap intervals comfortably containing zero**, or a paired
  `P(diff <= 0)` above 0.05 against any free alternative.
- **Results that flip inside a declared proxy's plausible range.**
- A headline driven by **one knob** — check the target-vol sweep.

For each finding give a concrete additional test that would settle it.

Write `outputs/interpretation/<slug>__results_critique.json` conforming to
`ResultsCritique`. If the result genuinely survives, say so — a critic that always
condemns is noise.

```bash
python -m ros.interpretation validate outputs/interpretation/<slug>__results_critique.json --schema ResultsCritique
python -m ros.interpretation record --stage 06_results_critique \
    --output outputs/interpretation/<slug>__results_critique.json --operator "<name>" --input "$1"
```
