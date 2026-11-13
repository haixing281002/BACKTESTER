---
description: "Gate B — report the gate as scored and stop. You do NOT vote."
argument-hint: "<report.txt>"
---

# GATE B — INVESTMENT DECISION

**No model votes here.** You report what the code scored; a named PM or IC rules.

**This is the ONE stop in the chain (changed 2026-10-06).** Everything from
Stage 00 through Stage 07 now runs without pausing for a human — see
`/paper`'s "ONE human checkpoint, at Gate B." Nothing about that autonomy
reaches here: `decision: PENDING` until a named human actually records one,
exactly as always.

**No Gate B brief is written (removed 2026-11-13, operator).** The brief was a model's one-page note built on the old
eight-criterion checklist; it is gone, and so is the "evidence supports" line. Do not write either.

Under Lightyear the gate is scored by code (`ros/governance/gate_v2.py`, Gate B v4): three hard blocks (data integrity,
edge over the benchmark at the card's cost, paired bootstrap) and a scorecard (sub-period stability, factor alpha,
performance after publication). Report those rows exactly as scored, each with its status and its number, and say which
could not be run. Add nothing that reads like a recommendation.

`run_pipeline.py`, the command-line path outside Lightyear, still prints its own older checklist; report it as printed.

End with exactly this:

> No decision has been made.
> A named PM records it with:
> `python run_pipeline.py --card <card> --decision <APPROVE|OBSERVE|FIX|REJECT> --decided-by "<name>" --rationale "…"`
