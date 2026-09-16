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
