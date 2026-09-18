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
