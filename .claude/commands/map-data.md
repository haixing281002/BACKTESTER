---
description: "Stage 03 — map a paper's data requirements onto what the fund holds"
argument-hint: "<card.yaml>"
---

# Stage 03 — DATA FEASIBILITY  (code binds, LLM advises)

**The deterministic gate owns the verdict.** Run it first and read it:

```bash
python -c "
from ros.cards.schema import load_card
from ros.data.firm_registry import build_firm_registry
from ros.feasibility import assess
print(assess(load_card('$1'), build_firm_registry()).render())"
```

Your job is the judgement the gate cannot make: whether anything we hold could
genuinely stand in, what a substitution costs **economically**, and what to buy.

A proxy is only a proxy if it can carry the same economic role. A constant assumed
rate is not a proxy for a policy rate that moves — say so, and say what breaks.
When you propose one, name the specific economic claim that changes, not a generic
caution.

Write `outputs/interpretation/<slug>__datamap.json` conforming to
`FeasibilityMapping`, with `procurement_suggestions` ordered by how much each
unblocks. Be concrete about the series, not the vendor.

**Where you disagree with the gate, say so plainly — and the gate still stands.**
A disagreement is a procurement question for a human, never a licence to proceed.
You cannot edit `ros/data/firm_registry.py` to make a series exist.

```bash
python -m ros.interpretation record --stage 03_data_mapping \
    --output outputs/interpretation/<slug>__datamap.json --operator "<name>" --input "$1"
```
