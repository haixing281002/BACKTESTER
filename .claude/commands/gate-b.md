---
description: "Gate B — assemble the IC briefing. You do NOT vote."
argument-hint: "<report.txt>"
---

# GATE B — INVESTMENT DECISION

**No model votes here.** You assemble the briefing; a named PM or IC rules.

From `$1`, write `outputs/interpretation/<slug>__gate_b_brief.md`, at most one
page:

1. **The single sentence** a PM needs: what this is, and what the evidence supports.
2. **The eight Gate B criteria**, each PASS/FAIL with its number.
3. **The decisive one.** Usually incremental IR or the factor fingerprint, not
   standalone Sharpe. Name it.
4. **What would have to change** for the answer to differ — new data, a different
   mandate, a fixed proxy.
5. **What this costs to run** if approved: turnover, days to execute a rebalance.

Be careful with your own framing. You chose what to foreground, and that shapes a
decision even though you cast no vote. Lead with the criterion that failed hardest,
not the most flattering number available.

End with exactly this, and nothing that reads like a recommendation dressed as a
summary:

> Evidence supports: **<PROMOTE|OBSERVE|REJECT>**. No decision has been made.
> A named PM records it with:
> `python run_pipeline.py --card <card> --decision <APPROVE|OBSERVE|FIX|REJECT> --decided-by "<name>" --rationale "…"`

```bash
python -m ros.interpretation record --stage gate_b \
    --output outputs/interpretation/<slug>__gate_b_brief.md --operator "<name>" --input "$1"
```
