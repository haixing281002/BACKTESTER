---
description: "Stage 00 — screen a paper for relevance to a long-only Indian equity mandate"
argument-hint: "<paper.pdf>"
---

# Stage 00 — TRIAGE  (LLM owns)

Screen `$1` for a **long-only Indian equity fund benchmarked to NIFTY 500**.
We cannot short, cannot use derivatives, and hold daily index closes only.

Read only the title and abstract — the first page is enough. This stage is meant
to be cheap; a wrong answer costs one unnecessary full read and the next stage
catches it.

**Judge the mechanism, not the market.** A US multi-asset paper can still be
relevant if what generates its excess return could survive our constraints. Mark
it irrelevant only when the mechanism itself cannot.

Write `outputs/interpretation/<slug>__triage.json` conforming to `TriageVerdict`
in `ros/agents/schemas.py`, then:

```bash
python -m ros.interpretation validate outputs/interpretation/<slug>__triage.json --schema TriageVerdict
python -m ros.interpretation record --stage 00_triage \
    --output outputs/interpretation/<slug>__triage.json \
    --operator "<the human's name>" --input "$1"
```

Ask the operator for their name if you do not know it. Report the verdict and the
single clearest reason in two lines.
