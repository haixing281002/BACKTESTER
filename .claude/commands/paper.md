---
description: "Full pipeline on one paper, stages 00 through Gate B"
argument-hint: "<paper.pdf>"
---

# Paper to Position — the whole chain on `$1`

Work the eleven checkpoints in order. Stop and report at each gate; do not run
past a human decision point.

1. `/triage $1` — is this worth a full read?
   **Stop if not relevant.** Record the verdict and say why.
2. `/ingest $1` — read the rendered PDF properly, emit a page-anchored analysis.
3. `/draft-card <analysis.json> adaptation` — write the Strategy Card.
4. `/critique-card <card.yaml> $1` — attack your own draft.
   Fold anything material back into the card, then re-validate it.
5. `/map-data <card.yaml>` — the gate binds, you advise.
6. `/gate-a <card.yaml>` — assemble the human queue.
   **STOP HERE.** Present the queue and wait. Do not proceed until the operator
   confirms. This is the point of the gate: everything after it is expensive.
7. `/run <card.yaml>` — the deterministic pipeline, stages 03–08.
8. `/critique-results <report.txt>` — attack the output.
9. `/gate-b <report.txt>` — assemble the IC briefing.
   **STOP.** The evidence supports something; you do not decide what happens.

Throughout: you interpret, code computes, a human allocates. If you find yourself
about to estimate a statistic in conversation, write code instead. If you find
yourself about to say "so we should approve this", stop — that is not yours.
