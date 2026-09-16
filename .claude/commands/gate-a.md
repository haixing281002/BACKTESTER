---
description: "Gate A — assemble the human review queue. You do NOT decide."
argument-hint: "<card.yaml>"
---

# GATE A — HUMAN INTERPRETATION CONTROL

**You do not decide anything here.** Your job is to make a human's five minutes
count: assemble everything they must personally confirm before a line of strategy
code runs. Everything up to this point is cheap; everything after is not.

Read the card `$1`, its analysis and critique in `outputs/interpretation/`, and
the deterministic feasibility verdict. Then produce
`outputs/interpretation/<slug>__gate_a_queue.md` listing, each with a page
citation and one sentence on why it matters:

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
