---
description: "Full pipeline on one paper, stages 00 through Gate B"
argument-hint: "<paper.pdf>"
---

# Paper to Position — the whole chain on `$1`

## First: is there a paper?

**If `$1` is empty, do not proceed and do not pick one.** Run:

```bash
python -c "from ros.papers import ask_for_a_paper; print(ask_for_a_paper())"
```

and show the result. It lists the PDFs already in the repo and says how to add a
new one. Then ask which paper they want, and wait.

There is no default paper. A default would mean a run that quietly analysed last
week's PDF looked exactly like a run that analysed theirs — and by the time that
surfaces, a Gate A queue has been reviewed and signed against the wrong work.

**If `$1` is given, confirm what you are about to read before reading it:**

```bash
python -c "
from ros.papers import require_paper
p = require_paper('$1')
print(f'{p.path}\n  {p.size:,} bytes   sha256 {p.short_sha}   slug: {p.slug}')"
```

Say the title back to them once you have opened page 1. If it is not the paper
they meant, it is far cheaper to find out now than at Gate A.

## The chain

Work the checkpoints in order. Stop and report at each gate; do not run past a
human decision point.

1. `/triage $1` — is this worth a full read?
   **Stop if not relevant.** Record the verdict and say why.
2. `/ingest $1` — read the rendered PDF properly. This is the heavy stage: it
   decides **which Indian universe** the paper should be tested on and
   **what the strategy actually is**.
3. `/draft-card <analysis.json> adaptation` — write the Strategy Card.
4. `/critique-card <card.yaml> $1` — attack your own draft.
   Fold anything material back into the card, then re-validate it.
5. `/map-data <card.yaml>` — the gate binds, you advise.
6. `/gate-a <card.yaml>` — assemble the human queue.
   **STOP HERE.** Present the queue and wait. Do not proceed until the operator
   confirms. This is the point of the gate: everything after it is expensive.

**Everything above needs NO MARKET DATA.** You can take any paper to Gate A with
nothing but the PDF. To see the whole picture in one deterministic pass:

```bash
python run_interpret.py --pdf $1
```

That prints the extraction floor, the universe choice against its ranked
alternatives, the strategy, the Gate A checklist, and — the useful part — exactly
which data series would have to be supplied for this specific paper to become
testable. A shortfall there is a normal outcome, not a failure: it tells the fund
what to buy, for a reason.

If data is needed, say so plainly and stop. The operator supplies it at Gate A
(`data/raw/` plus a `data/raw/MANIFEST.yaml` entry) and the run continues from
there. Do not improvise a substitute series to keep moving.

## After Gate A, only if data is in place

7. `/run <card.yaml>` — the deterministic pipeline, stages 03–08.
8. `/critique-results <report.txt>` — attack the output.
9. `/gate-b <report.txt>` — assemble the IC briefing.
   **STOP.** The evidence supports something; you do not decide what happens.

Throughout: you interpret, code computes, a human allocates. If you find yourself
about to estimate a statistic in conversation, write code instead. If you find
yourself about to say "so we should approve this", stop — that is not yours.
